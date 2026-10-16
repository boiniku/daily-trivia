"""旧画像・履歴をR2へ移す。検証前にローカル画像を消さない。"""
from __future__ import annotations

import copy
import hashlib
from pathlib import Path

from .image_format import prepare_image
from .state import State


def migrate_local(workflow, apply: bool = False, remove_images: bool = False) -> dict:
    root = workflow.state.root
    if not (root / "state.sqlite3").is_file():
        return {"message": "旧ローカル状態DBはありません", "batches": []}
    legacy = State(root)
    with legacy.connect() as db:
        batches = [dict(row) for row in db.execute("SELECT * FROM batches ORDER BY created_at")]
    result = {"apply": apply, "batches": [], "removed_local_images": 0}
    if not apply:
        result["batches"] = [{"batch": row["id"], "items": len(legacy.items(row["id"]))} for row in batches]
        return result
    storage, cloud = workflow.r2(), workflow.state
    remote_cache, prepared_cache, verified_local_files = {}, {}, set()

    def convert(value, batch, trivia_id, download_url=None, required=False):
        if isinstance(value, list):
            return [convert(entry, batch, trivia_id, download_url) for entry in value]
        if not isinstance(value, dict):
            return value
        download_url = value.get("download_url", download_url)
        if "sha256" in value and "size" in value and ("path" in value or "r2" in value):
            asset = {k: v for k, v in value.items() if k not in {"path", "source"}}
            cache_key = (batch, trivia_id, value["sha256"])
            location = value.get("r2") or remote_cache.get(cache_key)
            if location:
                storage.read_asset(dict(asset, r2=location))
            else:
                # 以前の確認用キーがあればそのまま使い、重複アップロードしない。
                old_location = {"bucket": storage.settings.review_bucket,
                                "key": f"{storage.settings.review_prefix}/{batch}/{trivia_id}-{asset['sha256'][:20]}.webp"}
                head = storage.head(old_location["bucket"], old_location["key"])
                if head:
                    storage.read_asset(dict(asset, r2=old_location))
                    location = old_location
                else:
                    data = None
                    path = Path(value["path"]).resolve() if value.get("path") else None
                    if path and path.is_relative_to(root) and path.is_file():
                        data = path.read_bytes()
                    elif required and download_url:
                        if download_url not in prepared_cache:
                            prepared_cache[download_url] = prepare_image(workflow.commons.download(download_url),
                                workflow.settings.image_max_dimension, workflow.settings.image_webp_quality)
                        prepared = prepared_cache[download_url]
                        for variant in (prepared, prepared["source"]):
                            if variant["sha256"] == asset["sha256"]:
                                data = variant["data"]
                                break
                    if data is not None:
                        if hashlib.sha256(data).hexdigest() != asset["sha256"] or len(data) != asset["size"]:
                            raise ValueError("旧ローカル画像が変更されています。削除せずに確認してください")
                        location = storage.store_asset(batch, trivia_id, dict(asset, data=data))["r2"]
                        storage.read_asset(dict(asset, r2=location))
                        if path and path.is_file():
                            verified_local_files.add(path)
            if location:
                remote_cache[cache_key] = location
                asset.update(r2=location)
                asset.pop("missing", None)
                if value.get("path"):
                    old_path = Path(value["path"]).resolve()
                    if old_path.is_relative_to(root) and old_path.is_file():
                        if hashlib.sha256(old_path.read_bytes()).hexdigest() != asset["sha256"]:
                            raise ValueError("旧ローカル画像が変更されています。削除しません")
                        verified_local_files.add(old_path)
            elif required:
                raise ValueError("必要な旧画像を復旧できません。移行前の記録は変更しません")
            else:
                asset["missing"] = True
            if "source" in value:
                # 全体版が既に消えている場合は出典から同じハッシュの画像だけを復旧する。
                asset["source"] = convert(value["source"], batch, trivia_id, download_url, required=required)
            return asset
        return {key: convert(entry, batch, trivia_id, download_url, required=required and key in {"asset", "source"})
                for key, entry in value.items() if key != "_revision"}

    for row in batches:
        batch = row["id"]
        existing, _ = storage.get_json(cloud.key(batch))
        if existing:
            result["batches"].append({"batch": batch, "status": "already_migrated"})
            continue
        items = {}
        for item in legacy.items(batch):
            print(f"移行: {batch} / 雑学 {item['trivia_id']}", flush=True)
            original = copy.deepcopy(item)
            download_url = item.get("selected", {}).get("download_url")
            converted = convert(item, batch, item["trivia_id"], download_url)
            if item.get("asset"):
                converted["asset"] = convert(item["asset"], batch, item["trivia_id"], download_url, required=True)
                converted["staging"] = dict(converted["asset"]["r2"])
            converted.pop("batch_id", None)
            converted.pop("trivia_id", None)
            # 選定済みの全体版を候補・選定記録にも共有し、欠損候補は再検索に回す。
            if converted.get("asset"):
                chosen_sha = original["asset"]["sha256"]
                for candidate in converted.get("candidates", []):
                    if candidate["asset"]["sha256"] == chosen_sha:
                        candidate["asset"] = copy.deepcopy(converted["asset"])
            items[str(item["trivia_id"])] = converted
        document = dict(row, items=items, api_usage_history=legacy.usage(batch), storage_version=2)
        storage.put_json(cloud.key(batch), document)
        check, _ = storage.get_json(cloud.key(batch))
        if check != document:
            raise ValueError("R2の作業記録を検証できません。ローカル画像は削除しません")
        result["batches"].append({"batch": batch, "status": "migrated", "items": len(items)})
    if remove_images:
        for path in verified_local_files:
            resolved = path.resolve()
            if not resolved.is_relative_to(root):
                raise ValueError("削除対象が作業フォルダの外にあります")
            resolved.unlink()
            result["removed_local_images"] += 1
    return result
