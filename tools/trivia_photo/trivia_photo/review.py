from __future__ import annotations

import html
import json
import secrets
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from filelock import FileLock, Timeout

from .config import ROOT
from .workflow import safe_error

LABELS = {"queued": "待機", "planned": "検索準備済み", "candidates": "候補取得済み", "selected": "選定済み",
          "staged": "確認待ち", "approved": "承認済み", "rejected": "却下", "needs_review": "要確認",
          "error": "エラー", "published": "反映済み"}


def link(url: str, label: str) -> str:
    if urlparse(url or "").scheme not in {"https", "http"}:
        return html.escape(label)
    return f'<a href="{html.escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">{html.escape(label)}</a>'


def render(workflow, batch: str, token: str = "", offline: bool = False) -> str:
    summary = workflow.summary(batch)
    cards = []
    for item in workflow.state.items(batch):
        e = lambda value: html.escape(str(value or ""), quote=True)
        meta = item.get("metadata", {})
        can_review = item["status"] in {"staged", "approved", "rejected"} and "staging" in item
        photo = ""
        if item.get("asset"):
            source = workflow.r2().image_url(item["asset"]) if offline else f"/image/{batch}/{item['trivia_id']}.webp"
            photo = f'<img src="{e(source)}" alt="アプリ表示の写真" loading="lazy"><p class="format-note">アプリと同じ16:9表示</p>'
        else:
            photo = '<div class="no-image">写真を取得できていません</div>'
        rights = ""
        if meta.get("rights_review_required"):
            rights = '<label class="rights"><input type="checkbox" class="rights-check">追加の権利・利用条件を確認済み</label>'
        actions = ""
        if can_review and not offline:
            actions = f'{rights}<div class="actions"><button class="approve" data-decision="approve">この写真を承認</button><button class="reject" data-decision="reject">却下する</button></div>'
        elif offline and can_review:
            actions = '<p class="muted">承認・却下は review コマンドで開く確認画面から行えます。</p>'
        reference = "参考画像" if meta.get("is_reference") else "対象の写真"
        staging = item.get("staging", {})
        original_photo = ""
        if item.get("asset"):
            asset = item["asset"].get("source", item["asset"])
            if asset.get("r2"):
                source_url = workflow.r2().image_url(asset) if offline else f"/source/{batch}/{item['trivia_id']}.webp"
                original_photo = f'<details class="source-detail"><summary>元の写真全体を見る</summary><img class="source-photo" src="{e(source_url)}" alt="切り抜き前の写真" loading="lazy"></details>'
        cards.append(f'''<article class="card" data-id="{item['trivia_id']}">
            <div class="photo">{photo}</div><div class="body">
            <div class="eyebrow">雑学 #{item['trivia_id']} <span class="status {e(item['status'])}">{e(LABELS.get(item['status'], item['status']))}</span></div>
            <h2>{e(item['trivia']['title'])}</h2><p class="content">{e(item['trivia']['content'])}</p>
            <div class="reason"><strong>{reference}</strong><p>{e(meta.get('selection_reason') or item.get('selection', {}).get('reason') or item.get('error'))}</p></div>
            <dl><dt>作者</dt><dd>{e(meta.get('author') or '—')}</dd><dt>利用条件</dt><dd>{link(meta.get('license_url', ''), meta.get('license') or '未確認')}</dd>
            <dt>出典</dt><dd>{link(meta.get('source_url', ''), meta.get('title') or '—')}</dd></dl>
            <p class="credit">{e(item.get('credit'))}</p>
            <details><summary>保存先・追加の利用条件</summary><p class="path">{e(staging.get('bucket'))}/{e(staging.get('key'))}</p><p>{e(meta.get('restrictions') or '追加条件の記録なし')}</p></details>
            {original_photo}{actions}<p class="feedback" aria-live="polite"></p></div></article>''')
    css = (ROOT / "web" / "review.css").read_text(encoding="utf-8")
    css += "\n" + (ROOT / "web" / "app-image.css").read_text(encoding="utf-8")
    script = ""
    if not offline:
        js = (ROOT / "web" / "review.js").read_text(encoding="utf-8")
        script = '<script nonce="' + token + '">const context = ' + json.dumps({"token": token, "batch": batch}) + ';\n' + js + '</script>'
    usage = summary["api_usage_history"]
    history = f"<p class='muted'>旧方式のAPI使用履歴：{usage['tokens']:,}トークン / 概算${usage['estimated_cost_usd']:.4f}</p>" if usage["calls"] else ""
    codex_count = sum(bool(item.get("codex_review")) for item in workflow.state.items(batch))
    return f'''<!doctype html><html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>毎日雑学 · 写真の確認</title><style>{css}</style></head>
    <body><header><span class="brand">毎日雑学 <span>/ PHOTO REVIEW</span></span><span class="environment">確認用 · アプリには未反映</span></header>
    <main><section class="intro"><div><p class="eyebrow">写真を確認してから反映</p><h1>雑学に合う、<br>一枚を選ぶ。</h1><p class="muted">承認してもアプリには反映されません。反映は別の publish コマンドで行います。</p></div>
    <div class="batch"><span class="muted">今回のバッチ</span><code>{html.escape(batch)}</code><div class="metrics"><div><strong>{len(cards)}</strong><span>件</span></div><div><strong>{codex_count}</strong><span>Codex選定</span></div></div>{history}</div></section>
    <section class="grid">{''.join(cards)}</section></main>{script}</body></html>'''


