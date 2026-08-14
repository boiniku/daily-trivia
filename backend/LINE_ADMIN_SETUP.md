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
- `TRIVIA_COLLECTION_MODEL`: 自動収集モデル。省略時は`gpt-5-mini`
- `TRIVIA_MAX_SEARCH_CALLS`: 1回の収集で許可するWeb検索回数。深掘り用の推奨値は`5`
- `TRIVIA_SEARCH_CONTEXT_SIZE`: Web検索から取得する文脈量。推奨値は`medium`
- `DAILY_COLLECTION_COUNT`: 毎日収集する件数。推奨値は`10`、最大`10`
- `DAILY_COLLECTION_MAX_PENDING`: 承認待ちがこの件数以上なら自動収集を停止。推奨値は`30`
- `DAILY_COLLECTION_MONTHLY_BUDGET_USD`: 月次概算費用がこの米ドル額に達したら停止。初期値は`6.0`
- `DAILY_COLLECTION_SECRET`: GitHub Actionsからの日次実行を認証する十分に長いランダム文字列

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
ヘルプ
新規
新規(地図用)
生成 宇宙 3
収集 5
収集 食べ物 5
地図収集
地図収集 京都 5
候補
```

- `ヘルプ`: LINE上に使い方を表示
- `新規`: 通常雑学の手入力フォームを開く
- `新規(地図用)`: 雑学MAP用の手入力フォームを開く。住所・施設名、都道府県、緯度経度、解説を入力できます
- `生成`: Web検索を使わず、モデルの知識から通常雑学の候補を作成
- `収集`: Web検索を使い、日本語の雑学まとめサイトから通常雑学の題材を探して独自文章を作成
- `地図収集`: Web検索で、住所・座標つきの雑学MAP候補だけを収集。地名なしなら幅広い場所からおまかせで集めます
- `候補` / `承認待ち` / `一覧`: 承認待ち候補をLINEに表示

`収集`で参考にするサイトを限定する場合は、Renderへ次を追加します。

```text
TRIVIA_DISCOVERY_DOMAINS=example.com,zatsugaku.example.jp
```

未設定の場合はドメインを限定せず、題材発見には雑学サイト、深掘り確認には公式サイト、
官公庁、大学・研究機関、博物館、専門メディアなども検索します。

収集処理はOpenAI Responses APIのWeb Searchを`required`で呼び出します。公開済みと承認待ちの
全タイトル、直近最大300件の本文要約を検索プロンプトへ渡し、取得後にもDB全件との類似判定を行います。
LINEの`収集`と毎朝9時の自動収集は、同じ収集・重複判定・候補保存処理を使用します。

候補カードの操作:

- `公開する`: 通常候補はアプリ用の`trivia`へ登録
- `MAP公開する`: 住所・座標が揃った候補は雑学MAPへ登録し、通常雑学には登録しない
- `編集する`: スマホ用フォームを開く
- `却下する`: 候補を却下

## 毎朝9時の自動収集

`.github/workflows/daily-trivia-collection.yml`が毎日00:00 UTC（日本時間の朝9:00）に
認証付きの日次収集エンドポイントを呼び出します。GitHubリポジトリに次を設定してください。

- Actions variable `DAILY_COLLECTION_URL`: `https://daily-trivia-backend.onrender.com`
- Actions secret `DAILY_COLLECTION_SECRET`: Renderの同名環境変数と同じ値

同じ日本日付の処理はDBに1件だけ記録されるため、再試行しても二重収集されません。
トークン数、Web検索回数、概算費用も記録されます。月次概算が上限へ達した場合は停止してLINEへ通知します。

`新規`では、AIを使わずにタイトル、本文、解説、カテゴリ、画像をスマホから入力できます。
`新規(地図用)`では、雑学MAP用として住所・施設名、都道府県、緯度経度も入力できます。フォーム上で通常雑学だけ、MAPだけ、または両方への登録を選べます。

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
