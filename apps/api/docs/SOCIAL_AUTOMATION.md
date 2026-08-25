# SNS投稿自動化

承認済みの`trivia`から、TikTok / Instagram向け動画と、X / Threads向けテキストを作成します。通常運用はKling 3.0の短い動画と静止画を組み合わせ、特別な投稿だけ別の動画モデルを選べる構成です。

## 安全な初期状態

XとThreadsへの実投稿は既定で無効です。認証情報を設定したうえで、対応するフラグを`true`にした媒体だけが投稿されます。

```text
SOCIAL_X_PUBLISH_ENABLED=true
SOCIAL_THREADS_PUBLISH_ENABLED=true
```

通常の`prepare`は`static`動画ジョブを作ります。調査結果から、勘違いの反転、クイズ、名前の由来、仕組み、基本の答え明かしのいずれかを選び、4〜5シーン、18〜22秒で生成します。人気動画の固有の文章はコピーせず、冒頭で期待を作って情報を小分けにし、最後に回収する構造だけを利用します。各シーン用の縦画像を最大5枚作り、ズームや左右パン、字幕、ナレーションを付けたH.264 MP4をFFmpegで作成します。生成画像は1枚ごとにR2へ保存するため、途中で処理が失敗しても再利用できます。

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

## Aivis Cloud APIの音声

通常の音声はAivis Cloud APIを使用します。APIキー以外は`render.yaml`に標準値があります。別のモデルを使う場合はモデルUUIDと、そのモデルが持つスタイル名へ変更してください。

```text
SOCIAL_TTS_PROVIDER=aivis
AIVIS_API_KEY=...
AIVIS_MODEL_UUID=47e53151-a378-46f3-abee-ce13aa07feb1
AIVIS_STYLE_NAME=ノーマル
AIVIS_SELECTED_STYLE=Surprise
AIVIS_HOOK_STYLE_NAME=Surprise
```

標準運用では選定済みの`Surprise`を全編へ利用します。`AIVIS_STYLE_NAME`は低レベルクライアントのフォールバック設定です。

無料クレジットで声を決める間は、動画をレンダリングせず試聴APIを使います。指定したコンテンツの冒頭2場面だけを合成し、MP3をR2へ保存します。1回のリクエストは最大180文字、3スタイルまでです。

```powershell
$preview = Invoke-RestMethod `
  -Method Post `
  -Uri "https://daily-trivia-e7ge.onrender.com/internal/social/content/1/voice-previews" `
  -Headers $SocialHeaders `
  -ContentType "application/json" `
  -Body '{"styles":["ノーマル","Calm","Surprise"]}'

$preview.previews | Format-Table style, audio_url, character_count
```

スタイル名は選択したモデルが実際に持つものだけを指定します。採用する声が決まったら`AIVIS_STYLE_NAME`を固定し、本番の`render-static`を実行します。

## 共通BGM

複数SNSでの利用が許可された歌詞なしのMP3を1曲だけ用意し、R2などの公開URLをRenderの環境変数へ設定します。

```text
SOCIAL_BGM_URL=https://your-public-r2.example/social/assets/bgm/main-loop.mp3
```

設定すると全動画で同じ曲をループし、ナレーションの10%の音量で自動ミックスします。未設定でも動画生成は成功します。TikTokなど各媒体のアプリ内楽曲をダウンロードして他媒体へ転用しないでください。

現在の標準曲はDOVA-SYNDROMEの「Escort」（もっぴーさうんど）です。DOVAの再配布禁止条件を守るため、元MP3はR2上で暗号化し、Render内でのみ復号して完成動画へミックスします。公開R2 URLで元音源を配信しません。

## 毎日雑学への誘導

動画本編の後に、R2へ保存した同一の5秒プロモーション動画を連結します。「毎日3つ」「ウィジェットで見られる」「アプリアイコンと毎日雑学」を順に表示し、ナレーションにも固定の案内を追加します。脚本AIに宣伝文を作らせないため、雑学に関係なくブランド表現が安定し、プロモーション映像の生成費も毎回発生しません。

```text
SOCIAL_PROMO_VIDEO_URL=https://your-public-r2.example/social/assets/video/daily-trivia-promo.mp4
SOCIAL_BRAND_CTA_NARRATION=毎日3つの雑学を、ウィジェットで。毎日雑学。
SOCIAL_BRAND_CTA_SUBTITLE=続きは「毎日雑学」で
```

## 固定イントロ

動画の先頭には約1秒の固定イントロを連結します。「これ知ってたら／ちょっとすごい／今日の雑学」という高コントラストの動く文字を表示しながら、その回固有のhookナレーションを0秒から流します。同じ導入を長く見せないため、イントロは1秒で切って本編映像へ移ります。

```text
SOCIAL_INTRO_VIDEO_URL=https://your-public-r2.example/social/assets/video/daily-trivia-intro.mp4
```

SeedanceのモデルIDは契約・リージョンで利用可能な値を確認し、`SEEDANCE_MODEL`へ明示してください。Seedanceは`prepare --video-mode seedance`を明示した場合だけ利用します。

## Kling（通常の動画生成）

Kling Open PlatformでAPIキーとAPI残高を用意し、Renderへ次を設定します。通常サイトの会員クレジットとは別管理です。

```text
KLING_API_KEY=...
KLING_MODEL=kling-3.0
KLING_DURATION_SECONDS=5
KLING_MONTHLY_VIDEO_LIMIT=5
```

`kling`モードでは、revealシーン用の初回フレームを生成してR2へ保存し、Kling 3.0へ720p・5秒・音声なし・single-shotで投入します。月内に外部タスクを投入済みのKling動画ジョブが5件に達すると、それ以上の送信を拒否します。Klingの出力URLは一時的なため、`poll-video`で成功を確認した時点でR2へ退避します。

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

Kling用コンテンツを準備して動画を生成する場合は次の順序です。

```powershell
python -m scripts.social.run_social_pipeline prepare --trivia-id 123 --video-mode kling
python -m scripts.social.run_social_pipeline submit-video VIDEO_JOB_ID
python -m scripts.social.run_social_pipeline poll-video VIDEO_JOB_ID
```

## 内部API

すべて`Authorization: Bearer $SOCIAL_AUTOMATION_SECRET`が必要です。

```text
POST /internal/social/prepare
GET  /internal/social/jobs
POST /internal/social/content/{id}/regenerate
POST /internal/social/content/{id}/voice-previews
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
- 雑学タイプ別の4〜5シーン脚本と、冒頭候補3案の生成
- Aivis音声と、動画生成前の低コストな声の試聴
- 最大4枚の低品質画像を生成し、失敗時も画像単位で再利用
- パン・ズーム、日本語字幕、ナレーション、共通BGM付き静止画MP4生成
- 生成画像と完成MP4のR2保存
- Seedance非同期タスクの投入・状態確認
- Kling 3.0の720p・5秒・無音タスク投入、月5本制限、R2退避
- Xテキスト投稿
- Threadsテキスト投稿
- 投稿の承認、冪等性、再試行、外部投稿の明示的な有効化

Instagram / TikTokへの実投稿はまだ未実装です。各媒体のAPI審査と認証情報を用意した後に追加します。

画像生成にはOpenAIの画像生成APIを使用します。新形式では通常4枚生成するため、画像料金は旧形式の約4倍になります。雑学の既存画像があれば1シーン目へ再利用し、その分の生成を省略します。
