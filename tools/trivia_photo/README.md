# 写真の収集・確認・反映ツール

管理画面の「管理・編集 → 写真の確認」は、このリポジトリ内の実装を読み込みます。
別フォルダのチェックアウトを配置する必要はありません。`TRIVIA_PHOTO_ROOT`を明示した場合だけ、その配置を優先します。

通常雑学と雑学MAPを切り替え、候補から最大10枚を選択できます。管理画面の採用ボタンは、承認記録をR2に保存した後、同じ管理画面の本番DBへ写真と写真別出典を反映します。通常雑学は`trivia`、Mapは`map_trivia`です。先頭1枚を旧版向け`image_url`に、全写真を`image_urls`に保存します。

MapのR2確認履歴・公開画像は別プレフィックスです。同じ数値IDでも通常雑学へ書き込みません。画面を開くだけでは公開せず、失敗時は採用を保持して反映を再試行できます。

## セットアップ

リポジトリ直下で、管理画面と同じPython環境に依存ライブラリをインストールします。

```powershell
python -m pip install -r apps/api/requirements.txt -r tools/trivia_photo/requirements.txt
```

接続設定は`apps/api/.env`またはプロセス環境から読み込みます。管理画面からの反映先DBは、その管理画面の`DATABASE_URL`に固定します。接続情報・画像・作業履歴はGitへ登録しません。

収集は手動です。このフォルダの[AGENTS.md](AGENTS.md)と[収集手順](docs/harness/collect.md)に従います。CLIはこのフォルダから実行します。通常雑学は`--target`省略、Mapはコマンド名より前に`--target map`を付けます。

```powershell
python -m trivia_photo --target map collect --limit 5
python -m trivia_photo --target map list --batch latest
```

`collect`だけでは写真選定は完了しません。検索・画像の目視・選定・検証を行い、管理画面でユーザーが承認します。候補が未収集の場合、確認一覧は空です。定期収集は行いません。