def export_report(workflow, batch: str):
    path = workflow.state.root / batch / "review.html"
    path.write_text(render(workflow, batch, offline=True), encoding="utf-8")
    return path


def serve(workflow, batch: str, port: int = 8765, open_browser: bool = False):
    token = secrets.token_hex(24)

    class Handler(BaseHTTPRequestHandler):
        def allowed_host(self):
            return self.headers.get("Host") in {f"127.0.0.1:{port}", f"localhost:{port}"}

        def respond(self, code, data, content_type="application/json; charset=utf-8"):
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", f"default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; script-src 'nonce-{token}'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self.allowed_host():
                return self.respond(403, b'{}')
            path = urlparse(self.path).path
            try:
                if path == "/":
                    return self.respond(200, render(workflow, batch, token).encode(), "text/html; charset=utf-8")
                parts = path.split("/")
                if len(parts) == 4 and parts[1] in {"image", "source"} and parts[2] == batch:
                    trivia_id = int(parts[3].removesuffix(".webp"))
                    item = workflow.state.get(batch, trivia_id)
                    asset = item["asset"]
                    if parts[1] == "source":
                        asset = asset.get("source", asset)
                    return self.respond(200, workflow.asset_bytes(asset), "image/webp")
                return self.respond(404, b'{}')
            except (ValueError, KeyError, OSError):
                return self.respond(404, b'{}')

        def do_POST(self):
            origin = self.headers.get("Origin")
            if not self.allowed_host() or self.headers.get("X-Trivia-Photo-Token") != token or origin not in {None, f"http://127.0.0.1:{port}", f"http://localhost:{port}"}:
                return self.respond(403, b'{"error":"forbidden"}')
            if urlparse(self.path).path != "/api/decision":
                return self.respond(404, b'{}')
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size < 4096:
                    raise ValueError("入力サイズが不正です")
                data = json.loads(self.rfile.read(size))
                if data.get("decision") not in {"approve", "reject"}:
                    raise ValueError("確認結果が不正です")
                with FileLock(workflow.state.root / "workflow.lock", timeout=0):
                    workflow.decision(batch, int(data["trivia_id"]), data["decision"] == "approve", data.get("rights_confirmed") is True)
                self.respond(200, json.dumps({"message": "承認しました。アプリへの反映はまだ行っていません" if data["decision"] == "approve" else "却下しました"}, ensure_ascii=False).encode())
            except (ValueError, KeyError, Timeout) as exc:
                self.respond(409, json.dumps({"error": safe_error(exc)}, ensure_ascii=False).encode())

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"確認画面: {url}  終了: Ctrl+C", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
