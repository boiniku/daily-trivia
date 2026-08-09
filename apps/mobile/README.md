# 毎日雑学アプリ

Expo Router、React Native、TypeScriptで実装したiOS/Androidアプリです。APIは`apps/api`にあります。

## ディレクトリ構成

```text
apps/mobile/
├─ app/          Expo Routerの画面とルート
├─ assets/       画像とフォント
├─ components/   再利用するUI
├─ constants/    環境設定、色、レイアウト
├─ contexts/     認証と課金のReact Context
├─ data/         アプリ内の静的データ
├─ docs/         運用・規約ドキュメント
├─ managers/     位置情報、通知、解放処理
├─ models/       TypeScriptのデータ型
├─ modules/      Expoネイティブモジュール
├─ plugins/      Expo config plugin
├─ scripts/      ビルド補助・診断スクリプト
├─ targets/      iOSウィジェットターゲット
├─ tasks/        バックグラウンドタスク
└─ utils/        APIやウィジェット等の共通処理
```

Expo Routerでは`app/`自体がルーティング定義なので、一般的な`src/`配下へ移動させずルートに維持します。`modules/`と`targets/`もネイティブビルドがパスを参照するため移動しません。

## 開発

```sh
npm install
npm run typecheck
npm start
```

実機からローカルAPIを使う場合は`.env.example`を`.env.local`へコピーし、`EXPO_PUBLIC_BACKEND_URL`をPCのLAN IPへ変更します。

## ビルド環境

- `npm run build:development`: ステージングAPIを使うDevelopment Build
- `npm run build:preview`: ステージングAPIを使う内部配布版
- `npm run build:testflight`: ステージングAPIを使うTestFlight版
- `npm run build:production`: 本番APIを使うApp Store版

本番リリースと旧アプリ互換性の手順は[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)を参照してください。

## 補助スクリプト

- `npm run check:r2-themes`: 公開済みウィジェット画像を確認
- `npm run generate:widget-mocks`: ウィジェットのモック画像を再生成
