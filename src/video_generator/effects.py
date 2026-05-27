"""動画エフェクト集

スライドショーで使う複数のエフェクトを FFmpeg filter として提供。
各エフェクトは画像1枚を入力 → 短尺動画化する関数。
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass


@dataclass
class EffectConfig:
    """エフェクト設定"""

    name: str
    vf_builder: Callable[[int, int, float, int], str]
    """vf_builder(width, height, duration_sec, fps) -> filter string"""


def _cover_filter(w: int, h: int) -> str:
    """画像を w×h にカバー風(ズームしてクロップ)"""
    return (
        f"scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h}"
    )


def ken_burns_zoom_in(w: int, h: int, dur: float, fps: int) -> str:
    """ゆっくり拡大"""
    total = int(dur * fps)
    cover = _cover_filter(w, h)
    return (
        f"{cover},zoompan=z='min(zoom+0.0015,1.15)':d={total}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )


def ken_burns_zoom_out(w: int, h: int, dur: float, fps: int) -> str:
    """ゆっくり縮小"""
    total = int(dur * fps)
    cover = _cover_filter(w, h)
    return (
        f"{cover},zoompan=z='if(eq(on,0),1.15,max(zoom-0.0015,1.0))':d={total}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )


def zoom_punch(w: int, h: int, dur: float, fps: int) -> str:
    """最初に強くズーム → 徐々に落ち着く(インパクト演出)"""
    total = int(dur * fps)
    cover = _cover_filter(w, h)
    # 最初の 0.3 秒で 1.0 → 1.3 にズーム、その後 1.05 まで戻る
    # if(lte(on, 9), 1+on*0.033, max(1.3-((on-9)*0.005), 1.05))
    return (
        f"{cover},zoompan="
        f"z='if(lte(on\\,9)\\,1+on*0.033\\,max(1.3-((on-9)*0.005)\\,1.05))':"
        f"d={total}:"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )


def pan_left_to_right(w: int, h: int, dur: float, fps: int) -> str:
    """左から右へパン(画像を 1.2 倍してX移動)"""
    total = int(dur * fps)
    cover = _cover_filter(int(w * 1.3), h)
    return (
        f"{cover},zoompan=z='1.15':d={total}:"
        f"x='(iw-iw/zoom)*on/{total}':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )


def pan_right_to_left(w: int, h: int, dur: float, fps: int) -> str:
    """右から左へパン"""
    total = int(dur * fps)
    cover = _cover_filter(int(w * 1.3), h)
    return (
        f"{cover},zoompan=z='1.15':d={total}:"
        f"x='(iw-iw/zoom)*(1-on/{total})':y='ih/2-(ih/zoom/2)':"
        f"s={w}x{h}:fps={fps}"
    )


def static_cover(w: int, h: int, dur: float, fps: int) -> str:
    """静止(エフェクトなし)"""
    return f"{_cover_filter(w, h)},fps={fps}"


EFFECTS: list[EffectConfig] = [
    EffectConfig("ken_burns_in", ken_burns_zoom_in),
    EffectConfig("zoom_punch", zoom_punch),
    EffectConfig("pan_left_to_right", pan_left_to_right),
    EffectConfig("ken_burns_out", ken_burns_zoom_out),
    EffectConfig("pan_right_to_left", pan_right_to_left),
]


def pick_effect(index: int) -> EffectConfig:
    """slide index で効果をローテーション(最初の zoom_punch は強烈なフック用)"""
    if index == 0:
        return next(e for e in EFFECTS if e.name == "zoom_punch")
    return EFFECTS[index % len(EFFECTS)]


TRANSITIONS = [
    "fade",
    "wipeleft",
    "wiperight",
    "slideup",
    "slidedown",
    "circlecrop",
]


def pick_transition(index: int) -> str:
    """transition 種類をローテーション"""
    return TRANSITIONS[index % len(TRANSITIONS)]
