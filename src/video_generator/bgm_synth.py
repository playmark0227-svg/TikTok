"""BGM シンセサイザー

assets/bgm/ に音源が無い場合のフォールバックとして、
ffmpeg で著作権フリーの BGM を合成する。無音より遥かにマシ。

mood ごとにコード進行・テンポ・音色を変える。
本番で著作権フリー BGM ファイルを assets/bgm/<mood>/ に置けば
そちらが優先される(VideoProcessor / engine 側のロジック)。
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from src.utils.logger import get_logger

logger = get_logger(__name__)

# mood ごとの設定: コード構成音(Hz)とテンポ感
_MOOD_PRESETS = {
    # 明るい長三和音 + 5度、軽いトレモロ
    "upbeat": {
        "freqs": [440.0, 554.37, 659.25, 880.0],  # A4 C#5 E5 A5 (Aメジャー)
        "tremolo_hz": 5.0,
        "tremolo_depth": 0.25,
        "lowpass": 3500,
        "volume": 0.8,
    },
    # 落ち着いたマイナー系、ゆったりトレモロ
    "calm": {
        "freqs": [392.0, 466.16, 587.33],  # G4 Bb4 D5 (Gマイナー)
        "tremolo_hz": 2.5,
        "tremolo_depth": 0.2,
        "lowpass": 2200,
        "volume": 0.75,
    },
    # トレンド風、やや高め + 速いトレモロ
    "trendy": {
        "freqs": [523.25, 659.25, 783.99, 1046.5],  # C5 E5 G5 C6 (Cメジャー)
        "tremolo_hz": 6.5,
        "tremolo_depth": 0.3,
        "lowpass": 4000,
        "volume": 0.8,
    },
}


class BGMSynthError(Exception):
    """BGM 合成エラー"""


def synthesize_bgm(
    output: Path,
    duration: float,
    *,
    mood: str = "upbeat",
    sample_rate: int = 44100,
) -> Path:
    """mood に応じた BGM を合成して output に書き出す

    複数のサイン波を重ねたパッド + トレモロ + ローパス + フェードで、
    耳に痛くない環境音楽風の BGM を作る。
    """
    preset = _MOOD_PRESETS.get(mood, _MOOD_PRESETS["upbeat"])
    output.parent.mkdir(parents=True, exist_ok=True)

    # 各周波数のサイン波を生成する入力 + amerge
    inputs: list[str] = []
    filter_parts: list[str] = []
    labels: list[str] = []
    for i, freq in enumerate(preset["freqs"]):
        inputs.extend(
            ["-f", "lavfi", "-t", f"{duration:.2f}",
             "-i", f"sine=frequency={freq}:sample_rate={sample_rate}"]
        )
        # 各音を減衰(和音の総和がクリップしない範囲で)
        filter_parts.append(f"[{i}:a]volume=0.5[s{i}]")
        labels.append(f"[s{i}]")

    n = len(preset["freqs"])
    mix = (
        "".join(labels)
        + f"amix=inputs={n}:duration=longest:normalize=0[mixed];"
    )
    # トレモロ(音量を周期的に揺らす) + ローパス + 全体音量 + フェード
    post = (
        f"[mixed]tremolo=f={preset['tremolo_hz']}:d={preset['tremolo_depth']},"
        f"lowpass=f={preset['lowpass']},"
        f"volume={preset['volume']},"
        f"afade=t=in:st=0:d=1.0,"
        f"afade=t=out:st={max(0.0, duration - 1.2):.2f}:d=1.2[out]"
    )
    filter_complex = ";".join(filter_parts) + ";" + mix + post

    cmd = [
        "ffmpeg", "-y",
        *inputs,
        "-filter_complex", filter_complex,
        "-map", "[out]",
        "-c:a", "aac", "-b:a", "128k",
        str(output),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("BGM 合成失敗", stderr=result.stderr[-400:])
        raise BGMSynthError(f"BGM 合成失敗: {result.stderr[-200:]}")
    logger.info("BGM 合成完了", mood=mood, duration=round(duration, 1), path=str(output))
    return output


def mix_bgm_into_video(
    video: Path,
    bgm: Path,
    output: Path,
    *,
    bgm_volume: float = 0.5,
    original_volume: float = 1.0,
) -> Path:
    """動画に BGM をミックス(元音声があれば混ぜる、無ければ BGM のみ)"""
    output.parent.mkdir(parents=True, exist_ok=True)

    # 元動画に音声トラックがあるか
    has_audio = _has_audio_stream(video)

    if has_audio:
        filter_complex = (
            f"[0:a]volume={original_volume}[a0];"
            f"[1:a]volume={bgm_volume}[a1];"
            f"[a0][a1]amix=inputs=2:duration=first:normalize=0[aout]"
        )
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(bgm),
            "-filter_complex", filter_complex,
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart",
            str(output),
        ]
    else:
        cmd = [
            "ffmpeg", "-y",
            "-i", str(video),
            "-i", str(bgm),
            "-map", "0:v", "-map", "1:a",
            "-c:v", "copy", "-c:a", "aac",
            "-shortest", "-movflags", "+faststart",
            str(output),
        ]

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error("BGM ミックス失敗", stderr=result.stderr[-400:])
        raise BGMSynthError(f"BGM ミックス失敗: {result.stderr[-200:]}")
    return output


def _has_audio_stream(video: Path) -> bool:
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a",
             "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(video)],
            capture_output=True, text=True,
        )
        return "audio" in result.stdout
    except Exception:
        return False
