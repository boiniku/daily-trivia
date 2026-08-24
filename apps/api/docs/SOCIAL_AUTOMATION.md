# SNS投稿自動化

承認済みの`trivia`から、TikTok / Instagram向け静止画動画と、X / Threads向けテキストを作成します。通常運用は低価格な静止画動画、バズを狙う投稿だけ手動でSeedanceを選ぶ2レーン構成です。

## 安全な初期状態

XとThreadsへの実投稿は既定で無効です。認証情報を設定したうえで、対応するフラグを`true`にした媒体だけが投稿されます。

```text
SOCIAL_X_PUBLISH_ENABLED=true
SOCIAL_THREADS_PUBLISH_ENABLED=true
```

通常の`prepare`は`static`動画ジョブを作ります。脚本は「冒頭の意外性→疑問→答え→記憶に残る締め」の4シーン、18〜22秒で生成します。各シーン用の縦画像を最大4枚作り、ズームや左右パン、字幕、ナレーションを付けたH.264 MP4をFFmpegで作成します。生成画像は1枚ごとにR2へ保存するため、途中で処理が失敗しても再利用できます。

## 共通BGM

複数SNSでの利用が許可された歌詞なしのMP3を1曲だけ用意し、R2などの公開URLをRenderの環境変数へ設定します。

```text
SOCIAL_BGM_URL=https://your-public-r2.example/social/assets/bgm/main-loop.mp3
```

設定すると全動画で同じ曲をループし、ナレーションの10%の音量で自動ミックスします。未設定でも動画生成は成功します。TikTokなど各媒体のアプリ内楽曲をダウンロードして他媒体へ転用しないでください。

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
- 維持率を意識した4シーン脚本と、冒頭候補3案の生成
- 最大4枚の低品質画像を生成し、失敗時も画像単位で再利用
- パン・ズーム、日本語字幕、ナレーション、共通BGM付き静止画MP4生成
- 生成画像と完成MP4のR2保存
- Seedance非同期タスクの投入・状態確認
- Xテキスト投稿
- Threadsテキスト投稿
- 投稿の承認、冪等性、再試行、外部投稿の明示的な有効化

Instagram / TikTokへの実投稿はまだ未実装です。各媒体のAPI審査と認証情報を用意した後に追加します。

画像生成にはOpenAIの画像生成APIを使用します。新形式では通常4枚生成するため、画像料金は旧形式の約4倍になります。雑学の既存画像があれば1シーン目へ再利用し、その分の生成を省略します。
