"""商品画像コンポジターのテスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.video_generator.product_slide import (
    ProductImageError,
    _resize_contain,
    _resize_cover,
    _wrap,
    compose_product_slide,
    download_image,
)


def _make_fake_product_photo(path: Path, w: int = 800, h: int = 600) -> Path:
    """白背景に色付き矩形の擬似商品写真"""
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (w, h), (245, 245, 245))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([w // 4, h // 4, w * 3 // 4, h * 3 // 4], radius=30,
                           fill=(80, 120, 200))
    path.parent.mkdir(parents=True, exist_ok=True)
    img.save(path)
    return path


@pytest.mark.unit
class TestResizeHelpers:
    def test_cover_fills_exact(self):
        from PIL import Image

        src = Image.new("RGB", (400, 800))
        out = _resize_cover(src, 1080, 1920)
        assert out.size == (1080, 1920)

    def test_contain_fits_within(self):
        from PIL import Image

        src = Image.new("RGB", (2000, 1000))
        out = _resize_contain(src, 800, 800)
        assert out.width <= 800
        assert out.height <= 800

    def test_wrap_short(self):
        assert _wrap("短い", 10) == ["短い"]

    def test_wrap_long(self):
        result = _wrap("あ" * 30, 10)
        assert len(result) == 3


@pytest.mark.unit
class TestComposeProductSlide:
    def test_compose_produces_vertical_png(self, tmp_path: Path):
        photo = _make_fake_product_photo(tmp_path / "p.jpg")
        out = tmp_path / "slide.png"
        compose_product_slide(photo, out, "コレ知らない?", "¥4,980 / ★4.4")
        assert out.exists()
        from PIL import Image

        with Image.open(out) as im:
            assert im.size == (1080, 1920)

    def test_compose_without_headline(self, tmp_path: Path):
        photo = _make_fake_product_photo(tmp_path / "p.jpg")
        out = tmp_path / "slide.png"
        compose_product_slide(photo, out, "見出し", headline_baked=False)
        assert out.exists()

    def test_compose_missing_image_raises(self, tmp_path: Path):
        with pytest.raises(ProductImageError):
            compose_product_slide(
                tmp_path / "nope.jpg", tmp_path / "o.png", "x"
            )

    def test_accent_rotation(self, tmp_path: Path):
        photo = _make_fake_product_photo(tmp_path / "p.jpg")
        for i in range(6):
            out = tmp_path / f"s{i}.png"
            compose_product_slide(photo, out, "テスト", accent_index=i)
            assert out.exists()


@pytest.mark.unit
class TestDownloadImage:
    def test_download_invalid_url_raises(self, tmp_path: Path):
        with pytest.raises(ProductImageError):
            download_image(
                "http://127.0.0.1:0/nonexistent.jpg", tmp_path / "x.jpg", timeout=2
            )
