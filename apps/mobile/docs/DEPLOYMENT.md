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

1. Neonに本番とは別のステージングDB（または完全分離したNeonブランチ）を作成する。
2. ステージング用にowner接続とRLS対象app_user接続を用意する。
3. Render Blueprintを同期し、`daily-trivia-backend-staging`を作成する。
4. ステージングサービスの`DATABASE_URL`と`APP_DATABASE_URL`へ、ステージングDBのURLだけを設定する。
5. Firebase、OpenAI、R2等のステージング用環境変数を設定する。R2を共用する場合も`R2_TRIVIA_IMAGE_PREFIX=staging`を維持する。
6. Renderが割り当てたURLが`https://daily-trivia-backend-staging.onrender.com`と違う場合、`eas.json`の3か所とRenderの`PUBLIC_BASE_URL`を実URLへ変更する。
7. `/health`が`{"status":"ok","environment":"staging"}`を返すことを確認する。

本番DBのURLをステージングへコピーしてはいけない。バックエンドは起動時にマイグレーションを実行するため、誤接続すると本番スキーマや本番データへ影響する。

## 通常のテスト

```sh
npm run typecheck
npm run build:development
```

TestFlightで確認する場合：

```sh
npm run build:testflight
npm run submit:testflight
```

TestFlight版は`EXPO_PUBLIC_APP_ENV=staging`で作られ、ステージングAPIを参照する。

## 本番リリース

安全な順序は「後方互換バックエンドを先に、本番アプリを後に」である。

1. ステージングへバックエンドをデプロイする。
2. Development BuildとTestFlightで旧機能・新機能を確認する。
3. DB変更が追加型であり、旧アプリからのリクエストでも動くことを確認する。
4. 本番バックエンドを手動デプロイする。この時点でも旧アプリが動く必要がある。
5. `production`プロファイルで本番API参照のアプリをビルドする。
6. ビルド成果物の接続先を確認してApp Storeへ提出する。
7. 新版の利用率とサーバーログを確認する。
8. 旧APIの削除は、旧版の利用がなくなり、最低対応バージョンを引き上げた後の別リリースで行う。

App Storeで新版が実際にダウンロード可能になったことを確認してから、Render本番サービスの
`LATEST_APP_VERSION`と`MINIMUM_SUPPORTED_APP_VERSION`を新版（今回なら`1.0.39`）へ更新する。
公開前に変更すると、App Storeからまだ取得できない更新を旧版ユーザーへ案内してしまう。
旧版も「あとで」を選んで継続利用できるため、バックエンドの後方互換性は維持する。

```sh
npm run build:production
npm run submit:production
```

## 旧版を壊さないAPIルール

現在配信済みのアプリはパスにバージョンを持たないため、既存エンドポイントをAPI v1として扱う。

- 既存エンドポイント、JSONフィールド、意味を削除・改名しない。
- 新しいレスポンス項目は追加だけにし、旧アプリが無視できる形にする。
- 新しいリクエスト項目はoptionalまたは既定値付きにする。
- DB変更は最初にnullable列・新テーブルを追加する。列の削除や型変更を同じリリースで行わない。
- 挙動を壊す変更が必要なら`/v2/...`を新設し、既存パスを残す。
- データ移行は「新構造を追加 → 両対応 → 新アプリ普及 → 旧構造削除」の順に分ける。
- `MINIMUM_SUPPORTED_APP_VERSION`の引き上げだけを安全策にしない。現在のアプリは更新を後回しにできるため、旧版がしばらく残る前提にする。

アプリは認証付きAPIにアプリバージョン、環境、APIバージョンのヘッダーを送る。サーバーログや将来の互換分岐に利用できる。

## 緊急時

- 本番バックエンドに問題が出たら、まず直前の互換バージョンへロールバックする。
- DBの破壊的変更を同じデプロイで行わない。アプリのロールバックよりDBの巻き戻しの方が難しい。
- 本番API URLをTestFlight用に切り替えて回避しない。
- ステージングビルドを本番へ提出しない。
