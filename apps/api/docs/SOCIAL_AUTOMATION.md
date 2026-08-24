# SNS投稿自動化

承認済みの`trivia`から、TikTok / Instagram向け静止画動画と、X / Threads向けテキストを作成します。通常運用は低価格な静止画動画、バズを狙う投稿だけ手動でSeedanceを選ぶ2レーン構成です。

## 安全な初期状態

XとThreadsへの実投稿は既定で無効です。認証情報を設定したうえで、対応するフラグを`true`にした媒体だけが投稿されます。

```text
SOCIAL_X_PUBLISH_ENABLED=true
SOCIAL_THREADS_PUBLISH_ENABLED=true
```

通常の`prepare`は`static`動画ジョブを作ります。脚本は「冒頭の意外性→疑問→答え→記憶に残る締め」の4シーン、18〜22秒で生成します。各シーン用の縦画像を最大4枚作り、ズームや左右パン、字幕、ナレーションを付けたH.264 MP4をFFmpegで作成します。生成画像は1枚ごとにR2へ保存するため、途中で処理が失敗しても再利用できます。

脚本の前に`gpt-5.6-luna`とWeb検索でDBの短い雑学を調査し、主題、よくある勘違い、確認済み事実、補足、注意点、出典を事実メモにします。脚本はこのメモだけを根拠に生成し、対象不明の「これ」から始まる導入、場面時間に対して長すぎるナレーション、一般的すぎる締めを機械的に検査します。検査に失敗した場合は画像生成前に一度だけ自動修正します。

調査結果と生成使用量はコンテンツJSONの`research`と`generation_meta`へ保存されます。標準ではWeb検索を1回に制限します。

```text
SOCIAL_CONTENT_MODEL=gpt-5.6-luna
SOCIAL_RESEARCH_MAX_SEARCH_CALLS=1
SOCIAL_RESEARCH_SEARCH_CONTEXT_SIZE=low
```

### 1投稿あたりの概算費用

標準設定、約20秒、画像4枚の場合の目安です。実際の文字数、検索結果、自動修正の有無で変動します。

| 処理 | 概算 |
| --- | ---: |
| Web調査1回 | $0.010 |
| Lunaによる事実メモ・脚本 | $0.001〜0.004 |
| 縦長low画像4枚 | $0.024 |
| 約120文字のTTS | 約$0.002 |
| 合計 | 約$0.037〜0.040 |

毎日1本を30日作る場合は約$1.1〜1.2です。Seedance、SNS各社の有料API、Renderの有料プランは含みません。`generation_meta.estimated_cost_usd`には各ジョブの調査・脚本部分の実測トークンに基づく概算が保存されます。

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
POST /internal/social/content/{id}/regenerate
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
