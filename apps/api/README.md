# API

毎日雑学のFastAPI APIと管理機能です。

## 主な構成

```text
apps/api/
├─ main.py              FastAPIエントリーポイント
├─ admin_dashboard.py   Streamlit管理画面
├─ database.py          DB接続とセッション
├─ models.py            SQLAlchemyモデル
├─ routers/             APIルーター
├─ services/            ドメイン処理と外部サービス連携
├─ scripts/             DB移行・データ投入・保守コマンド
├─ tests/               自動テスト
└─ requirements.txt     Python依存関係
```

## 開発

```powershell
cd apps/api
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

環境変数は`.env.example`を参考に`.env`へ設定してください。

## 雑学管理画面

```powershell
cd apps/api
.\venv\Scripts\python.exe -m streamlit run admin_dashboard.py
```

- 「新規登録」で通常・地図用・両方を選択します。地図用には都道府県、住所・施設名、緯度、経度が必要です。ヒントと解放半径も設定できます。
- 写真欄の「端末から写真を追加（複数選択可）」で写真をまとめて選べます。「登録する写真」に保存予定の合計枚数を表示します。
- 「R2の画像候補から選ぶ」→「画像候補を読み込む / 更新」で保存済み画像を表示します。複数の写真にチェックを付け、「選択した写真をまとめて追加」を押してください。ページを移動して選び続けられます。「この写真を追加」では1枚ずつ追加できます。
- 写真は1件につき最大10枚です。複数アップロード、R2画像の追加、URLの改行入力に対応し、矢印で表示順を変更できます。先頭の写真が表紙です。「外す」で写真を一覧から除き、登録・更新すると保存されます。
- 画像一覧の初期フォルダは`R2_TRIVIA_IMAGE_PREFIX`です。空欄にするとバケット全体が対象になります。必要なR2設定は`.env.example`を参照してください。
- 「AI収集・承認」では候補を1件ずつ選んで編集・公開できます。既存候補の承認にはOpenAI APIキーは不要です。
- 「管理・編集」では通常雑学からのMAP登録、MAPの写真・出典・ヒント編集、非公開・再公開ができます。写真の関連付け解除ではR2の画像自体を残すため、他の雑学で共有している画像も引き続き使えます。

入力エラー時の内容と、画面・登録先を切り替えたときのテキスト入力は同じブラウザーセッション内で保持されます。通常と地図の同時登録はまとめて保存され、片方だけが登録されることはありません。

複数写真のデータ移行と外部ツール向けの保存仕様は[複数写真の運用手順](docs/MULTIPLE_IMAGES.md)を参照してください。

「管理・編集 → 写真の確認」は、リポジトリ内の[`tools/trivia_photo`](../../tools/trivia_photo/README.md)を利用します。「写真の管理対象」で通常雑学・雑学MAPを切り替え、候補の複数枚承認と管理画面の本番DBへの自動反映ができます。写真ツールの接続情報や画像をGitに追加する必要はありません。

## テスト

```powershell
python -m unittest discover -s tests -v
```

LINE管理機能の設定は[`docs/LINE_ADMIN_SETUP.md`](docs/LINE_ADMIN_SETUP.md)を参照してください。

Seedance動画とX投稿の自動化は[`docs/SOCIAL_AUTOMATION.md`](docs/SOCIAL_AUTOMATION.md)を参照してください。

## 雑学の自動収集元

自動収集は、`services/trivia_collection.py` の許可リストにある雑学・豆知識サイトだけを検索します。検索ツール側のドメイン制限に加え、保存前にも出典URLのホスト名を検証します。

収集元を変更する場合は、カンマ区切りの `TRIVIA_DISCOVERY_DOMAINS` で上書きできます。空値は制限解除にはならず、組み込みの許可リストへ戻ります。

```text
TRIVIA_DISCOVERY_DOMAINS=zatsuneta.com,kerokero-info.com,i-trivia.net
```

日次のランダム収集では、公開済み・承認待ちに同じ中心対象がある候補も除外します。テーマを明示した手動収集では、同じ対象でも事実が異なる候補を調査できます。

## 運用スクリプト

APIディレクトリからモジュールとして実行します。

```powershell
python -m scripts.migrations.migrate_trivia_candidates
python -m scripts.data.import_map_trivia_xlsx --help
python -m scripts.data.seed_data
```

各スクリプトは`migrations`、`data`、`maintenance`に用途別で配置しています。
