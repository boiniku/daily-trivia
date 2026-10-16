# 毎日雑学の環境分離とリリース手順

## 環境

| 用途 | Gitブランチ | EASプロファイル | API | DB |
|---|---|---|---|---|
| ローカル開発 | 任意 | `development` | 本番 | 本番 |
| Development Build | `develop` | `development` | 本番 | 本番 |
| 内部配布 | `develop` | `preview` | 本番 | 本番 |
| TestFlight | `develop` | `testflight` | 本番 | 本番 |
| App Store | `main` | `production` | 本番 | 本番 |

2026-10-16のユーザー指定により、アプリの全ビルドは本番API経由で同じ本番DBを参照する。
ビルド種別、広告・課金の開発フラグ、EASの更新チャンネルは引き続き分ける。
App Store提出は`production`プロファイルで作成する。

## 接続と画像の承認

- `eas.json`のdevelopment・preview・testflight・productionは本番APIを明示指定する。
- ローカルのExpoも`.env.development.local`の本番APIを使う。接続先を未設定にした開発環境だけlocalhostへフォールバックする。
- 管理画面の「管理・編集 → 写真の確認」で採用すると、その管理画面の本番DBへ写真と出典を保存する。
- `image_url`は先頭1枚、`image_urls`は全写真、`image_sources`は写真別の出典。旧版は1枚、新版は全写真を読む。
- DB反映に失敗したら採用を保持し、画面の「採用済みの写真を本番へ反映」から再試行する。
- 本番APIにも複数写真のレスポンス対応が必要。DBに列を作るだけでは旧APIから全写真を取得できない。

RenderのステージングサービスとテストDBは、サーバー移行・互換性検証用として残す。
開発アプリが本番データを使うために、ステージングサービスのDB接続設定を変更する必要はない。

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

TestFlight版は`EXPO_PUBLIC_APP_ENV=staging`で作られるが、データは本番API経由で本番DBを参照する。

## 本番リリース

安全な順序は「後方互換バックエンドを先に、本番アプリを後に」である。

1. バックエンドの移行と旧版互換性をテストDBで検証する。
2. 本番API更新後、Development BuildとTestFlightでも同じ本番データを使って確認する。
3. DB変更が追加型であり、旧アプリからのリクエストでも動くことを確認する。
4. 本番バックエンドを手動デプロイする。この時点でも旧アプリが動く必要がある。
5. `production`プロファイルで本番API参照のアプリをビルドする。
6. ビルド成果物の接続先を確認してApp Storeへ提出する。
7. 新版の利用率とサーバーログを確認する。
8. 旧APIの削除は、旧版の利用がなくなり、最低対応バージョンを引き上げた後の別リリースで行う。

App Storeで新版が実際にダウンロード可能になったことを確認してから、Render本番サービスの
`LATEST_APP_VERSION`を新版（今回なら`1.1.1`）へ更新する。
公開前に変更すると、App Storeからまだ取得できない更新を旧版ユーザーへ案内してしまう。
旧版も「あとで」を選んで継続利用できるため、バックエンドの後方互換性は維持する。
`MINIMUM_SUPPORTED_APP_VERSION`は今回`1.0.5`のままにする。現状の画面は強制更新ではなく
更新案内なので、この値だけを上げても旧版を安全に停止できるわけではない。

```sh
npm run build:production
npm run submit:production
```

### GitHub Actionsで半自動実行

`main`へマージした後、GitHubのActionsから`Production release 1.1.1`を手動実行する。
各回の`version`は`1.1.1`、`confirmation`は`RELEASE-1.1.1`と入力する。

1. `deploy-backend`: Render本番サービスを旧`backend/`構成から`apps/api/`構成へ更新し、自動デプロイをOFFにして、指定コミットをデプロイする。`/health`が同じコミットを返すまで待つ。
2. `build-and-upload-ios`: 本番APIが同じコミットであることを再確認し、EAS本番ビルドをApp Store Connectへ送る。
3. App Store Connectでビルドを選択し、審査へ提出する。リリース方法は「手動」または段階的リリースを選ぶ。
4. Appleで1.1.1が公開された後、`enable-update-prompt`を実行する。Apple公開APIが1.1.1を返さない間は自動停止する。

GitHubリポジトリには次を一度だけ設定する。

- Secret `RENDER_API_KEY`: Render APIキー
- Secret `RENDER_PRODUCTION_SERVICE_ID`: 本番Web ServiceのID（`srv-...`）
- Secret `EXPO_TOKEN`: Expoのアクセストークン
- Environment `production-render`, `app-store-connect`, `production-update-prompt`: Required reviewersに承認者を設定

このワークフローはApp Storeでの一般公開や審査提出そのものを勝手に行わない。
EASはビルドをApp Store Connectへアップロードするところまでで止まり、公開後の更新案内も別承認になっている。

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

## APIだけの本番更新

`deploy-production-api.yml`はmainのAPIをRenderへ手動反映し、同じコミットでのヘルスチェックまで確認する。アプリ版数に依存せず、App Storeビルドや提出は実行しない。

```powershell
gh workflow run deploy-production-api.yml --ref main
```
