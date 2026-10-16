from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from filelock import FileLock, Timeout

from .commons import Commons
from .cloud_state import CloudState
from .config import Settings
from .database import Neon
from .harness import read_json
from .inspection import inspect_image
from .review import export_report, serve
from .storage import R2
from .workflow import Workflow, safe_error
from .approval import PhotoReview


def parser():
    app = argparse.ArgumentParser(description="毎日雑学の写真を少量ずつ収集・確認・反映します")
    app.add_argument("--env-file", type=Path)
    app.add_argument("--target", choices=("normal", "map"), default="normal", help="写真の管理対象（通常雑学またはMap）")
    commands = app.add_subparsers(dest="command", required=True)
    collect = commands.add_parser("collect", help="Neonから対象を小分けに取得し、Codex用の作業ファイルを出す")
    collect.add_argument("--limit", type=int)
    collect.add_argument("--ids", type=int, nargs="+")
    collect.add_argument("--retry", action="store_true", help="過去に失敗・却下した対象も検索する")
    collect.add_argument("--resume", help="保存済みバッチを再開。latestも指定可")
    search = commands.add_parser("search", help="Codexが考えた検索語で写真候補を取得。AI APIは使わない")
    search.add_argument("--batch", default="latest")
    search.add_argument("--id", type=int, required=True)
    search.add_argument("--plan-file", type=Path)
    search.add_argument("--refresh", action="store_true", help="未承認の候補を検索し直す。旧記録は残す")
    select = commands.add_parser("select", help="Codexの選定JSONを検証し、R2の確認用フォルダへ保存")
    select.add_argument("--batch", default="latest")
    select.add_argument("--id", type=int, required=True)
    select.add_argument("--selection-file", type=Path, required=True)
    inspect = commands.add_parser("inspect", help="Codex用にR2画像をメモリから表示。ローカル画像保存なし")
    inspect.add_argument("--batch", default="latest")
    inspect.add_argument("--id", type=int, required=True)
    inspect.add_argument("--candidate", type=int)
    inspect.add_argument("--source", action="store_true")
    migrate = commands.add_parser("migrate-local", help="旧ローカル画像・履歴をR2へ移す。Neon更新なし")
    migrate.add_argument("--apply", action="store_true")
    migrate.add_argument("--remove-local-images", action="store_true")
    for name in ("review", "list", "verify", "format", "approve", "reject", "publish"):
        cmd = commands.add_parser(name)
        cmd.add_argument("--batch", default="latest")
        if name in {"format", "approve", "reject", "publish"}:
            cmd.add_argument("--ids", type=int, nargs="+", required=name in {"approve", "reject"})
        if name == "approve":
            cmd.add_argument("--rights-confirmed", action="store_true")
        if name == "review":
            cmd.add_argument("--port", type=int, default=8765)
            cmd.add_argument("--open", action="store_true")
        if name == "publish":
            cmd.add_argument("--apply", action="store_true", help="承認済み画像を公開R2へコピーし、Neonへ登録")
            cmd.add_argument("--credits-ready", action="store_true", help="アプリのクレジット表示対応が完了している場合のみ指定")
    commands.add_parser("doctor", help="Neon・R2・画像検索の接続を読み取り確認。AI呼び出しなし")
    queue = commands.add_parser("review-queue", help="管理画面からの選び直し依頼を読む。検索やAI API呼び出しなし")
    queue.add_argument("--batch", help="省略時は全バッチ")
    return app


