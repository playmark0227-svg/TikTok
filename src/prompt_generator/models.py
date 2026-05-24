"""企画データモデル"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

BgmMood = Literal["upbeat", "calm", "trendy"]


@dataclass
class ContentPlan:
    """Veo + TikTok 投稿用の企画"""

    veo_prompt_clip1: str  # 1本目8秒の英語プロンプト
    veo_prompt_clip2: str  # 2本目8秒の英語プロンプト
    caption: str  # TikTok キャプション(日本語)
    hashtags: list[str]  # ハッシュタグ
    subtitle_text: str  # 動画に焼き込む字幕
    bgm_mood: BgmMood = "upbeat"
    voice_style: str = "energetic"  # 音声スタイルヒント
    generated_at: datetime = field(default_factory=datetime.now)
    revision_count: int = 0
    raw_response: str = ""  # Claude の生レスポンス

    def to_dict(self) -> dict:
        return {
            "veo_prompt_clip1": self.veo_prompt_clip1,
            "veo_prompt_clip2": self.veo_prompt_clip2,
            "caption": self.caption,
            "hashtags": self.hashtags,
            "subtitle_text": self.subtitle_text,
            "bgm_mood": self.bgm_mood,
            "voice_style": self.voice_style,
            "generated_at": self.generated_at,
            "revision_count": self.revision_count,
        }

    @property
    def full_caption(self) -> str:
        """ハッシュタグ込みの最終キャプション"""
        tags = " ".join(self.hashtags)
        return (
            f"{self.caption}\n\n"
            f"{tags}\n\n"
            f"※プロフィールのリンクから商品をチェック✨"
        )
