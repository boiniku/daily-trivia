# 確認用保存を検証する

```powershell
.\.venv\Scripts\python.exe -m trivia_photo verify --batch <batch>
.\.venv\Scripts\python.exe -m trivia_photo list --batch <batch>
```

保存済み写真がr2=verified、image_url_unchanged=trueであることを確認する。
verifyは読み取りのみ。URLが変わっていたら競合として報告し、自動で戻さない。
未保存・要確認はverifyに出ないためlistも見る。
inspect --batch <batch> --id <id>でR2の選定画像をメモリから表示して確認する。
画面の見た目を変更した場合も、画像をファイルへ保存しない。画像・ブラウザツールのメモリ出力を使う。

通常の確認場所は既存の毎日雑学の管理画面 →「管理・編集」→「写真の確認」。
収集回を指定し、おすすめと別候補を比較して採用・理由付き選び直し・保留を行える。
詳細は[統合した確認方法](../approval-design.md)を参照する。独立した写真管理サイトを追加で起動しない。
既存管理画面の採用ボタンは承認保存と本番Neonへの反映まで続けて行う。保留・選び直しはDBを更新しない。選び直しの依頼は`review-queue`で読み、手動のCodex実行で処理する。

レポートdata/<batch>/review.htmlと旧reviewコマンドは補助用途として残す。
HTMLは文字列だけで画像を含まない。画像への署名付きリンクは15分で失効する。

```powershell
.\.venv\Scripts\python.exe -m trivia_photo review --batch <batch> --open
```

起動を依頼された場合はlocalhostだけで起動し、不要な常駐プロセスを残さない。
補助HTMLの承認とCLIのapproveはR2への記録のみ。既存管理画面の自動反映とは区別する。
公開バケット内の確認用フォルダは非公開ではない。NeonへURLを入れないのでアプリに表示されない。
件数とID、参考画像の区別、要確認の理由、確認場所を簡潔に報告する。
本当に画像を開いた場合だけ目視確認済みと伝える。Codexの利用量をPython側で推測しない。


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