def main(argv=None):
    if not sys.stdout.isatty():
        sys.stdout.reconfigure(encoding="utf-8")
    args = parser().parse_args(argv)
    try:
        settings = Settings.load(args.env_file).for_target(args.target)
        if args.target == "map" and args.command == "migrate-local":
            raise ValueError("旧ローカル画像の移行は通常雑学のみ対応しています")
        storage = R2(settings)
        state = CloudState(storage, settings.data_dir)
        if args.command == "doctor":
            settings.require("database_url", "endpoint", "access_key", "secret_key", "bucket", "review_bucket")
            rows = Neon(settings.database_url, table=settings.target_table).fetch(1, None, [])
            for bucket in set((settings.bucket, settings.review_bucket)):
                storage.client.head_bucket(Bucket=bucket)
            candidates = Commons(settings.user_agent).search("American beaver", limit=2)
            result = {"neon": "ok", "missing_image_sample_id": rows[0]["id"] if rows else None,
                      "r2": "ok", "commons": "ok", "commons_candidates": len(candidates),
                      "review_bucket_is_separate": settings.review_bucket != settings.bucket,
                      "review_prefix": settings.review_prefix, "executor": "codex", "ai_api": "unused"}
        else:
            workflow = Workflow(settings, state, storage=storage)
            if args.command == "inspect":
                print(json.dumps(inspect_image(workflow, args.batch, args.id, args.candidate, args.source)))
                return 0
            if args.command == "migrate-local":
                from .migration import migrate_local
                with FileLock(state.root / "workflow.lock", timeout=0):
                    result = migrate_local(workflow, args.apply, args.remove_local_images)
                print(json.dumps(result, ensure_ascii=False, indent=2))
                return 0
            if args.command == "review":
                serve(workflow, state.resolve_batch(args.batch), args.port, args.open)
                return 0
            if args.command == "verify":
                batch = state.resolve_batch(args.batch)
                results = []
                for item in state.items(batch):
                    if "staging" not in item:
                        continue
                    location, asset = item["staging"], item["asset"]
                    head = workflow.r2().head(location["bucket"], location["key"])
                    if head is None:
                        raise ValueError("確認用のR2画像が見つかりません")
                    workflow.r2().check_object(head, asset["sha256"], asset["size"])
                    current = workflow.neon.current(item["trivia_id"])
                    results.append({"trivia_id": item["trivia_id"], "r2": "verified",
                                    "image_url_unchanged": current.get("image_url") == item["trivia"].get("image_url"),
                                    "status": item["status"]})
                result = {"batch": batch, "items": results}
            elif args.command == "review-queue":
                result = {"requests": PhotoReview(workflow).queue(args.batch)}
            elif args.command == "list":
                batch = state.resolve_batch(args.batch)
                result = {**workflow.summary(batch), "items": [{"id": item["trivia_id"], "title": item["trivia"]["title"],
                          "status": item["status"], "error": item.get("error")} for item in state.items(batch)]}
            else:
                with FileLock(state.root / "workflow.lock", timeout=0):
                    if args.command == "collect":
                        settings.require("database_url")
                        result = workflow.collect(args.limit if args.limit is not None else settings.batch_size, args.ids, args.retry, args.resume)
                        if result.get("batch"):
                            result["report"] = str(export_report(workflow, result["batch"]))
                    elif args.command == "search":
                        result = workflow.search(args.batch, args.id, read_json(args.plan_file) if args.plan_file else None, args.refresh)
                    elif args.command == "select":
                        result = workflow.select(args.batch, args.id, read_json(args.selection_file))
                        result["report"] = str(export_report(workflow, state.resolve_batch(args.batch)))
                    elif args.command == "format":
                        result = workflow.reformat(args.batch, args.ids)
                        export_report(workflow, state.resolve_batch(args.batch))
                    elif args.command in {"approve", "reject"}:
                        batch = state.resolve_batch(args.batch)
                        for trivia_id in args.ids:
                            workflow.decision(batch, trivia_id, args.command == "approve", getattr(args, "rights_confirmed", False))
                        export_report(workflow, batch)
                        result = workflow.summary(batch)
                    elif args.command == "publish":
                        result = workflow.publish(args.batch, args.ids, args.apply, args.credits_ready)
                        export_report(workflow, state.resolve_batch(args.batch))
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if args.command in {"publish", "format"} and any(row["status"] == "error" for row in result):
            return 1
        if args.command == "collect" and result.get("statuses", {}).get("error"):
            return 1
        if args.command in {"search", "select"} and result.get("status") == "error":
            return 1
        return 0
    except Timeout:
        print("別の収集・承認・反映処理が実行中です。終了後に再実行してください")
        return 1
    except Exception as exc:
        print(json.dumps({"error": safe_error(exc)}, ensure_ascii=False))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
