# SNS投稿自動化

承認済みの`trivia`から、TikTok / Instagram向け静止画動画と、X / Threads向けテキストを作成します。通常運用は低価格な静止画動画、バズを狙う投稿だけ手動でSeedanceを選ぶ2レーン構成です。

## 安全な初期状態

XとThreadsへの実投稿は既定で無効です。認証情報を設定したうえで、対応するフラグを`true`にした媒体だけが投稿されます。

```text
SOCIAL_X_PUBLISH_ENABLED=true
SOCIAL_THREADS_PUBLISH_ENABLED=true
```

通常の`prepare`は`static`動画ジョブを作ります。雑学に`image_url`があれば再利用し、なければ`gpt-image-1-mini`のlow品質で縦画像を1枚生成します。字幕カードとナレーションを付けたH.264 MP4をFFmpegで作り、画像と完成動画をR2へ保存します。

SeedanceのモデルIDは契約・リージョンで利用可能な値を確認し、`SEEDANCE_MODEL`へ明示してください。Seedanceは`prepare --video-mode seedance`を明示した場合だけ利用します。

## CLI

`apps/api`をカレントディレクトリとして実行します。

```powershell
python -m scripts.social.run_social_pipeline prepare --trivia-id 123
python -m scripts.social.run_social_pipeline render-static 1
python -m scripts.social.run_social_pipeline status
python -m scripts.social.run_social_pipeline approve 1
python -m scripts.social.run_social_pipeline submit-video 1
python -m scripts.social.run_social_pipeline poll-video 1
python -m scripts.social.run_social_pipeline publish-text
```

`prepare`で`--trivia-id`を省略すると、SNSコンテンツ未作成の雑学を`hee_count`順で選びます。同じ雑学に対するジョブ作成は冪等です。

Seedance用コンテンツを準備する場合だけ、次のように明示します。

```powershell
python -m scripts.social.run_social_pipeline prepare --trivia-id 123 --video-mode seedance
```

## 内部API

すべて`Authorization: Bearer $SOCIAL_AUTOMATION_SECRET`が必要です。

```text
POST /internal/social/prepare
GET  /internal/social/jobs
POST /internal/social/content/{id}/approve
POST /internal/social/video/{id}/submit
POST /internal/social/video/{id}/poll
POST /internal/social/video/{id}/render-static
POST /internal/social/publish-text
```

作成直後のX・Threads投稿は`waiting_approval`です。`approve`後に`queued`となり、`publish-text`の対象になります。失敗時は最大3回まで再試行します。

## 現在の実装範囲

- 投稿セット生成
- Xの加重文字数ガード
- 既存画像優先・画像がない場合だけ低品質画像を1枚生成
- 日本語字幕カード・ナレーション付き静止画MP4生成
- 生成画像と完成MP4のR2保存
- Seedance非同期タスクの投入・状態確認
- Xテキスト投稿
- Threadsテキスト投稿
- 投稿の承認、冪等性、再試行、外部投稿の明示的な有効化

Instagram / TikTokへの実投稿はまだ未実装です。各媒体のAPI審査と認証情報を用意した後に追加します。

画像生成にはOpenAIの画像生成APIを使用します。`gpt-image-1-mini`の縦長low品質は公式料金で1枚$0.006です。既存画像がある雑学では画像生成料金は発生しません。
