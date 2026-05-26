"""スライドショー生成器の単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.video_editor.ffmpeg_wrapper import check_ffmpeg_available
from src.video_generator.slideshow_builder import (
    PALETTES,
    SlideshowBuilder,
    SlideshowError,
    _wrap_text,
    generate_placeholder_image,
)

REQUIRES_FFMPEG = pytest.mark.skipif(
    not check_ffmpeg_available(),
    reason="ffmpeg が PATH にない",
)


@pytest.mark.unit
class TestWrapText:
    def test_short_text_one_line(self):
        assert _wrap_text("短い", 10) == ["短い"]

    def test_long_text_wraps(self):
        text = "あいうえおかきくけこさしすせそ"
        result = _wrap_text(text, 5)
        assert len(result) >= 2
        for line in result[:-1]:
            assert len(line) <= 5

    def test_exact_boundary(self):
        text = "12345"
        result = _wrap_text(text, 5)
        assert len(result) == 1


@pytest.mark.unit
class TestPlaceholderImage:
    def test_generate_creates_png(self, tmp_path: Path):
        out = tmp_path / "p.png"
        result = generate_placeholder_image(out, "タイトル", "サブ")
        assert result.exists()
        assert result.stat().st_size > 0

    def test_palette_index_within_range(self, tmp_path: Path):
        """palette_index が範囲外でも問題なく(modulo で)生成される"""
        out = tmp_path / "p.png"
        generate_placeholder_image(out, "test", palette_index=999)
        assert out.exists()

    def test_each_palette_works(self, tmp_path: Path):
        for i in range(len(PALETTES)):
            out = tmp_path / f"p_{i}.png"
            generate_placeholder_image(out, f"パレット{i}", palette_index=i)
            assert out.exists()

    def test_long_title_wraps(self, tmp_path: Path):
        out = tmp_path / "p.png"
        long_title = "あ" * 50
        generate_placeholder_image(out, long_title)
        assert out.exists()


@pytest.mark.unit
class TestSlideshowBuilderUnit:
    def test_build_empty_raises(self, tmp_path: Path):
        builder = SlideshowBuilder()
        with pytest.raises(SlideshowError):
            builder.build([], tmp_path / "out.mp4")


@pytest.mark.unit
@REQUIRES_FFMPEG
class TestSlideshowBuilderIntegration:
    def test_build_single_slide(self, tmp_path: Path):
        img = tmp_path / "img.png"
        generate_placeholder_image(img, "テスト")
        builder = SlideshowBuilder(slide_duration=1.0)
        out = tmp_path / "out.mp4"
        result = builder.build([img], out, ken_burns=False)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_build_multiple_slides_with_xfade(self, tmp_path: Path):
        imgs = []
        for i in range(3):
            p = tmp_path / f"img_{i}.png"
            generate_placeholder_image(p, f"slide {i}", palette_index=i)
            imgs.append(p)
        builder = SlideshowBuilder(slide_duration=1.0, transition_duration=0.3)
        out = tmp_path / "out.mp4"
        result = builder.build(imgs, out)
        assert result.exists()
        # ffprobe で確認できる長さがあること
        from src.video_editor.ffmpeg_wrapper import FFmpegWrapper

        duration = FFmpegWrapper().get_duration(result)
        # 3 slides * 1.0s - 2 transitions * 0.3s = 2.4s 前後
        assert duration > 1.5

    def test_built_video_has_audio_track(self, tmp_path: Path):
        """無音オーディオトラックが付いていること(TikTok互換性のため)"""
        import subprocess

        img = tmp_path / "img.png"
        generate_placeholder_image(img, "テスト")
        builder = SlideshowBuilder(slide_duration=1.0)
        out = tmp_path / "out.mp4"
        builder.build([img], out, ken_burns=False)

        result = subprocess.run(
            [
                "ffprobe",
                "-v", "error",
                "-select_streams", "a",
                "-show_entries", "stream=codec_type",
                "-of", "csv=p=0",
                str(out),
            ],
            capture_output=True,
            text=True,
        )
        assert "audio" in result.stdout
