# 毎日雑学

モバイルアプリとAPIを1つのリポジトリで管理するモノレポです。

## 構成

```text
.
├─ apps/
│  ├─ api/             FastAPI API・管理画面・データベース処理
│  └─ mobile/          Expo / React Nativeモバイルアプリ
├─ docs/               プロダクト・公開サイト関連ドキュメント
├─ examples/           検証用の独立したサンプル
├─ tools/              診断用・旧運用スクリプト
└─ render.yaml         Renderの本番・ステージング設定
```

## API

```powershell
cd apps/api
python -m venv venv
.\venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload
```

テストはAPIディレクトリで実行します。

```powershell
python -m unittest discover -s tests -v
```

## モバイルアプリ

```powershell
cd apps/mobile
npm install
npm run typecheck
npm start
```

ビルドとリリースの詳細は[`apps/mobile/docs/DEPLOYMENT.md`](apps/mobile/docs/DEPLOYMENT.md)を参照してください。

## 運用上の注意

- 秘密情報はコミットせず、各アプリの`.env.example`をひな形として使います。
- `node_modules`、`venv`、`.expo`、`dist`などは生成物なのでGitでは管理しません。
- Renderは`apps/api`をサービスルートとして起動します。
- `examples`と`tools`は本番アプリの実行には使用しません。
