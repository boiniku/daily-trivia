# Neonの画像クレジット欄

`public.trivia`に、NULLを許容する2つのカラムを追加する。既存行の値や`image_url`は変更しない。

| カラム | PostgreSQL型 | 用途 |
| --- | --- | --- |
| `image_credit` | `text` | 表示用のクレジット文。後でアプリのテキスト欄に表示できる |
| `image_credit_metadata` | `jsonb` | 作者・出典・ライセンスのリンク、加工内容、利用条件の確認情報など |

`image_credit`の例：`写真：作者名 / 写真タイトル / CC BY 4.0 / Wikimedia Commons経由。縮小・WebP変換。`

以下は保存形式の例であり、実際の写真や利用許諾の記録ではない。

```json
{
  "schema_version": 1,
  "title": "写真タイトル",
  "author": "作者名",
  "provider": "wikimedia_commons",
  "source_url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
  "license": "CC BY 4.0",
  "license_url": "https://creativecommons.org/licenses/by/4.0/",
  "copyright_notice": null,
  "changes": ["縮小", "WebP変換"],
  "is_reference": true,
  "checked_at": "2026-10-09T00:00:00Z",
  "evidence": {
    "url": "https://commons.wikimedia.org/wiki/File:Example.jpg",
    "license_statement": "取得時に確認したライセンス情報"
  }
}
```

ライセンスによって必要な表示項目は異なるため、作者が指定する追加のクレジット、著作権表示、免責表示なども必要に応じて保存する。HTMLをそのまま表示する前提にはしない。

画像が公開待ちの場合にもクレジットだけ保存できる。画像をアプリへ反映するときは、R2保存成功後に`image_url`と対応するクレジットを同じDBトランザクションで登録する設計にする。

## 手動での構造確認・追加

このプロジェクトのルートで実行する。定期実行は設定しない。

```powershell
python scripts/init_image_credit.py --check
python scripts/init_image_credit.py --apply
```

既定動作は読み取り確認のみ。`--apply`は不足するカラムを1トランザクションで追加し、追加結果を検証する。再実行しても既存カラムを上書きしない。ロック取得に時間がかかる場合は終了する。

接続設定は、`TRIVIA_PHOTO_DATABASE_URL`、このフォルダの`.env`、プロセスの`DATABASE_URL`、既存アプリの`apps/api/.env`の順に探す。`--env-file`で明示した場合はそのファイルのみ使用する。既存ファイルは読むだけで変更しない。

## 後でアプリ側で必要な対応

ユーザーが`毎日雑学`側で以下を実装する。

1. ORMモデルとAPIのレスポンスに2つの欄を追加する。
2. 詳細画面で`image_credit`を表示する。
3. `image_credit_metadata`から出典・ライセンスのリンクなどを表示する。
4. クレジット必須の画像を公開する前に、必要な表示が実際に出ることを確認する。

DBに欄を追加しただけでは、現在のAPIから新しい欄は返らない。既存APIと既存アプリのコードはこの作業では編集しない。
