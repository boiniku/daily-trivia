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
