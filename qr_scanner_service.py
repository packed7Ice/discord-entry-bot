#!/usr/bin/env python3
"""
qr_scanner_service.py - QRコードスキャナーサービス

カメラ映像からQRコードを高速に読み取り、
.envで定義されたOPEN_QR / CLOSE_QR / TEST_QRと照合し、
一致した場合はDiscord Webhookへ通知を送信する。

Features:
- pyzbar優先の高速QR検出（fallback: OpenCV QRCodeDetector）
- エッジトリガ（再アーム）方式による連投防止
- RotatingFileHandlerによるログローテーション
- カメラ切断時の自動リカバリ
- 軽量なUI表示
"""

import os
import sys
import time
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict, Optional, Tuple

import cv2
import requests
from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# pyzbar の読み込み（オプション）
# ---------------------------------------------------------------------------
try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAS_PYZBAR = True
except ImportError:
    HAS_PYZBAR = False

# ---------------------------------------------------------------------------
# 定数（デフォルト値、.envで上書き可能なものもあり）
# ---------------------------------------------------------------------------
WIDTH = 640
HEIGHT = 480
FPS = 30

# スキャン間引き（N フレームに1回だけ QR 解析）
SCAN_EVERY_N_FRAMES = 2

# エッジトリガ再アーム時間（この秒数QRが見えなくなったら再度armed=Trueにする）
REARM_MISS_SEC = 1.0

# カメラ読み取り連続失敗時のリトライ上限
CAM_FAIL_THRESHOLD = 30
CAM_REOPEN_WAIT_SEC = 3.0

# UI表示保持時間
UI_HOLD_SEC = 1.2

# ROI関連
ROI_PADDING = 40
ROI_TIMEOUT_SEC = 2.0

# ---------------------------------------------------------------------------
# ログ設定
# ---------------------------------------------------------------------------
LOG_DIR = Path(__file__).parent / "logs"
LOG_FILE = LOG_DIR / "qr_scanner.log"
LOG_MAX_BYTES = 1 * 1024 * 1024  # 1MB
LOG_BACKUP_COUNT = 5

def setup_logging() -> logging.Logger:
    """ロガーをセットアップ（コンソール + ファイル）"""
    LOG_DIR.mkdir(exist_ok=True)

    logger = logging.getLogger("qr_scanner")
    logger.setLevel(logging.DEBUG)

    # フォーマット
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # コンソールハンドラ
    ch = logging.StreamHandler(sys.stdout)
    ch.setLevel(logging.DEBUG)
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    # ファイルハンドラ（ローテーション）
    fh = RotatingFileHandler(
        LOG_FILE,
        maxBytes=LOG_MAX_BYTES,
        backupCount=LOG_BACKUP_COUNT,
        encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    return logger


logger = setup_logging()

# ---------------------------------------------------------------------------
# .env 読み込み
# ---------------------------------------------------------------------------
load_dotenv(Path(__file__).parent / ".env")

def get_required_env(key: str) -> str:
    """必須環境変数を取得。未設定なら即終了"""
    val = os.environ.get(key)
    if not val:
        logger.critical(f"環境変数 {key} が設定されていません。.env を確認してください。")
        sys.exit(1)
    return val


WEBHOOK_URL = get_required_env("DISCORD_WEBHOOK_URL")
OPEN_QR = get_required_env("OPEN_QR")
CLOSE_QR = get_required_env("CLOSE_QR")
TEST_QR = get_required_env("TEST_QR")

# オプション設定
LOG_RAW_QR = os.environ.get("LOG_RAW_QR", "false").lower() == "true"
SHOW_RAW_TEXT = os.environ.get("SHOW_RAW_TEXT", "false").lower() == "true"

# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------
def clamp(v: int, lo: int, hi: int) -> int:
    return max(lo, min(hi, v))


def qr_preview(text: str, max_len: int = 10) -> str:
    """QRコード内容のプレビュー（先頭N文字）"""
    if len(text) <= max_len:
        return text
    return text[:max_len] + "..."


def identify_qr(text: str) -> str:
    """QRコード文字列を種類に分類"""
    if text == OPEN_QR:
        return "OPEN"
    elif text == CLOSE_QR:
        return "CLOSE"
    elif text == TEST_QR:
        return "TEST"
    else:
        return "UNKNOWN"

# ---------------------------------------------------------------------------
# Discord Webhook
# ---------------------------------------------------------------------------
def send_discord(message: str) -> bool:
    """Discord Webhookへ送信。成功したらTrue"""
    try:
        r = requests.post(WEBHOOK_URL, json={"content": message}, timeout=10)
        r.raise_for_status()
        return True
    except Exception as e:
        logger.error(f"WEBHOOK_FAIL: {e}")
        return False

# ---------------------------------------------------------------------------
# 画像前処理
# ---------------------------------------------------------------------------
def preprocess(gray: cv2.Mat) -> cv2.Mat:
    """グレースケール画像の前処理"""
    return cv2.equalizeHist(gray)

# ---------------------------------------------------------------------------
# UI表示
# ---------------------------------------------------------------------------
def put_ui(frame: cv2.Mat, lines: list, ok: bool = True) -> None:
    """画面左上にステータスパネルを描画"""
    x, y = 12, 12
    pad = 8
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    thickness = 2

    # 背景矩形サイズ計算
    max_w = 0
    total_h = 0
    for t in lines:
        (tw, th), _ = cv2.getTextSize(t, font, font_scale, thickness)
        max_w = max(max_w, tw)
        total_h += th + 10
    box_w = max_w + pad * 2
    box_h = total_h + pad * 2

    # 背景（白）
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), (255, 255, 255), -1)
    # 枠（緑/赤）
    color = (0, 180, 0) if ok else (0, 0, 200)
    cv2.rectangle(frame, (x, y), (x + box_w, y + box_h), color, 2)

    # テキスト
    cy = y + pad + 20
    for t in lines:
        cv2.putText(frame, t, (x + pad, cy), font, font_scale, (0, 0, 0), thickness, cv2.LINE_AA)
        cy += 28

