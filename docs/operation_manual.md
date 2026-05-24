# 運用マニュアル

ViFight TikTok 商品PR動画 自動投稿システム

## 1. 日常運用

### 1.1 標準的な1日の流れ

| 時刻 | イベント |
| --- | --- |
| 17:00 | launchd がパイプラインを起動 |
| 17:00-17:10 | 商品選定 → 企画生成 |
| 17:10-17:20 | Veo で動画生成(8秒×2本)|
| 17:20-17:22 | FFmpeg で編集(連結・字幕・BGM・PR表示)|
| 17:22 | Discord 承認チャンネルに通知 |
| 17:22-?? | ViFight 承認待ち(最長24時間)|
| 承認後即時 | TikTok 投稿 |
| 投稿後 | Discord 通知チャンネルに完了報告 |

### 1.2 Discord 操作

#### 承認する場合
1. 承認チャンネルに届いた動画 + 企画を確認
2. メッセージに `✅` でリアクション
3. 自動的に TikTok 投稿される

#### 修正を依頼する場合
1. メッセージに `✏️` でリアクション
2. Bot からの「修正指示を入力してください」リプライに対して、自然言語で指示を返信
   - 例: 「もっと明るい雰囲気で」「商品をアップで撮って」「キャプションを若者向けに」
3. 動画が再生成され、再度承認チャンネルに届く
4. 修正は最大3回まで、超えると自動却下

#### 却下する場合
1. メッセージに `❌` でリアクション
2. その日は投稿されず、翌日の17:00に再実行

### 1.3 候補商品が見つからない場合

- Discord 通知チャンネルに「候補商品なし」エラーが届く
- 翌日17:00に自動再実行される
- 連続2日候補なしなら、`config/categories.yaml` のキーワード見直しを検討

## 2. エラー対応

### 2.1 よくあるエラー

| エラー | 原因 | 対処 |
| --- | --- | --- |
| `Amazon API 認証失敗` | アクセスキー期限切れ / レート制限 | `.env` 更新 / 翌日リトライ |
| `Veo 生成タイムアウト` | プロンプト問題 / API 障害 | プロンプトを抽象化、`.env` で `VEO_MODEL` を別バージョンに変更 |
| `TikTok 401 Unauthorized` | アクセストークン期限切れ | `python scripts/tiktok_oauth_init.py` で再認証 |
| `Discord 通知が届かない` | Bot プロセス停止 | `bash scripts/install_launchd.sh status` で確認、必要なら再インストール |
| `Firebase Storage アップロード失敗` | バケット容量 / 認証 | Firebase Console で容量・サービスアカウント確認 |

### 2.2 ログの確認

```bash
# 直近のアプリログ
tail -f logs/app.log

# launchd Bot ログ
tail -f logs/launchd_bot.out.log
tail -f logs/launchd_bot.err.log

# launchd パイプラインログ
tail -f logs/launchd_pipeline.out.log
tail -f logs/launchd_pipeline.err.log
```

### 2.3 手動でパイプライン実行

```bash
cd ~/path/to/tiktok-auto-poster
source .venv/bin/activate

# DRY_RUN で試走(本物の API は叩かない)
python main.py --dry-run

# 本番実行(通常は launchd 経由)
python main.py
```

### 2.4 試走スクリプト

承認まで自動化された E2E テスト:

```bash
python scripts/test_run.py
```

## 3. メンテナンス

### 3.1 月次メンテナンスチェックリスト

- [ ] TikTok アクセストークン有効期限(Firestore `tokens/tiktok` を確認、期限切れなら手動更新)
- [ ] Firebase Storage 使用量(無料枠 5GB 以内か)
- [ ] Firestore リード/ライト数(無料枠超過の確認)
- [ ] Amazon PA-API 利用状況(レート制限解除条件: 過去30日売上)
- [ ] 楽天 API 利用状況(レート制限超過チェック)
- [ ] 投稿実績レビュー(Firestore `posts` コレクションを集計)
- [ ] BGM ライブラリの追加(同じ曲ばかりにならないよう)
- [ ] `config/categories.yaml` のキーワード見直し

### 3.2 API キー更新手順

1. `.env` を編集
2. launchd を再起動して環境変数を再読み込み:
   ```bash
   bash scripts/install_launchd.sh stop
   bash scripts/install_launchd.sh install
   ```

### 3.3 依存関係の更新

```bash
source .venv/bin/activate
pip list --outdated
pip install --upgrade -r requirements.txt

# テスト実行で破壊的変更を検知
pytest
```

### 3.4 商品選定カテゴリの追加

`config/categories.yaml` に新規エントリを追加:

```yaml
- name: 新カテゴリ名
  keywords:
    - 検索キーワード1
    - 検索キーワード2
  amazon_browse_node_id: "AmazonのカテゴリID"
  rakuten_genre_id: 楽天のジャンルID
  weight: 1.0
```

`.env` の `TARGET_CATEGORIES` にも追加してから launchd を再起動。

## 4. 起動・停止

### 4.1 launchd インストール(初回 / 再インストール)

```bash
bash scripts/install_launchd.sh install
```

### 4.2 停止

```bash
bash scripts/install_launchd.sh stop
```

### 4.3 状態確認

```bash
bash scripts/install_launchd.sh status
```

### 4.4 完全削除

```bash
bash scripts/install_launchd.sh uninstall
```

## 5. 緊急時対応

### 5.1 異常な投稿が出てしまった場合

1. TikTok アプリで該当投稿を削除
2. Firestore `posts` コレクションから該当ドキュメントを削除または `status: "deleted"` に更新
3. 当面 `.env` で `SKIP_TIKTOK_POST=true` にして自動投稿を停止
4. 原因調査(ログ確認、プロンプト見直し)

### 5.2 ステマ規制違反の懸念がある場合

1. 直ちに `SKIP_TIKTOK_POST=true` で停止
2. 過去投稿を全件確認(Firestore `posts` の `caption` と `hashtags` を grep)
3. `#PR` `#広告` が抜けているものがあれば、TikTok 上で訂正・削除
4. `src/tiktok_publisher/publisher.py` の `validate_caption()` がパスしなかったログを追跡

### 5.3 API 利用料金の急増

1. `.env` で `SKIP_TIKTOK_POST=true` および launchd 停止で支出を凍結
2. Anthropic / Google / Firebase の各コンソールで使用量確認
3. プロンプトキャッシュの効きを確認(`claude_client.py`)
4. Veo モデルを `veo-3.1-lite-generate-preview` に下げる選択肢

## 6. 連絡先

| 用途 | 連絡先 |
| --- | --- |
| 運用者(ViFight) | playmark0227@gmail.com |
| Anthropic サポート | https://support.anthropic.com/ |
| Google Cloud サポート | https://cloud.google.com/support |
| TikTok for Developers | https://developers.tiktok.com/support |
