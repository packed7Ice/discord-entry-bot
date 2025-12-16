from __future__ import annotations

import secrets
from pathlib import Path
from typing import Dict, Iterable

import qrcode
from PIL import Image, ImageDraw, ImageFont


PROJECT_DIR = Path(__file__).resolve().parent
ENV_PATH = PROJECT_DIR / ".env"
OUT_DIR = PROJECT_DIR / "qr_out"

OPEN_LABEL = "OPEN"
CLOSE_LABEL = "CLOSE"

# ここで “複数サイズ” を指定（大 → 小 の順がおすすめ）
# box_size = 1セル(モジュール)のピクセル数。小さいほど物理サイズも小さくなります。
BOX_SIZES: list[int] = [12, 10, 8, 6, 5, 4, 3, 2]

# 上部ラベルの高さ（px）…QRが小さいほどラベルが相対的に大きく見えるので、
# 必要なら後で調整してください。
LABEL_HEIGHT_PX = 80

# QR周囲の余白（quiet zone）…QR規格的に重要。小型化したいほど削りたくなるが推奨は維持。
BORDER_MODULES = 4


# ---------- .env 読み書き ----------
def parse_env(text: str) -> Dict[str, str]:
    env: Dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()
    return env


def dump_env(env: Dict[str, str]) -> str:
    order = ["DISCORD_WEBHOOK_URL", "OPEN_QR", "CLOSE_QR"]
    keys = [k for k in order if k in env] + sorted(k for k in env if k not in order)
    return "\n".join(f"{k}={env[k]}" for k in keys) + "\n"


# ---------- QR + ラベル描画 ----------
def build_qr_image(payload: str, box_size: int) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,  # 自動
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=BORDER_MODULES,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def get_font(size: int) -> ImageFont.ImageFont:
    # Windowsなら arial.ttf が通ることが多い
    for font_name in ["arial.ttf", "meiryo.ttc", "YuGothM.ttc"]:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_labeled_qr(payload: str, label: str, out_path: Path, box_size: int) -> None:
    qr_img = build_qr_image(payload, box_size=box_size)
    qr_w, qr_h = qr_img.size

    # ラベル領域の高さは固定（必要なら可変にしてもOK）
    label_h = LABEL_HEIGHT_PX

    canvas = Image.new("RGB", (qr_w, qr_h + label_h), "white")
    canvas.paste(qr_img, (0, label_h))

    draw = ImageDraw.Draw(canvas)

    # QRが小さくなるほどラベル文字も少し縮める（好みで調整）
    # 最低16pxくらいにはしておく
    font_size = max(16, int(min(40, box_size * 3.2)))
    font = get_font(font_size)

    # 中央寄せ
    bbox = draw.textbbox((0, 0), label, font=font)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    text_x = (qr_w - text_w) // 2
    text_y = (label_h - text_h) // 2

    draw.text((text_x, text_y), label, fill="black", font=font)

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)


def generate_variants(payload: str, label: str, prefix: str, box_sizes: Iterable[int]) -> None:
    for bs in box_sizes:
        filename = f"{prefix}_box{bs}.png"
        make_labeled_qr(payload, label, OUT_DIR / filename, box_size=bs)


def main() -> None:
    env_text = ENV_PATH.read_text(encoding="utf-8") if ENV_PATH.exists() else ""
    env = parse_env(env_text)

    # トークンが無ければ生成（既存があれば維持）
    env.setdefault("OPEN_QR", secrets.token_hex(16))
    env.setdefault("CLOSE_QR", secrets.token_hex(16))

    # .env 更新
    ENV_PATH.write_text(dump_env(env), encoding="utf-8")

    # 複数サイズのQR画像を生成
    generate_variants(env["OPEN_QR"], OPEN_LABEL, "OPEN_QR", BOX_SIZES)
    generate_variants(env["CLOSE_QR"], CLOSE_LABEL, "CLOSE_QR", BOX_SIZES)

    print("✅ .env 更新完了:", ENV_PATH)
    print("✅ 複数サイズのラベル付きQR画像を生成:", OUT_DIR)
    print("  出力box_size:", BOX_SIZES)
    print("OPEN_QR  =", env["OPEN_QR"])
    print("CLOSE_QR =", env["CLOSE_QR"])


if __name__ == "__main__":
    main()
