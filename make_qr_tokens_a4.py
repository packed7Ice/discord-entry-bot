from __future__ import annotations

from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

# 入力：QR画像が置かれているフォルダ
PROJECT_DIR = Path(__file__).resolve().parent
IN_DIR = PROJECT_DIR / "qr_out"

# 出力
OUT_PATH = IN_DIR / "qr_sheet_A4_300dpi.png"

# A4 300dpi 相当（縦）
A4_W, A4_H = 2480, 3508  # px

# レイアウト（必要ならここだけ調整）
MARGIN = 120            # 余白
GAP_X = 60              # 列間
GAP_Y = 80              # 行間
COLS = 2                # 2列（左：OPEN群、右：CLOSE群）
TITLE_H = 140           # 上部タイトル領域
LABEL_H = 50            # 各QRの下にファイル名を書く領域

# 表示したい box_size の並び（生成側と揃える）
BOX_SIZES = [12, 10, 8, 6, 5, 4, 3, 2]


def load_font(size: int):
    for name in ["arial.ttf", "meiryo.ttc", "YuGothM.ttc"]:
        try:
            return ImageFont.truetype(name, size)
        except Exception:
            pass
    return ImageFont.load_default()


def open_image(path: Path) -> Image.Image:
    img = Image.open(path)
    if img.mode != "RGB":
        img = img.convert("RGB")
    return img


def main() -> None:
    # 期待するファイルを集める
    open_paths = [IN_DIR / f"OPEN_QR_box{bs}.png" for bs in BOX_SIZES]
    close_paths = [IN_DIR / f"CLOSE_QR_box{bs}.png" for bs in BOX_SIZES]

    missing = [p for p in (open_paths + close_paths) if not p.exists()]
    if missing:
        print("❌ 先に make_qr_tokens.py を実行して、以下のファイルを生成してください:")
        for p in missing[:10]:
            print("  -", p.name)
        if len(missing) > 10:
            print(f"  ... and {len(missing)-10} more")
        return

    # A4キャンバス
    sheet = Image.new("RGB", (A4_W, A4_H), "white")
    draw = ImageDraw.Draw(sheet)

    title_font = load_font(56)
    sub_font = load_font(32)
    name_font = load_font(24)

    # タイトル
    title = "QR Size Sheet (A4, 300dpi)"
    draw.text((MARGIN, 40), title, fill="black", font=title_font)

    # 列タイトル
    col_w = (A4_W - 2 * MARGIN - GAP_X) // 2
    x_open = MARGIN
    x_close = MARGIN + col_w + GAP_X
    y0 = MARGIN + TITLE_H

    draw.text((x_open, y0 - 70), "OPEN", fill="black", font=sub_font)
    draw.text((x_close, y0 - 70), "CLOSE", fill="black", font=sub_font)

    # 各セルの最大配置サイズ（列幅に合わせる）
    # 縦方向は「QR画像 + ファイル名」ぶん確保して均等割り
    rows = len(BOX_SIZES)
    usable_h = A4_H - y0 - MARGIN
    cell_h = (usable_h - GAP_Y * (rows - 1)) // rows
    max_img_h = max(60, cell_h - LABEL_H)  # 画像領域
    max_img_w = col_w

    def paste_column(paths: list[Path], x_left: int):
        y = y0
        for p in paths:
            img = open_image(p)

            # 縦横比を保って縮小（必要なら）
            img_w, img_h = img.size
            scale = min(max_img_w / img_w, max_img_h / img_h, 1.0)
            new_w = int(img_w * scale)
            new_h = int(img_h * scale)
            if scale != 1.0:
                img = img.resize((new_w, new_h), Image.Resampling.LANCZOS)

            # 中央寄せ
            px = x_left + (col_w - img.size[0]) // 2
            py = y + (max_img_h - img.size[1]) // 2
            sheet.paste(img, (px, py))

            # ファイル名（boxサイズ）が分かるように
            name = p.stem  # 例: OPEN_QR_box12
            nb = draw.textbbox((0, 0), name, font=name_font)
            tw = nb[2] - nb[0]
            tx = x_left + (col_w - tw) // 2
            ty = y + max_img_h + 10
            draw.text((tx, ty), name, fill="black", font=name_font)

            y += cell_h + GAP_Y

    paste_column(open_paths, x_open)
    paste_column(close_paths, x_close)

    # 保存（PNGにdpiメタを付与）
    IN_DIR.mkdir(parents=True, exist_ok=True)
    sheet.save(OUT_PATH, dpi=(300, 300))
    print("✅ A4シート画像を生成しました:", OUT_PATH)


if __name__ == "__main__":
    main()