# ---------------------------------------------------------------------------
# カメラ管理
# ---------------------------------------------------------------------------
class CameraManager:
    """カメラの取得とリカバリを管理"""

    def __init__(self, device_id: int = 0):
        self.device_id = device_id
        self.cap: Optional[cv2.VideoCapture] = None
        self.fail_count = 0

    def open(self) -> bool:
        """カメラをオープン"""
        self.cap = cv2.VideoCapture(self.device_id)
        if not self.cap.isOpened():
            logger.error(f"カメラ {self.device_id} をオープンできません")
            return False

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
        self.cap.set(cv2.CAP_PROP_FPS, FPS)
        self.fail_count = 0
        logger.info(f"CAMERA_OPEN: デバイス {self.device_id} ({WIDTH}x{HEIGHT}@{FPS}fps)")
        return True

    def read(self) -> Tuple[bool, Optional[cv2.Mat]]:
        """フレームを読み取り"""
        if self.cap is None:
            return False, None
        ret, frame = self.cap.read()
        if ret:
            self.fail_count = 0
            return True, frame
        else:
            self.fail_count += 1
            if self.fail_count >= CAM_FAIL_THRESHOLD:
                logger.warning(f"CAMERA_FAIL: 連続 {self.fail_count} フレーム取得失敗。再オープンを試みます...")
                self.reopen()
            return False, None

    def reopen(self) -> None:
        """カメラを再オープン"""
        self.release()
        logger.info(f"CAMERA_REOPEN: {CAM_REOPEN_WAIT_SEC}秒待機後に再接続...")
        time.sleep(CAM_REOPEN_WAIT_SEC)
        if self.open():
            logger.info("CAMERA_REOPEN: 成功")
        else:
            logger.error("CAMERA_REOPEN: 失敗")

    def release(self) -> None:
        """カメラをリリース"""
        if self.cap is not None:
            self.cap.release()
            self.cap = None

