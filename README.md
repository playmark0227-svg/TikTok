# TikTok 商品PR動画 自動生成・投稿システム

Amazon / 楽天のアフィリエイト商品から売れ筋・話題性の高いものを自動選定し、Google Gemini (Veo 3.1) で PR 動画を毎日 1 本生成、Discord で人間の承認を得た後、TikTok へ自動投稿するシステム。

## 全体フロー

```
[毎日17:00 launchd起動]
    ↓
[1] 商品選定: Amazon PA-API + 楽天API → 候補抽出 → スコアリング → 1つ選定
    ↓
[2] 企画生成: Claude APIで映像プロンプト・キャプション・ハッシュタグを生成
    ↓
[3] 動画生成: Gemini API (Veo 3.1 Fast) で 8秒 × 2本生成
    ↓
[4] 動画編集: FFmpegで連結・字幕焼き込み・BGM・「#PR」ロゴ
    ↓
[5] Firebase Storage にアップロード
    ↓
[6] Discord Botで動画送信 → ViFightが ✅承認 / ✏️修正 / ❌却下
    ↓ (修正なら③に戻る、最大3回)
[7] TikTok Content Posting API で投稿
    ↓
[8] Firestoreに投稿履歴記録
    ↓
[9] Discordに投稿完了通知
```

## 必要な API キー取得先

| サービス | 取得先 |
| --- | --- |
| Anthropic (Claude) | https://console.anthropic.com/ |
| Google Gemini (Veo) | https://aistudio.google.com/apikey |
| Amazon PA-API | https://affiliate.amazon.co.jp/ |
| 楽天アフィリエイト | https://webservice.rakuten.co.jp/ |
| TikTok for Developers | https://developers.tiktok.com/ |
| Discord Developer Portal | https://discord.com/developers/applications |
| Firebase | https://console.firebase.google.com/ |

## セットアップ手順

### 1. リポジトリのクローン

```bash
git clone <repo-url>
cd tiktok-auto-poster
```

### 2. 仮想環境作成 & 依存関係インストール

```bash
python3.11 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

> **注**: 一部の Debian / Ubuntu 環境では、システムの PyJWT と衝突して失敗することがあります。
> その場合は `pip install --ignore-installed PyJWT -r requirements.txt` を実行してください。
>
> **FFmpeg のインストール**: 動画編集に必須です。
> - macOS: `brew install ffmpeg`
> - Ubuntu/Debian: `sudo apt-get install ffmpeg`

### 3. 環境変数設定

`.env.example` を `.env` にコピーし、各種 API キーを記入する。

```bash
cp .env.example .env
# .env を編集
```

### 4. Firebase プロジェクト作成

1. https://console.firebase.google.com/ で新規プロジェクト作成
2. Firestore Database を有効化(本番モード)
3. Storage を有効化
4. プロジェクト設定 → サービスアカウント → 新しい秘密鍵生成 → `firebase-credentials.json` として保存
5. `.env` の `FIREBASE_PROJECT_ID`, `FIREBASE_STORAGE_BUCKET` を設定

### 5. Firestore 初期化

```bash
python scripts/setup_firebase.py
```

### 6. TikTok OAuth 認証(審査通過後)

```bash
python scripts/tiktok_oauth_init.py
```

### 7. 自動起動の設定 (macOS)

```bash
bash scripts/install_launchd.sh
```

## 動画生成モード

`.env` の `CONTENT_GENERATOR` と `VIDEO_MODE` で 2 系統に切り替え可能。

### モードA: Veo + Claude(高品質・有料)

```env
CONTENT_GENERATOR=claude
VIDEO_MODE=veo
ANTHROPIC_API_KEY=...
GEMINI_API_KEY=...     # Veo は Google Cloud billing 必須
```

- 月コスト目安: 3〜5万円(Veo が高い)
- 品質: AI 生成の本物の動画クリップ

### モードB: スライドショー + Gemini(低コスト・推奨)

```env
CONTENT_GENERATOR=gemini
VIDEO_MODE=slideshow
GEMINI_API_KEY=...     # 無料 tier で OK(text), 画像生成は billing 推奨
SLIDESHOW_SLIDE_COUNT=5
SLIDESHOW_SLIDE_DURATION=2.5
```

- 月コスト目安: ¥0〜500(Gemini text 無料 tier + 画像 billing 数百円)
- 品質: TikTok でよく見る商品紹介スライド型
- 画像生成 billing が無い場合は装飾付きプレースホルダにフォールバック

### 即時実行(launchd 経由ではなく今すぐ動かす)

```bash
python scripts/run_now.py
```

- Amazon/楽天 キー未設定でも事前定義サンプル商品で完走可能
- Firebase / Discord / TikTok キー未設定は自動で dry-run override

## テスト実行

```bash
# 全テスト
pytest

# 単体テストのみ
pytest -m unit

# カバレッジ確認
pytest --cov=src --cov-report=html
open htmlcov/index.html
```

## 開発モード

`.env` に以下を設定すると、外部 API 呼び出しをスキップして動作確認できる。

```
DRY_RUN=true
SKIP_TIKTOK_POST=true
```

## トラブルシューティング

| 症状 | 対処 |
| --- | --- |
| `pip install` が失敗 | Python 3.11+ を使用しているか確認 |
| Firebase 認証エラー | `firebase-credentials.json` の配置を確認 |
| TikTok 投稿失敗 | アクセストークンの期限を確認、`scripts/tiktok_oauth_init.py` で再認証 |
| Discord Bot が反応しない | `launchctl list | grep tiktok` で起動状態確認 |

## ディレクトリ構造

```
tiktok-auto-poster/
├── config/        # 設定ファイル
├── src/           # アプリ本体
├── storage_local/ # ローカル一時保管
├── logs/          # ログ
├── tests/         # テスト
├── scripts/       # 補助スクリプト
├── docs/          # ドキュメント
├── assets/        # BGM, フォント, ロゴ
└── launchd/       # macOS 自動起動設定
```

## 実装フェーズ

- [x] Phase 0: プロジェクト初期化
- [x] Phase 1: 商品選定モジュール
- [x] Phase 2: 企画生成モジュール
- [x] Phase 3: 動画生成 + 編集モジュール
- [x] Phase 4: Firebase 連携
- [x] Phase 5: Discord Bot
- [x] Phase 6: TikTok 投稿
- [x] Phase 7: パイプライン統合
- [x] Phase 8: 運用設定

## ドキュメント

### 公開ドキュメント (GitHub Pages)

GitHub Pages で公開する一般ユーザー向けドキュメント:

- 🌐 サイト: https://playmark0227-svg.github.io/tiktok/
- [プライバシーポリシー (日本語)](https://playmark0227-svg.github.io/tiktok/privacy_policy_ja/)
- [Privacy Policy (English)](https://playmark0227-svg.github.io/tiktok/privacy_policy_en/) — TikTok 審査に提出する URL

### 内部ドキュメント (リポジトリ内のみ)

- [運用マニュアル](docs/operation_manual.md)
- [TikTok 審査申請文](docs/tiktok_app_review.md)

### GitHub Pages の有効化手順

1. GitHub リポジトリ → **Settings** → **Pages**
2. **Source**: `Deploy from a branch`
3. **Branch**: `claude/vibrant-brown-eScjj`(または `main` にマージ後 `main`)、 Folder: `/docs`
4. **Save** をクリック
5. 1〜2 分後に https://playmark0227-svg.github.io/tiktok/ で公開される

## ライセンス

Proprietary - ViFight 個人事業
