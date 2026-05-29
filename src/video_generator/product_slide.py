"""商品画像ベースのスライド合成

本物の TikTok 商品紹介動画のレイアウトを再現する:
- 商品写真を「ぼかし + 暗転」で 9:16 全面に敷く(余白を埋める)
- 商品写真を「くっきり contain」で中央上部に配置
- 下部にテキストバナー(見出し)を焼く

AI 画像生成(billing 必須)に頼らず、アフィリエイト商品の実画像を活用する。
これが無料・合法(アフィリエイト目的の商品画像利用)・商品が映る、を同時に満たす。
"""

from __future__ import annotations

from pathlib import Path

import httpx

from src.utils.logger import get_logger
from src.utils.text import strip_emoji
from src.video_editor.subtitle_burner import find_default_font

logger = get_logger(__name__)

DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1920
REQUEST_TIMEOUT = 12.0

# ブランドアクセント(見出しバナーの色)
ACCENT_COLORS = [
    (236, 72, 153),   # ピンク
    (251, 191, 36),   # イエロー
    (34, 211, 238),   # シアン
    (16, 185, 129),   # グリーン
    (139, 92, 246),   # パープル
]


class ProductImageError(Exception):
    """商品画像取得・合成エラー"""


def download_image(url: str, output: Path, *, timeout: float = REQUEST_TIMEOUT) -> Path:
    """商品画像を URL からダウンロード

    本番(Amazon/楽天 API が返す image_urls)で使用。
    """
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        if url.startswith("file://"):
            # ローカルファイル(テスト・オフライン用)
            import shutil

            shutil.copyfile(url[len("file://"):], output)
        else:
            with httpx.Client(timeout=timeout, follow_redirects=True) as client:
                resp = client.get(url, headers={"User-Agent": "Mozilla/5.0"})
                resp.raise_for_status()
                output.write_bytes(resp.content)
    except Exception as e:
        raise ProductImageError(f"画像DL失敗 {url[:60]}: {e}") from e

    # 妥当な画像か検証
    try:
        from PIL import Image

        with Image.open(output) as im:
            im.verify()
    except Exception as e:
        output.unlink(missing_ok=True)
        raise ProductImageError(f"画像が壊れています {url[:60]}: {e}") from e
    return output


def compose_product_slide(
    product_image: Path,
    output: Path,
    headline: str,
    subtext: str = "",
    *,
    width: int = DEFAULT_WIDTH,
    height: int = DEFAULT_HEIGHT,
    accent_index: int = 0,
    headline_baked: bool = True,
) -> Path:
    """商品画像から TikTok 風スライドを合成

    Args:
        product_image: 商品写真パス
        output: 出力 PNG
        headline: 見出し(下部バナーに焼く。動画字幕と別途重ねる場合は headline_baked=False)
        subtext: 補足(価格・評価など)
        accent_index: アクセント色のローテーション
        headline_baked: True で見出しを画像に焼く
    """
    from PIL import Image, ImageDraw, ImageFilter

    output.parent.mkdir(parents=True, exist_ok=True)
    accent = ACCENT_COLORS[accent_index % len(ACCENT_COLORS)]

    try:
        src = Image.open(product_image).convert("RGB")
    except Exception as e:
        raise ProductImageError(f"商品画像を開けません {product_image}: {e}") from e

    # 1. 背景: cover でフィル → 強ぼかし + 暗転
    bg = _resize_cover(src, width, height)
    bg = bg.filter(ImageFilter.GaussianBlur(40))
    dark = Image.new("RGB", (width, height), (0, 0, 0))
    bg = Image.blend(bg, dark, 0.45)

    # 2. 前景: contain で中央上部に配置(角丸 + 影風の枠)
    fg_max_w = int(width * 0.82)
    fg_max_h = int(height * 0.52)
    fg = _resize_contain(src, fg_max_w, fg_max_h)
    fg_x = (width - fg.width) // 2
    fg_y = int(height * 0.10)

    # 白フチ(商品を浮かせる)
    border = 10
    framed = Image.new("RGB", (fg.width + border * 2, fg.height + border * 2), (255, 255, 255))
    framed.paste(fg, (border, border))
    bg.paste(framed, (fg_x - border, fg_y - border))

    draw = ImageDraw.Draw(bg)

    if headline_baked and headline:
        _draw_headline_banner(
            draw, bg, headline, subtext, width, height, accent
        )

    bg.save(output, "PNG")
    return output


def _draw_headline_banner(draw, img, headline, subtext, width, height, accent):
    """下部 1/3 に見出しバナーを描く"""
    from PIL import ImageFont

    headline = strip_emoji(headline)
    subtext = strip_emoji(subtext)
    font_path = find_default_font()
    h_size = int(width * 0.082)
    s_size = int(width * 0.040)
    try:
        h_font = ImageFont.truetype(str(font_path), h_size) if font_path else ImageFont.load_default()
        s_font = ImageFont.truetype(str(font_path), s_size) if font_path else ImageFont.load_default()
    except Exception:
        h_font = ImageFont.load_default()
        s_font = ImageFont.load_default()

    lines = _wrap(headline, 11)
    line_h = int(h_size * 1.2)
    block_h = line_h * len(lines)
    y0 = int(height * 0.70)

    # 黒帯(見出しの可読性確保)
    draw.rectangle(
        [0, y0 - 24, width, y0 + block_h + (s_size + 30 if subtext else 24)],
        fill=(0, 0, 0),
    )

    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=h_font)
        tw = bbox[2] - bbox[0]
        x = (width - tw) // 2
        y = y0 + i * line_h
        # 縁取り
        for ox, oy in [(-3, 0), (3, 0), (0, -3), (0, 3)]:
            draw.text((x + ox, y + oy), line, font=h_font, fill=(0, 0, 0))
        draw.text((x, y), line, font=h_font, fill=(255, 255, 255))

    # アクセント下線
    underline_y = y0 + block_h + 6
    draw.rectangle(
        [width // 2 - 80, underline_y, width // 2 + 80, underline_y + 8],
        fill=accent,
    )

    if subtext:
        sub_lines = _wrap(subtext, 18)
        for i, line in enumerate(sub_lines):
            bbox = draw.textbbox((0, 0), line, font=s_font)
            tw = bbox[2] - bbox[0]
            x = (width - tw) // 2
            y = underline_y + 22 + i * int(s_size * 1.3)
            draw.text((x, y), line, font=s_font, fill=accent)


def _resize_cover(img, w: int, h: int):
    """cover: アスペクト維持で w×h を満たすよう拡大してクロップ"""
    src_ratio = img.width / img.height
    dst_ratio = w / h
    if src_ratio > dst_ratio:
        new_h = h
        new_w = int(h * src_ratio)
    else:
        new_w = w
        new_h = int(w / src_ratio)
    from PIL import Image

    resized = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - w) // 2
    top = (new_h - h) // 2
    return resized.crop((left, top, left + w, top + h))


def _resize_contain(img, max_w: int, max_h: int):
    """contain: アスペクト維持で max_w×max_h に収まるよう縮小"""
    from PIL import Image

    ratio = min(max_w / img.width, max_h / img.height)
    new_w = max(1, int(img.width * ratio))
    new_h = max(1, int(img.height * ratio))
    return img.resize((new_w, new_h), Image.LANCZOS)


def _wrap(text: str, max_chars: int) -> list[str]:
    if len(text) <= max_chars:
        return [text]
    lines, cur = [], ""
    for ch in text:
        cur += ch
        if len(cur) >= max_chars:
            lines.append(cur)
            cur = ""
    if cur:
        lines.append(cur)
    return lines