# ---------------------------------------------------------------------------
# エッジトリガ管理
# ---------------------------------------------------------------------------
class EdgeTriggerManager:
    """
    エッジトリガ（再アーム）方式で連続検出を抑制
    
    ロジック:
    - ある種類を検出したら armed=False にする
    - REARM_MISS_SEC 秒間その種類が見えなくなったら armed=True に戻す
    """

    def __init__(self, rearm_sec: float = REARM_MISS_SEC):
        self.rearm_sec = rearm_sec
        # 各種類ごとの状態: {"OPEN": {"armed": True, "last_seen": 0.0}, ...}
        self.states: Dict[str, dict] = {}

    def _get_state(self, kind: str) -> dict:
        if kind not in self.states:
            self.states[kind] = {"armed": True, "last_seen": 0.0}
        return self.states[kind]

    def update(self, kind: str, now: float) -> bool:
        """
        検出時に呼び出す。
        Returns: True なら送信可能（armed状態だった）、False なら無視
        """
        state = self._get_state(kind)
        state["last_seen"] = now

        if state["armed"]:
            state["armed"] = False
            return True
        return False

    def tick(self, now: float) -> None:
        """
        毎フレーム呼び出す。
        一定時間見えなかった種類を再アームする。
        """
        for kind, state in self.states.items():
            if not state["armed"]:
                elapsed = now - state["last_seen"]
                if elapsed >= self.rearm_sec:
                    state["armed"] = True
                    logger.debug(f"REARM: {kind} が再アームされました")

# ---------------------------------------------------------------------------
# QRコード検出
# ---------------------------------------------------------------------------
class QRDetector:
    """pyzbar優先、fallbackでOpenCV"""

    def __init__(self):
        self.cv_detector = cv2.QRCodeDetector()

    def detect(self, gray: cv2.Mat, roi_offset: Tuple[int, int] = (0, 0)) -> Tuple[Optional[str], Optional[Tuple[int, int, int, int]]]:
        """
        QRコードを検出
        Returns: (decoded_text, bbox) or (None, None)
        """
        if HAS_PYZBAR:
            return self._detect_pyzbar(gray, roi_offset)
        else:
            return self._detect_opencv(gray, roi_offset)

    def _detect_pyzbar(self, gray: cv2.Mat, roi_offset: Tuple[int, int]) -> Tuple[Optional[str], Optional[Tuple[int, int, int, int]]]:
        codes = zbar_decode(gray)
        if not codes:
            return None, None
        c = codes[0]
        text = c.data.decode("utf-8", errors="ignore")
        rect = c.rect
        bbox = (
            rect.left + roi_offset[0],
            rect.top + roi_offset[1],
            rect.width,
            rect.height
        )
        return text, bbox

    def _detect_opencv(self, gray: cv2.Mat, roi_offset: Tuple[int, int]) -> Tuple[Optional[str], Optional[Tuple[int, int, int, int]]]:
        try:
            text, points, _ = self.cv_detector.detectAndDecode(gray)
            if not text:
                return None, None
            bbox = None
            if points is not None:
                pts = points[0].astype(int)
                x0, y0 = pts.min(axis=0)
                x1, y1 = pts.max(axis=0)
                bbox = (x0 + roi_offset[0], y0 + roi_offset[1], x1 - x0, y1 - y0)
            return text, bbox
        except cv2.error:
            # OpenCV 4.12.0 のバグ回避
            return None, None

