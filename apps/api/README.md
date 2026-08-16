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

## 運用スクリプト

APIディレクトリからモジュールとして実行します。

```powershell
python -m scripts.migrations.migrate_trivia_candidates
python -m scripts.data.import_map_trivia_xlsx --help
python -m scripts.data.seed_data
```

各スクリプトは`migrations`、`data`、`maintenance`に用途別で配置しています。
