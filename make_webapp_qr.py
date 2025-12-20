import os
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont


PROJECT_DIR = Path(__file__).resolve().parent
OUT_DIR = PROJECT_DIR / "qr_out"

# 環境変数から取得、または手動で設定してください
WEBAPP_URL = os.environ.get("WEBAPP_URL", "https://your-app.onrender.com/")
LABEL = "QR Scanner"

BOX_SIZES = [12, 10, 8, 6]
LABEL_HEIGHT_PX = 80


def get_font(size: int) -> ImageFont.ImageFont:
    for font_name in ["arial.ttf", "meiryo.ttc", "YuGothM.ttc"]:
        try:
            return ImageFont.truetype(font_name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def make_labeled_qr(url: str, label: str, out_path: Path, box_size: int) -> None:
    """ラベル付きQRコードを生成"""
    qr = qrcode.QRCode(
        version=None,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=box_size,
        border=4,
    )
    qr.add_data(url)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    
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
    print(f"  生成: {out_path}")


def main() -> None:
    print("WebアプリQRコードを生成中...")
    print(f"URL: {WEBAPP_URL}")
    
    for bs in BOX_SIZES:
        filename = f"WEBAPP_QR_box{bs}.png"
        make_labeled_qr(WEBAPP_URL, LABEL, OUT_DIR / filename, box_size=bs)
    
    print(f"\n完了! 出力先: {OUT_DIR}")


if __name__ == "__main__":
    main()