# ---------------------------------------------------------------------------
# メインループ
# ---------------------------------------------------------------------------
def main() -> None:
    logger.info("=" * 50)
    logger.info("QR Scanner Service 起動")
    logger.info(f"pyzbar: {'有効' if HAS_PYZBAR else '無効（OpenCV fallback）'}")
    logger.info(f"WEBHOOK_URL: {WEBHOOK_URL[:30]}...")
    logger.info(f"OPEN_QR: {qr_preview(OPEN_QR)}")
    logger.info(f"CLOSE_QR: {qr_preview(CLOSE_QR)}")
    logger.info(f"TEST_QR: {qr_preview(TEST_QR)}")
    logger.info(f"LOG_RAW_QR: {LOG_RAW_QR}, SHOW_RAW_TEXT: {SHOW_RAW_TEXT}")
    logger.info("設定読み込みOK")
    logger.info("=" * 50)

    camera = CameraManager(device_id=0)
    if not camera.open():
        logger.critical("カメラを開けませんでした。終了します。")
        sys.exit(1)
    logger.info("カメラオープンOK")

    detector = QRDetector()
    trigger = EdgeTriggerManager(rearm_sec=REARM_MISS_SEC)

    frame_i = 0
    last_roi: Optional[Tuple[int, int, int, int]] = None
    last_roi_time = 0.0

    # UI表示用
    ui_until = 0.0
    ui_lines = ["READY"]
    ui_ok = True

    try:
        while True:
            ret, frame = camera.read()
            if not ret or frame is None:
                time.sleep(0.01)
                continue

            frame_i += 1
            now = time.time()

            # エッジトリガの再アームチェック
            trigger.tick(now)

            # 解析間引き
            if frame_i % SCAN_EVERY_N_FRAMES != 0:
                if now < ui_until:
                    put_ui(frame, ui_lines, ok=ui_ok)
                cv2.imshow("QR Scanner (q to quit)", frame)
                if cv2.waitKey(1) & 0xFF == ord("q"):
                    break
                continue

            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = preprocess(gray)

            # ROI適用
            use_roi = last_roi is not None and (now - last_roi_time) <= ROI_TIMEOUT_SEC
            if use_roi:
                rx, ry, rw, rh = last_roi
                scan_img = gray[ry:ry+rh, rx:rx+rw]
                roi_offset = (rx, ry)
            else:
                scan_img = gray
                roi_offset = (0, 0)

            # QR検出
            decoded_text, bbox = detector.detect(scan_img, roi_offset)

            if decoded_text:
                kind = identify_qr(decoded_text)

                # ログ出力
                if LOG_RAW_QR:
                    logger.info(f"QR_DETECTED: {kind} raw={decoded_text}")
                else:
                    logger.info(f"QR_DETECTED: {kind} preview={qr_preview(decoded_text)}")

                # エッジトリガ判定
                should_act = trigger.update(kind, now)

                if should_act:
                    if kind == "OPEN":
                        ui_lines = ["OPEN MATCH", "(sent)"]
                        ui_ok = True
                        if send_discord("あけた"):
                            logger.info("SENT: OPEN -> あけた")
                        else:
                            logger.warning("IGNORED: OPEN (webhook失敗)")

                    elif kind == "CLOSE":
                        ui_lines = ["CLOSE MATCH", "(sent)"]
                        ui_ok = True
                        if send_discord("しめた"):
                            logger.info("SENT: CLOSE -> しめた")
                        else:
                            logger.warning("IGNORED: CLOSE (webhook失敗)")

                    elif kind == "TEST":
                        ui_lines = ["TEST MATCH", "(sent)"]
                        ui_ok = True
                        if send_discord("test"):
                            logger.info("SENT: TEST -> test")
                        else:
                            logger.warning("IGNORED: TEST (webhook失敗)")

                    else:  # UNKNOWN
                        ui_lines = ["UNKNOWN QR", "(ignored)"]
                        ui_ok = False
                        logger.info("UNKNOWN: 不明なQRコード")

                    ui_until = now + UI_HOLD_SEC
                else:
                    logger.debug(f"IGNORED: {kind} (not armed)")

                if SHOW_RAW_TEXT:
                    ui_lines.append(f"txt: {qr_preview(decoded_text)}")

                # ROI更新
                if bbox is not None:
                    bx, by, bw, bh = bbox
                    bx = clamp(bx - ROI_PADDING, 0, WIDTH - 1)
                    by = clamp(by - ROI_PADDING, 0, HEIGHT - 1)
                    bw = clamp(bw + ROI_PADDING * 2, 1, WIDTH - bx)
                    bh = clamp(bh + ROI_PADDING * 2, 1, HEIGHT - by)
                    last_roi = (bx, by, bw, bh)
                    last_roi_time = now
                else:
                    last_roi = None

            # ROI枠表示
            if last_roi is not None:
                rx, ry, rw, rh = last_roi
                cv2.rectangle(frame, (rx, ry), (rx + rw, ry + rh), (0, 255, 0), 2)

            # UI表示
            if now < ui_until:
                put_ui(frame, ui_lines, ok=ui_ok)

            cv2.imshow("QR Scanner (q to quit)", frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break

    except KeyboardInterrupt:
        logger.info("Ctrl+C で終了")
    finally:
        camera.release()
        cv2.destroyAllWindows()
        logger.info("QR Scanner Service 終了")


if __name__ == "__main__":
    main()
