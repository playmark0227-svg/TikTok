"""テキスト処理ユーティリティ"""

from __future__ import annotations

import re

# 主要な絵文字ブロックを除去
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001f000-\U0001ffff"  # Misc Symbols & Pictographs, Emoji, Symbols & Pictographs Extended-A 等
    "\U00002600-\U000027bf"  # Misc symbols + Dingbats
    "\U0001f1e6-\U0001f1ff"  # Flags
    "‍"                  # Zero Width Joiner
    "️"                  # Variation Selector-16
    "]+",
    flags=re.UNICODE,
)


def strip_emoji(text: str) -> str:
    """動画に焼き込むテキストから絵文字を除去
    (Noto Sans CJK は絵文字非対応のため豆腐文字 □ になる)
    """
    cleaned = _EMOJI_PATTERN.sub("", text)
    # 連続スペースを 1 つに
    cleaned = re.sub(r" +", " ", cleaned)
    # 各行末のスペースを削る
    lines = [line.rstrip() for line in cleaned.split("\n")]
    return "\n".join(lines).strip()
