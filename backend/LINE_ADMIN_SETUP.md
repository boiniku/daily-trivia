# LINE雑学管理の設定

## Render環境変数

- `DATABASE_URL`: Neonのオーナー接続URL
- `APP_DATABASE_URL`: アプリ用接続URL
- `OPENAI_API_KEY`: 雑学生成用
- `LINE_CHANNEL_SECRET`: Messaging APIチャネルシークレット
- `LINE_CHANNEL_ACCESS_TOKEN`: Messaging APIチャネルアクセストークン
- `LINE_ADMIN_USER_IDS`: 操作を許可するLINEユーザーID。複数の場合はカンマ区切り
- `CANDIDATE_EDITOR_SECRET`: 十分に長いランダム文字列
- `PUBLIC_BASE_URL`: 例 `https://daily-trivia-backend.onrender.com`

## LINE Developers Console

Webhook URLを次のように設定し、Webhookを有効にします。

```text
https://<Renderのホスト名>/line/webhook
```

Webhook再送も有効にできます。公開処理は同じ候補を二重登録しません。

## 最初のユーザーID確認

`LINE_ADMIN_USER_IDS`を未設定の状態でBotへメッセージを送ると、返信に設定用のLINEユーザーIDが表示されます。その値をRenderへ設定して再デプロイします。

## 操作

```text
生成 宇宙 3
候補
新規
```

候補カードの操作:

- `公開する`: アプリ用の`trivia`へ登録
- `編集する`: スマホ用フォームを開く
- `却下する`: 候補を却下

`新規`では、AIを使わずにタイトル、本文、解説、カテゴリ、画像をスマホから入力できます。

スマホフォームでは画像の選択、下書き保存、または編集後そのまま公開ができます。編集URLの有効期限は7日間です。

画像アップロードには次のR2環境変数も必要です。

- `R2_ENDPOINT_URL`
- `R2_ACCESS_KEY_ID`
- `R2_SECRET_ACCESS_KEY`
- `R2_BUCKET_NAME`
- `TRIVIA_IMAGE_R2_BASE_URL`
- `R2_TRIVIA_IMAGE_PREFIX`（省略時は`trivia`）

候補の保存時と公開時に、公開済み雑学および承認待ち候補とのタイトル・本文の類似判定を行います。却下した候補は候補履歴には残りますが、アプリ用の`trivia`には登録されません。

## データベース

Render起動時に`migrate_trivia_candidates.py`が実行され、候補テーブルへ必要な列が追加されます。ローカルで先に反映する場合:

```powershell
cd backend
python migrate_trivia_candidates.py
```
