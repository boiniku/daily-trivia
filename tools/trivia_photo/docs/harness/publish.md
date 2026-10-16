# 確認後のアプリ反映

ユーザーが確認済みの対象を承認し、反映を依頼した場合に実行する。
写真の収集・確認の依頼だけではこの工程へ進まない。具体的なバッチとIDを指定する。

```powershell
.\.venv\Scripts\python.exe -m trivia_photo approve --batch <batch> --ids <id>
.\.venv\Scripts\python.exe -m trivia_photo publish --batch <batch> --ids <id>
```

approveはユーザーの承認を記録する。追加の権利確認が完了した場合のみ--rights-confirmedを使う。
publishの既定はdry-run。waiting_for_credit_displayならクレジット表示が未対応。
ユーザーが表示対応完了を伝えた場合だけ--credits-readyを使う。
反映まで依頼され、承認・権利・表示対応がそろった対象は次で反映する。

```powershell
.\.venv\Scripts\python.exe -m trivia_photo publish --batch <batch> --ids <id> --apply --credits-ready
```

作者表記不要の画像なら--credits-readyを省略できる。
公開R2コピー後、image_url/image_urls/image_sources/image_credit/image_credit_metadataを同時に登録する。管理画面で複数枚を採用した場合はapproved_photosの全写真を反映し、先頭を表紙にする。毎日雑学API側の複数写真・出典列の移行を先に済ませる。
既存画像・本文を上書きしない。競合や出典の条件変更なら止めて報告する。
確認用画像は消さない。DB更新失敗時はコピー済み画像を再利用して再開する。

## 管理画面からの自動反映

2026-10-16以降、毎日雑学の「管理・編集 → 写真の確認」は採用ボタンで本番DBへの反映まで行う。画面を表示するだけでは反映しない。管理画面のDATABASE_URLを明示的に渡し、写真専用のDB環境変数で別環境へ書かない。

失敗した場合は採用済み写真をR2に保持し、「採用済みの写真を本番へ反映」から再試行する。未承認・保留・選び直しは反映しない。CLIのapproveと単独のrender_photo_reviewの既定動作は承認保存のみ。

image_urlには先頭1枚、image_urlsには全写真、image_sourcesには写真別出典を保存する。旧版アプリはimage_url、新版と開発用ビルドはimage_urlsを読む。開発用ビルドも本番API経由で同じ本番DBを使う。


## 通常雑学と雑学MAPの切り替え

2026-10-16の指示により、Mapも候補確認・複数枚承認・本番DBへの自動反映に対応する。
既存管理画面の「管理・編集 → 写真の確認 → 写真の管理対象」で「通常の雑学」または「雑学MAP」を選ぶ。
採用ボタンで、選択中の対象へ全写真と写真別出典を同時に反映する。先頭1枚は旧版用のimage_urlにも残す。
通常雑学はpublic.trivia、Mapはpublic.map_triviaへ保存する。管理画面と同じ本番DBを使う。
Mapの確認画像と履歴はR2_REVIEW_PREFIX/map、公開写真はR2_TRIVIA_IMAGE_PREFIX/auto/mapへ分ける。
同じ数値IDでも対象をまたいだ承認・上書きはしない。通常雑学の既存バッチと公開URLは維持する。

CLIは全コマンド共通で、コマンド名より前に --target map を付ける。省略時は従来どおり通常雑学。
例: .\.venv\Scripts\python.exe -m trivia_photo --target map collect --limit 5
例: .\.venv\Scripts\python.exe -m trivia_photo --target map list --batch latest
例: .\.venv\Scripts\python.exe -m trivia_photo --target map review-queue
収集は引き続き手動で、collectだけでは候補を検索しない。collect.mdに従ってsearch・目視・select・verifyまで進める。
Mapの候補が未収集なら確認画面は空になる。対象を指定して写真収集を依頼する。
Mapのimage_credit/image_credit_metadata列を含む毎日雑学側のmigrate_trivia_images移行を先に適用する。
旧ローカル画像のmigrate-localは通常雑学専用。Mapに流用しない。
