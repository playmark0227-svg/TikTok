"""プロンプトテンプレート

Claude へ送るシステムプロンプトと、入力フォーマットを管理する。
"""

from __future__ import annotations

from src.product_selector.models import Product

SYSTEM_PROMPT = """あなたは TikTok の商品PR動画の企画ディレクター兼コピーライターです。
ユーザーから提供される商品情報を基に、以下の要素を生成してください。

# 出力要件
**必ず以下の JSON 形式で出力してください。それ以外の文字列(前置き・コードフェンス等)は出力しないでください。**

```json
{
  "veo_prompt_clip1": "...",
  "veo_prompt_clip2": "...",
  "caption": "...",
  "hashtags": ["#PR", "#広告", ...],
  "subtitle_text": "...",
  "bgm_mood": "upbeat" | "calm" | "trendy",
  "voice_style": "..."
}
```

# 各要素の仕様

## veo_prompt_clip1 / veo_prompt_clip2
- 言語: **英語**
- 各150単語以内
- Veo 3.1 で生成する8秒の縦動画(9:16)のプロンプト
- clip1: フック・商品の登場・印象的なシーン
- clip2: 商品の使用シーン・効果・ベネフィット
- 実在ブランド名・特定の商品名は使わない(一般化・抽象化)
- 人物の特定や著名人の模倣は避ける
- 「product on a clean studio background」「woman in her 20s using the product, soft natural light」のように、安全で再現可能な描写にする
- 音声(ナレーション・効果音)も自然に含む
- 縦動画(vertical, 9:16, portrait)を明示

## caption
- 言語: **日本語**
- 80〜150文字
- 構成: フック(疑問・驚き) → 商品の魅力 → 行動喚起(CTA)
- 絵文字を 2〜4 個入れる
- 「※プロフィールのリンクから」等の文言は不要(別途自動追加)

## hashtags
- 日本語ベース、半角 # 始まり
- 8〜12個
- **必ず "#PR" "#広告" を含める**(景表法・ステマ規制対応)
- 残りはトレンド・商品カテゴリ・ターゲット層に関するもの
- 例: #おすすめ #便利グッズ #映え #新生活

## subtitle_text
- 言語: **日本語**
- 動画に焼き込む短いキャッチコピー(1〜3文、各15文字以内)
- 改行で区切る(1行ずつ順次表示する想定)

## bgm_mood
- "upbeat" / "calm" / "trendy" のいずれか
- 商品ジャンル・ターゲットに合わせる

## voice_style
- 音声のトーン("energetic", "calm friendly", "professional" など)を英語で

# 注意事項
- 著作権・商標を侵害しない
- 誇大広告(「絶対」「100%」「業界No.1」等)は避ける
- 景品表示法・薬機法・ステマ規制を遵守
- 健康・美容商品は効果効能を断定しない
"""

PROMPT_TEMPLATE = """以下の商品の PR 動画企画を生成してください。

# 商品情報
- ソース: {source}
- カテゴリ: {category}
- タイトル: {title}
- 価格: ¥{price:,}
- 評価: {rating} ({review_count}件のレビュー)
- 商品説明: {description}

{few_shot_block}

# 出力
上記の商品情報を基に、システムプロンプトで指定された JSON 形式で企画を出力してください。
"""

REVISION_TEMPLATE = """前回生成した企画に対して、以下のフィードバックを反映して再生成してください。

# 商品情報
- カテゴリ: {category}
- タイトル: {title}

# 前回の企画(JSON)
{previous_json}

# ユーザーからのフィードバック
{feedback}

# 出力
フィードバックを反映した新しい企画を、システムプロンプトで指定された JSON 形式で出力してください。
"""

FEW_SHOT_HEADER = "# 過去の好成績例(参考)"


def build_few_shot_block(examples: list[dict]) -> str:
    """過去の高再生例を Claude プロンプト用に整形

    Args:
        examples: [{"product_title": "...", "caption": "...", "hashtags": [...], "veo_prompt_clip1": "..."}]
    """
    if not examples:
        return ""

    lines = [FEW_SHOT_HEADER, ""]
    for i, ex in enumerate(examples, 1):
        lines.append(f"## 例 {i}")
        lines.append(f"- 商品: {ex.get('product_title', 'N/A')}")
        cap = ex.get("caption", "")
        if cap:
            lines.append(f"- キャプション: {cap}")
        tags = ex.get("hashtags", [])
        if tags:
            lines.append(f"- ハッシュタグ: {' '.join(tags)}")
        prompt = ex.get("veo_prompt_clip1", "")
        if prompt:
            lines.append(f"- 映像プロンプト1: {prompt[:200]}")
        lines.append("")
    return "\n".join(lines)


def build_prompt(product: Product, few_shot_examples: list[dict] | None = None) -> str:
    """商品情報を Claude 入力用に整形"""
    few_shot = build_few_shot_block(few_shot_examples or [])
    return PROMPT_TEMPLATE.format(
        source=product.source,
        category=product.category,
        title=product.title,
        price=product.price,
        rating=product.rating,
        review_count=product.review_count,
        description=product.description,
        few_shot_block=few_shot,
    )


def build_revision_prompt(
    product: Product,
    previous_json: str,
    feedback: str,
) -> str:
    """修正用プロンプト"""
    return REVISION_TEMPLATE.format(
        category=product.category,
        title=product.title,
        previous_json=previous_json,
        feedback=feedback,
    )
