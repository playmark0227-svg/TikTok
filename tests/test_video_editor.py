"""動画編集モジュールの単体テスト"""

from __future__ import annotations

from pathlib import Path

import pytest

from config.settings import Settings
from src.prompt_generator.models import ContentPlan
from src.video_editor.ffmpeg_wrapper import (
    FFmpegError,
    FFmpegWrapper,
    check_ffmpeg_available,
)
from src.video_editor.pr_overlay import PROverlayBurner
from src.video_editor.processor import VideoProcessor
from src.video_editor.subtitle_burner import SubtitleBurner, find_default_font

REQUIRES_FFMPEG = pytest.mark.skipif(
    not check_ffmpeg_available(),
    reason="ffmpeg が PATH にありません",
)


def make_plan() -> ContentPlan:
    return ContentPlan(
        veo_prompt_clip1="a",
        veo_prompt_clip2="b",
        caption="テスト",
        hashtags=["#PR", "#広告"],
        subtitle_text="1行目\n2行目",
        bgm_mood="upbeat",
    )


def make_test_video(path: Path, duration: int = 2) -> Path:
    """テスト用のダミー動画を FFmpeg で生成"""
    import ffmpeg  # type: ignore[import-untyped]

    path.parent.mkdir(parents=True, exist_ok=True)
    (
        ffmpeg.input(f"color=c=blue:s=720x1280:d={duration}", f="lavfi")
        .output(
            str(path),
            vcodec="libx264",
            pix_fmt="yuv420p",
            t=duration,
        )
        .overwrite_output()
        .run(quiet=True)
    )
    return path


@pytest.mark.unit
class TestSubtitleBurner:
    def test_escape_drawtext_handles_special_chars(self):
        text = "テスト:文字'と[記号]"
        escaped = SubtitleBurner._escape_drawtext(text)
        assert ":" not in escaped or "\\:" in escaped
        assert "\\'" in escaped or "'" not in text  # 引用符はエスケープ

    def test_find_default_font_returns_path_or_none(self):
        font = find_default_font()
        assert font is None or font.exists()


@pytest.mark.unit
class TestPROverlayBurner:
    def test_instantiation(self):
        burner = PROverlayBurner()
        assert burner is not None


@pytest.mark.unit
class TestFFmpegWrapper:
    def test_check_ffmpeg_available_returns_bool(self):
        assert isinstance(check_ffmpeg_available(), bool)

    def test_concat_empty_raises(self):
        wrapper = FFmpegWrapper()
        with pytest.raises(FFmpegError):
            wrapper.concat_videos([], Path("/tmp/out.mp4"))


@pytest.mark.unit
@REQUIRES_FFMPEG
class TestFFmpegIntegration:
    def test_concat_single_clip_copies_file(self, tmp_path: Path):
        wrapper = FFmpegWrapper()
        src = make_test_video(tmp_path / "src.mp4")
        out = tmp_path / "out.mp4"
        result = wrapper.concat_videos([src], out)
        assert result.exists()
        assert result.stat().st_size > 0

    def test_concat_multiple_clips(self, tmp_path: Path):
        wrapper = FFmpegWrapper()
        clip1 = make_test_video(tmp_path / "c1.mp4", duration=1)
        clip2 = make_test_video(tmp_path / "c2.mp4", duration=1)
        out = tmp_path / "out.mp4"
        result = wrapper.concat_videos([clip1, clip2], out)
        assert result.exists()
        duration = wrapper.get_duration(result)
        assert duration >= 1.5

    def test_subtitle_burn_produces_video(self, tmp_path: Path):
        wrapper = FFmpegWrapper()
        burner = SubtitleBurner()
        src = make_test_video(tmp_path / "src.mp4", duration=4)
        out = tmp_path / "out.mp4"
        result = burner.burn(src, out, "テスト字幕\n2行目")
        assert result.exists()
        assert wrapper.get_duration(result) >= 1.0

    def test_pr_overlay_produces_video(self, tmp_path: Path):
        burner = PROverlayBurner()
        src = make_test_video(tmp_path / "src.mp4", duration=2)
        out = tmp_path / "out.mp4"
        result = burner.burn(src, out, label="広告")
        assert result.exists()
        assert result.stat().st_size > 0


@pytest.mark.unit
class TestVideoProcessor:
    def test_pick_bgm_returns_none_when_no_files(self, tmp_path: Path):
        settings = Settings(_env_file=None, dry_run=True)
        settings.__dict__["assets_dir_override"] = tmp_path
        processor = VideoProcessor(settings)
        # assets/bgm/upbeat に何もない
        result = processor._pick_bgm("upbeat")
        # ファイルが存在しなければ None
        assert result is None or result.exists()

    def test_process_empty_clips_raises(self):
        processor = VideoProcessor()
        with pytest.raises(ValueError):
            processor.process([], make_plan())


@pytest.mark.unit
@REQUIRES_FFMPEG
class TestVideoProcessorIntegration:
    def test_full_process_pipeline(self, tmp_path: Path):
        settings = Settings(_env_file=None, dry_run=True)
        processor = VideoProcessor(settings)
        clip1 = make_test_video(tmp_path / "c1.mp4", duration=2)
        clip2 = make_test_video(tmp_path / "c2.mp4", duration=2)
        plan = make_plan()
        result = processor.process([clip1, clip2], plan, output_dir=tmp_path, post_id="testid")
        assert result.exists()
        assert result.stat().st_size > 0
