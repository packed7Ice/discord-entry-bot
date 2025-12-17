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
TEST_LABEL = "TEST"

BOX_SIZES: list[int] = [12, 10, 8, 6, 5, 4, 3, 2]
LABEL_HEIGHT_PX = 80
BORDER_MODULES = 4


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
    order = ["DISCORD_WEBHOOK_URL", "OPEN_QR", "CLOSE_QR", "TEST_QR"]
    keys = [k for k in order if k in env] + sorted(k for k in env if k not in order)
    return "\n".join(f"{k}={env[k]}" for k in keys) + "\n"


def build_qr_image(payload: str, box_size: int) -> Image.Image:
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=BORDER_MODULES,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    return qr.make_image(fill_color="black", back_color="white").convert("RGB")


def get_font(size: int) -> ImageFont.ImageFont:
    for font_name in ["arial.ttf", "meiryo.ttc", "YuGothM.ttc"]:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_labeled_qr(payload: str, label: str, out_path: Path, box_size: int) -> None:
    qr_img = build_qr_image(payload, box_size=box_size)
    qr_w, qr_h = qr_img.size

    label_h = LABEL_HEIGHT_PX
    canvas = Image.new("RGB", (qr_w, qr_h + label_h), "white")
    canvas.paste(qr_img, (0, label_h))

    draw = ImageDraw.Draw(canvas)

    font_size = max(16, int(min(40, box_size * 3.2)))
    font = get_font(font_size)

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

    # 既存があれば維持、なければ生成（暗号的に十分長い）
    env.setdefault("OPEN_QR", secrets.token_hex(16))
    env.setdefault("CLOSE_QR", secrets.token_hex(16))
    env.setdefault("TEST_QR", secrets.token_hex(16))  # ★追加

    ENV_PATH.write_text(dump_env(env), encoding="utf-8")

    generate_variants(env["OPEN_QR"], OPEN_LABEL, "OPEN_QR", BOX_SIZES)
    generate_variants(env["CLOSE_QR"], CLOSE_LABEL, "CLOSE_QR", BOX_SIZES)
    generate_variants(env["TEST_QR"], TEST_LABEL, "TEST_QR", BOX_SIZES)  # ★追加

    print("✅ .env 更新完了:", ENV_PATH)
    print("✅ 複数サイズのラベル付きQR画像を生成:", OUT_DIR)
    print("  出力box_size:", BOX_SIZES)
    print("OPEN_QR  =", env["OPEN_QR"])
    print("CLOSE_QR =", env["CLOSE_QR"])
    print("TEST_QR  =", env["TEST_QR"])  # ★追加


if __name__ == "__main__":
    main()
