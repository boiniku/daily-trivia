# Codex Harnessへの変更と検証

2026-10-09、ユーザーが求めた方式に合わせ、判断を別のAI APIへ渡す実装から、
このフォルダのCodex自身が手順書とローカルツールを使って進める構成へ変更した。

## 参考にした既存の方式

- ../trivia_usagi/AGENTS.md：入口から工程別手順書へ案内する。
- ../trivia_usagi/.claude/commands/images.md：AIが検索語と素材を判断し、Pythonが取得と出所記録を担当する。
- ../trivia_usagi/.claude/commands/photo.md：成果物を実際に開いて確認する。
- ../auto_trivia_collection/AGENTS.md：手順と検証条件をリポジトリに残して、Codexが順に実行する。

これらのフォルダは読み取りだけ。動画制作側のコミット・push・工程ごとの停止など、
今回の手動写真収集に不要な運用は持ち込まない。

## 構成

AGENTS.md → docs/harness/collect.md → select.md → review.md。
アプリ反映を依頼されたときだけpublish.mdを読む。

collectはNeonのSELECTと作業JSON出力のみ。searchはCodexが作成した検索要件で候補取得・加工。
Codexは写真を画像表示ツールで開いて、内容との関係と利用条件を判断する。
selectは判断JSON・候補一覧の版・画像ハッシュを検証して確認用R2へ保存する。
追加のOpenAI API呼び出し、APIキー・モデル・単価・予算設定、OpenAI SDK依存を取り除いた。
Codexセッション自体の利用量はPythonから計測・推測しない。

候補一覧は必要な情報だけを表示し、元の利用条件メタデータのHTMLは別ファイルへ保存する。
目視・権利確認の内容、選定理由、手順書の版、画像ハッシュはローカル状態と画像メタデータへ残す。
旧バッチ・承認状態・旧API方式の使用履歴は保持する。

## 実データでの検証

- 新規バッチ：20261009T123659Z-09a6962876
- 対象：雑学ID 4「パンダの指は6本」
- 本文の真偽確認：未実施。確認済みの入力として使用。
- Codexが検索要件を作成し、Commonsから候補3枚を取得。
- Codexが加工後の3枚を実際に開いた。竹を持って食べるパンダを選び、頭骨と枝で隠れたパンダは不採用。
- 採用画像：[Pandas eating Bamboo - panoramio.jpg](https://commons.wikimedia.org/wiki/File:Pandas_eating_Bamboo_-_panoramio.jpg)
- 作者Raki_Man、CC BY 3.0。出典本文と[ライセンス本文](https://creativecommons.org/licenses/by/3.0/)を実際に開いて、商用利用・加工・表示条件を確認して記録。
- 保存形式：1200×675px、WebP、132,330バイト。アプリと同じ16:9の中央切り取り。
- R2キー：trivia-photo-review/20261009T123659Z-09a6962876/4-5097de8d92056fa3deb0.webp
- 新規バッチの追加AI API使用：0回。
- verify：r2=verified、image_url_unchanged=true、staged。
- approve・公開コピー・NeonのURL更新は未実施。
- 確認画面を非表示のEdgeで撮影し、data/harness-review.pngを実際に開いて確認。

以前のバッチ20261009T100825Z-e2049105f6のID 1/2/3もverifyで確認。
3件ともR2保存済み、画像URL未変更、確認待ちの状態を保持している。
毎日雑学のgit statusは実装前からある変更のままで、この作業ではアプリコードを変更していない。

## 自動検証

53テスト成功。対象取得と候補取得に外部書き込みが無いこと、承認済みの選び直し防止、
古い候補一覧・改変画像・不正な判断JSONの拒否、参考写真の格上げ防止、
R2失敗後の選定結果再利用、旧履歴保持、承認と反映の分離、Neon競合検知、
ライセンス制限、16:9加工、確認サーバーの保護を確認した。

```powershell
.\.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests -v
```
