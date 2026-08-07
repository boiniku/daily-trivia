# 毎日雑学の環境分離とリリース手順

## 環境

| 用途 | Gitブランチ | EASプロファイル | API | DB |
|---|---|---|---|---|
| ローカル開発 | 任意 | `development` | ローカルまたはステージング | ローカルまたはステージング |
| Development Build | `develop` | `development` | ステージング | ステージング専用 |
| 内部配布 | `develop` | `preview` | ステージング | ステージング専用 |
| TestFlight | `develop` | `testflight` | ステージング | ステージング専用 |
| App Store | `main` | `production` | 本番 | 本番 |

TestFlight用ビルドをApp Store本番へ昇格させないこと。ステージングURLがバイナリに組み込まれているため、本番提出時は必ず`production`プロファイルで別のビルドを作る。

## 初回セットアップ

1. Neonに本番とは別のステージングブランチを作成する。
2. ステージング用にowner接続とRLS対象app_user接続を用意する。
3. Renderで`daily-trivia-backend-staging`を作成する。
4. `DATABASE_URL`と`APP_DATABASE_URL`へステージングDBのURLだけを設定する。
5. Firebase、OpenAI、R2等のステージング用環境変数を設定する。
6. Renderの実URLが設定値と違う場合、`eas.json`と`PUBLIC_BASE_URL`を実URLへ変更する。
7. `/health`が`{"status":"ok","environment":"staging"}`を返すことを確認する。

本番DBのURLをステージングへコピーしてはいけない。バックエンドは起動時にマイグレーションを実行するため、誤接続すると本番へ影響する。

## 通常のテスト

```sh
npm run typecheck
npm run build:development
```

TestFlightの場合：

```sh
npm run build:testflight
npm run submit:testflight
```

## 本番リリース

安全な順序は「後方互換バックエンドを先に、本番アプリを後に」である。

1. ステージングへバックエンドをデプロイする。
2. Development BuildとTestFlightで旧機能・新機能を確認する。
3. DB変更が追加型で、旧アプリでも動くことを確認する。
4. 本番バックエンドを手動デプロイする。この時点でも旧アプリが動く必要がある。
5. `production`プロファイルで本番API参照のアプリをビルドする。
6. App Storeへ提出する。
7. 新版の利用率とサーバーログを確認する。
8. 旧APIの削除は最低対応バージョンを引き上げた後の別リリースで行う。

## 旧版を壊さないAPIルール

現在配信済みのアプリが使う既存エンドポイントをAPI v1として扱う。

- 既存エンドポイント、JSONフィールド、意味を削除・改名しない。
- 新しいレスポンス項目は追加だけにする。
- 新しいリクエスト項目はoptionalまたは既定値付きにする。
- DB変更は最初にnullable列・新テーブルを追加する。
- 壊す変更が必要なら`/v2/...`を新設し、既存パスを残す。
- 「新構造を追加 → 両対応 → 新アプリ普及 → 旧構造削除」の順に分ける。
- 現在のアプリは更新を後回しにできるため、旧版が残る前提にする。

## 緊急時

- 問題が出たら直前の互換バージョンへロールバックする。
- DBの破壊的変更をバックエンドデプロイと同時に行わない。
- ステージングビルドを本番へ提出しない。
