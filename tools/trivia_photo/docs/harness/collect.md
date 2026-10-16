# 写真を集める

判断はこのセッションのCodexが担当する。追加のOpenAI APIキーは不要。
「次の5件の写真を集めて」の依頼では、以下を確認用R2保存と検証まで進める。
途中の工程ごとに許可を求める必要はない。ユーザー承認とアプリ反映は別工程。

## 1. 作業単位を用意する

AGENTS.mdを確認する。既定5件、指定があればその件数を使う。
本文は確認済みとして扱い、真偽確認・裏取り・修正をしない。
新規なら次を実行する。初回は必要に応じてdoctorで接続を確認する。

```powershell
.\.venv\Scripts\python.exe -m trivia_photo collect --limit 5
```

続きの依頼では新規を作らず、`collect --resume <batch>`を使う。
既存の承認済み・反映済み・確認待ちを勝手に検索し直さない。
出力のバッチIDを記録し、以降latestではなくその具体的IDを指定する。
対象・作業履歴の正本はR2。ローカルの作業JSONは消してもcollect --resumeで再生成できる。

## 2. 主題と検索語を考える

出力のtasks[].task_fileを読み、title/content/explanationを理解する。
prompts/plan.txtを読んで、Codex自身が検索要件を考え、task.jsonのplan_fileへJSONを作る。
同じ主題の要件・候補が保存済みなら再利用する。
選び直しの場合は`review-queue`の理由・補足とtask.jsonのreselection_requestを検索要件へ反映する。
却下済み写真はPython側でページID・出典URL・画像ハッシュを照合して除外する。無理に再採用しない。

```json
{
  "subject": "1948年のアイダホ州のビーバー移送",
  "exact_queries": ["Idaho beaver parachute 1948", "beaver relocation Idaho"],
  "reference_queries": ["Castor canadensis"],
  "required_features": "当時の移送の記録写真を優先。なければアメリカビーバーの実写写真",
  "avoid": "別の動物、図版、生成画像、現在の写真を当時の記録と誤認させる説明"
}
```

検索語は短い英語1〜2個、意味のある参考写真の語を最大1個。URLや許諾を創作しない。
一般的な動植物の性質ならその外観で十分で、本文の主張を写真で証明する必要はない。

## 3. Pythonで候補を取得する

```powershell
.\.venv\Scripts\python.exe -m trivia_photo search --batch <batch> --id <id> --plan-file <plan.json>
```

Commons検索・ダウンロード・ライセンス機械検査・16:9加工をメモリ上で行い、最大3候補と全体版を確認用R2へ保存する。
ローカルに画像を保存せず、Neonにも書き込まない。出力のtask_fileを読み直す。
候補が無い、または合わない場合は要件を見直して同じコマンドに--refreshを付ける。
通常は2回まで見直す。適切な写真が無ければ要確認と理由を残して次へ進む。

## 4. Codexが写真を見て選ぶ

**[select.md](select.md)を読んで実行する。**
inspectで各候補をR2からメモリへ読み、画像として実際に表示する。表示できなければ選定を完了としない。
実写、主題、表示範囲、出典の利用条件を判断し、選定JSONをselection_fileへ作る。

```powershell
.\.venv\Scripts\python.exe -m trivia_photo select --batch <batch> --id <id> --selection-file <selection.json>
```

Pythonが候補一覧の版とR2画像のハッシュを検証し、選定記録をR2へ保存する。画像は検索時に保存したものを再利用する。
R2だけの失敗ならcollect --resume <batch>で選定結果を再利用できる。
適切な候補が無い場合もselectのunusable形式で判断を記録する。

## 5. 保存結果を確認して提示する

**[review.md](review.md)を読んで、verifyと実物の確認まで実行する。**
件数、参考画像の区別、要確認の理由、R2確認用キー、確認場所をユーザーに提示する。
ここまでが収集依頼の範囲。勝手にapproveやpublishを実行しない。

## 再開

queued/plannedは検索要件作成とsearch、candidatesは目視とselect、
selected/errorで選定保存済みならR2保存の再開、stagedはユーザー確認待ち。
needs_reviewは理由を読み、依頼があれば検索語を直してsearch --refreshする。
rejected/reselection_requestedは、選び直しの依頼時に`review-queue`で理由を読み、元のバッチでsearch --refreshする。
heldは保留。選び直しの依頼がなければ触らない。画面操作だけでCodexやAI APIを起動しない。
同じ候補を読み直すだけのsearchでは追加取得は発生しない。


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
