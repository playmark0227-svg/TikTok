"""BGM シンセサイザーのテスト"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.video_editor.ffmpeg_wrapper import check_ffmpeg_available
from src.video_generator.bgm_synth import (
    _MOOD_PRESETS,
    _has_audio_stream,
    mix_bgm_into_video,
    synthesize_bgm,
)

REQUIRES_FFMPEG = pytest.mark.skipif(
    not check_ffmpeg_available(), reason="ffmpeg が PATH にない"
)


@pytest.mark.unit
class TestPresets:
    def test_all_moods_have_presets(self):
        for mood in ("upbeat", "calm", "trendy"):
            assert mood in _MOOD_PRESETS
            assert "freqs" in _MOOD_PRESETS[mood]


@pytest.mark.unit
@REQUIRES_FFMPEG
class TestSynthesize:
    def test_synthesize_creates_audio(self, tmp_path: Path):
        out = tmp_path / "bgm.aac"
        synthesize_bgm(out, 3.0, mood="upbeat")
        assert out.exists()
        assert out.stat().st_size > 1000

    def test_synthesize_all_moods(self, tmp_path: Path):
        for mood in ("upbeat", "calm", "trendy"):
            out = tmp_path / f"{mood}.aac"
            synthesize_bgm(out, 2.0, mood=mood)
            assert out.exists()

    def test_unknown_mood_falls_back(self, tmp_path: Path):
        out = tmp_path / "bgm.aac"
        synthesize_bgm(out, 2.0, mood="nonexistent")
        assert out.exists()


@pytest.mark.unit
@REQUIRES_FFMPEG
class TestMixBGM:
    def _make_silent_video(self, path: Path, dur: int = 3) -> Path:
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"color=c=blue:s=360x640:d={dur}",
             "-f", "lavfi", "-i",
             "anullsrc=channel_layout=stereo:sample_rate=44100",
             "-c:v", "libx264", "-c:a", "aac", "-shortest", "-t", str(dur),
             str(path)],
            capture_output=True,
        )
        return path

    def test_mix_into_video_with_audio(self, tmp_path: Path):
        video = self._make_silent_video(tmp_path / "v.mp4")
        bgm = tmp_path / "bgm.aac"
        synthesize_bgm(bgm, 3.0)
        out = tmp_path / "out.mp4"
        mix_bgm_into_video(video, bgm, out)
        assert out.exists()
        assert _has_audio_stream(out)
