import os
import time
import requests
import cv2
from dotenv import load_dotenv

try:
    from pyzbar.pyzbar import decode as zbar_decode
    HAS_PYZBAR = True
except Exception:
    HAS_PYZBAR = False

load_dotenv()
WEBHOOK_URL = os.environ["DISCORD_WEBHOOK_URL"]
OPEN_QR     = os.environ["OPEN_QR"]
CLOSE_QR    = os.environ["CLOSE_QR"]
TEST_QR     = os.environ["TEST_QR"]  # ★追加

WIDTH, HEIGHT = 640, 480
SCAN_EVERY_N_FRAMES = 2
COOLDOWN_SEC = 1.5

ROI_PADDING = 40
ROI_TIMEOUT_SEC = 2.0

# ★表示関連
UI_HOLD_SEC = 1.2  # 表示を何秒保持するか
SHOW_RAW_TEXT = False  # QRの生文字列を画面に出したいなら True

def send_discord(text: str) -> None:
    r = requests.post(WEBHOOK_URL, json={"content": text}, timeout=5)
    r.raise_for_status()

def preprocess(gray):
    return cv2.equalizeHist(gray)

def clamp(v, lo, hi):
    return max(lo, min(hi, v))

def put_ui(frame, lines, ok=True):
    # 左上にパネル表示（軽量）
    x, y = 12, 12
    pad = 8
    font = cv2.FONT_HERSHEY_SIMPLEX
    font_scale = 0.7
    thickness = 2

    # 背景矩形サイズをざっくり計算
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

def main():
    cap = cv2.VideoCapture(0)
    cap.set(cv2.CAP_PROP_FRAME_WIDTH, WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, 30)

    cv_detector = cv2.QRCodeDetector()

    last_sent = {"OPEN": 0.0, "CLOSE": 0.0}
    frame_i = 0

    last_roi = None
    last_roi_time = 0.0

    # ★UI表示保持用
    ui_until = 0.0
    ui_lines = ["READY"]
    ui_ok = True
    last_text_preview = ""

    while True:
        ret, frame = cap.read()
        if not ret:
            print("カメラ取得失敗。VideoCapture(1) なども試してください。")
            break

        frame_i += 1
        show_frame = frame

        # 解析間引き
        if frame_i % SCAN_EVERY_N_FRAMES != 0:
            # UI表示維持
            if time.time() < ui_until:
                put_ui(show_frame, ui_lines, ok=ui_ok)
            cv2.imshow("QR Scanner (q to quit)", show_frame)
            if cv2.waitKey(1) & 0xFF == ord("q"):
                break
            continue

        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        gray = preprocess(gray)

        now = time.time()

        use_roi = last_roi is not None and (now - last_roi_time) <= ROI_TIMEOUT_SEC
        if use_roi:
            x, y, w, h = last_roi
            scan_img = gray[y:y+h, x:x+w]
            roi_offset = (x, y)
        else:
            scan_img = gray
            roi_offset = (0, 0)

        decoded_text = None
        bbox = None

        if HAS_PYZBAR:
            codes = zbar_decode(scan_img)
            if codes:
                c = codes[0]
                decoded_text = c.data.decode("utf-8", errors="ignore")
                rect = c.rect
                bbox = (rect.left + roi_offset[0], rect.top + roi_offset[1], rect.width, rect.height)
        else:
            text, points, _ = cv_detector.detectAndDecode(scan_img)
            if text:
                decoded_text = text
                if points is not None:
                    pts = points[0].astype(int)
                    x0, y0 = pts.min(axis=0)
                    x1, y1 = pts.max(axis=0)
                    bbox = (x0 + roi_offset[0], y0 + roi_offset[1], (x1 - x0), (y1 - y0))

        if decoded_text:
            # 表示用（漏れが気になるなら非表示に）
            last_text_preview = decoded_text[:10] + ("..." if len(decoded_text) > 10 else "")

            # 判定
            if decoded_text == OPEN_QR:
                ui_lines = ["OPEN MATCH", "(will send)"]
                ui_ok = True
                ui_until = now + UI_HOLD_SEC

                if now - last_sent["OPEN"] >= COOLDOWN_SEC:
                    send_discord("あけた")
                    last_sent["OPEN"] = now

            elif decoded_text == CLOSE_QR:
                ui_lines = ["CLOSE MATCH", "(will send)"]
                ui_ok = True
                ui_until = now + UI_HOLD_SEC

                if now - last_sent["CLOSE"] >= COOLDOWN_SEC:
                    send_discord("しめた")
                    last_sent["CLOSE"] = now

            elif decoded_text == TEST_QR:
                # ★テスト表示（Discord送信しない／するならここで送る）
                ui_lines = ["TEST MATCH", "(will send)"]
                ui_ok = True
                ui_until = now + UI_HOLD_SEC
                send_discord("test")

            else:
                ui_lines = ["UNKNOWN QR", "(ignored)"]
                ui_ok = False
                ui_until = now + UI_HOLD_SEC

            if SHOW_RAW_TEXT:
                ui_lines.append(f"txt: {last_text_preview}")

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

        # ROI枠表示（任意）
        if last_roi is not None:
            x, y, w, h = last_roi
            cv2.rectangle(show_frame, (x, y), (x+w, y+h), (0, 255, 0), 2)

        # UI表示
        if time.time() < ui_until:
            put_ui(show_frame, ui_lines, ok=ui_ok)

        cv2.imshow("QR Scanner (q to quit)", show_frame)
        if cv2.waitKey(1) & 0xFF == ord("q"):
            break

    cap.release()
    cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
