from __future__ import annotations

from .commons import Commons
from .image_format import prepare_image, processing_changes, format_signature
from .config import Settings
from .database import Neon, fingerprint
from .harness import Plan, Selection, candidate_snapshot, export_task, instructions_version, task_path, validate
from .licenses import credit_text, non_photo
from .state import State, now
from .storage import R2
from .approval import PhotoReview, matches_rejection, photo_identity, review_token


def safe_error(exc: Exception) -> str:
    # Third-party errors may contain connection details or presigned URLs.
    if isinstance(exc, ValueError):
        return str(exc)[:500]
    message = str(exc).lower()
    for label, markers in (
        ("名前解決に失敗", ("could not translate host name", "name or service not known")),
        ("接続タイムアウト", ("timeout expired", "connection timed out")),
        ("認証に失敗", ("password authentication failed",)),
        ("接続パラメータ非対応", ("unsupported startup parameter",)),
        ("SSL接続エラー", ("ssl error", "ssl syscall", "certificate verify failed")),
    ):
        if any(marker in message for marker in markers):
            return type(exc).__name__ + "（" + label + "）"
    return type(exc).__name__ + "（通信・設定・提供元の状態を確認してください）"


class Workflow:
    def __init__(self, settings: Settings, state: State, neon=None, commons=None, storage=None):
        self.settings, self.state = settings, state
        self.neon = neon or Neon(settings.database_url, table=settings.target_table)
        self.commons = commons or Commons(settings.user_agent, settings.image_max_dimension)
        self.storage = storage

    def r2(self):
        if self.storage is None:
            self.storage = R2(self.settings)
        return self.storage

    def collect(self, limit: int = 5, ids: list[int] | None = None, retry: bool = False, resume: str | None = None) -> dict:
        if not 1 <= limit <= 50:
            raise ValueError("1回の件数は1〜50件にしてください")
        if resume:
            batch = self.state.resolve_batch(resume)
        else:
            excluded = self.state.attempted_ids(retry)
            rows = self.neon.fetch(limit, ids, excluded)
            if not rows:
                return {"message": "対象となる未処理の雑学がありません", "batch": None}
            batch = self.state.create_batch(rows)
        for item in self.state.items(batch):
            if ids and item["trivia_id"] not in ids:
                continue
            if resume and retry and ids and item["status"] in {"staged", "rejected"}:
                self.archive_legacy_rejection(item)
                item.setdefault("selection_history", []).append({key: item.get(key) for key in ("selected", "selection", "staging", "metadata")})
                for key in ("selected", "selection", "candidates", "staging", "asset", "metadata", "credit", "approved_photos", "published_photos", "published_url", "review", "error", "codex_review"):
                    item.pop(key, None)
                self.state.save(item, "planned")
                item["status"] = "planned"
            if retry and item["status"] == "needs_review":
                item.pop("selection", None)
                item.pop("error", None)
                if not item.get("candidates"):
                    item.pop("candidates", None)
                self.state.save(item, "planned")
                item["status"] = "planned"
            # R2だけが失敗した場合は、保存済みの判断を再利用する。
            if "selected" in item and "staging" not in item and item["status"] not in {"approved", "published", "rejected"}:
                try:
                    self.stage_one(item)
                except Exception as exc:
                    item["error"] = safe_error(exc)
                    self.state.save(item, "error")
        self.state.finish(batch, "awaiting_codex")
        for item in self.state.items(batch):
            export_task(self.state, item, self.r2() if item.get("candidates") else None)
        return self.summary(batch)

    def search(self, batch: str, trivia_id: int, plan: dict | None = None, refresh: bool = False) -> dict:
        batch = self.state.resolve_batch(batch)
        item = self.state.get(batch, trivia_id)
        if item["status"] in {"approved", "published"}:
            raise ValueError("承認済み・反映済みの写真は検索し直しません")
        if "selected" in item and not refresh:
            raise ValueError("選定済みです。写真を選び直す場合はsearch --refreshを指定してください")
        new_plan = validate(Plan, plan) if plan is not None else item.get("plan")
        if not new_plan:
            raise ValueError("Codexが作成した検索要件のJSONを--plan-fileで指定してください")
        if refresh or new_plan != item.get("plan"):
            self.archive_legacy_rejection(item)
            if item.get("candidates") or item.get("selected"):
                item.setdefault("selection_history", []).append({key: item.get(key) for key in
                    ("plan", "candidates", "selected", "selection", "staging", "metadata", "codex_review", "review")})
            for key in ("candidates", "selected", "selection", "staging", "asset", "metadata", "credit", "approved_photos", "published_photos", "published_url", "review", "error", "codex_review"):
                item.pop(key, None)
        item["plan"] = new_plan
        item["plan_record"] = {"actor": "codex", "recorded_at": now(), "instructions_version": instructions_version()}
        self.state.save(item, "planned")
        try:
            self.search_one(item)
        except Exception as exc:
            item["error"] = safe_error(exc)
            self.state.save(item, "error")
        return self.task_summary(self.state.get(batch, trivia_id))

    def search_one(self, item: dict) -> None:
        batch, trivia_id = item["batch_id"], item["trivia_id"]
        if "candidates" not in item:
            candidates, seen, download_errors = [], set(), []
            rejected = PhotoReview(self).rejections(trivia_id)
            item["excluded_photos"] = rejected
            searches = [(q, "exact") for q in item["plan"]["exact_queries"]]
            searches += [(q, "reference") for q in item["plan"]["reference_queries"]]
            for query, relationship in searches:
                cap = 2 if relationship == "exact" and item["plan"]["reference_queries"] else 3
                if len(candidates) >= cap:
                    continue
                for candidate in self.commons.search(query):
                    if candidate["page_id"] in seen or matches_rejection(candidate, rejected):
                        continue
                    seen.add(candidate["page_id"])
                    try:
                        prepared = prepare_image(self.commons.download(candidate["download_url"]),
                                                 self.settings.image_max_dimension, self.settings.image_webp_quality)
                    except Exception as exc:
                        download_errors.append(safe_error(exc))
                        if len(download_errors) >= 6:
                            break
                        continue
                    candidate["search_relationship"] = relationship
                    if matches_rejection(dict(candidate, asset=prepared), rejected):
                        continue
                    candidate["asset"] = self.store_asset(batch, trivia_id, prepared)
                    candidates.append(candidate)
                    if len(candidates) >= cap:
                        break
            item["candidates"] = candidates
            item["download_errors"] = download_errors
        item.pop("error", None)
        if not item["candidates"]:
            item["error"] = "対象と利用条件を満たす候補を取得できませんでした。検索語を見直してください"
            self.state.save(item, "needs_review")
        else:
            self.state.save(item, "candidates")

    def select(self, batch: str, trivia_id: int, decision: dict) -> dict:
        batch = self.state.resolve_batch(batch)
        item = self.state.get(batch, trivia_id)
        if item["status"] in {"staged", "approved", "rejected", "published"} or "selected" in item:
            raise ValueError("選定済みです。変更する場合は未承認の対象をsearch --refreshで検索し直してください")
        if "candidates" not in item:
            raise ValueError("先にsearchで候補を取得してください")
        selection = validate(Selection, decision)
        if selection["candidate_snapshot"] != candidate_snapshot(item):
            raise ValueError("候補が変更されています。task.jsonを読み直して写真を確認してください")
        index = selection["candidate_index"]
        if index is None:
            if selection["relationship"] != "unusable" or selection["is_photograph"]:
                raise ValueError("候補がない場合はrelationship=unusable、is_photograph=falseにしてください")
        elif not 0 <= index < len(item["candidates"]):
            raise ValueError("Codexの候補番号が不正です")
        else:
            selected = item["candidates"][index]
            if matches_rejection(selected, PhotoReview(self).rejections(trivia_id)):
                raise ValueError("この雑学で却下済みの写真です。別の候補を選んでください")
            if not selection["is_photograph"] or selection["relationship"] == "unusable":
                raise ValueError("写真として採用できない場合はcandidate_index=nullにしてください")
            if selection["inspected_image_sha256"] != selected["asset"]["sha256"]:
                raise ValueError("実際に確認した表示用画像のSHA-256を指定してください")
            self.asset_bytes(selected["asset"])
            if non_photo(selected["metadata"]):
                raise ValueError("図版・イラストは写真として選定できません")
        record = {"actor": "codex", "recorded_at": now(), "instructions_version": instructions_version(),
                  "candidate_snapshot": selection["candidate_snapshot"], "visual_review": selection["visual_review"],
                  "rights_review": selection["rights_review"], "inspected_image_sha256": selection["inspected_image_sha256"]}
        item.update(selection=selection, codex_review=record)
        item.pop("reselection_request", None)
        if index is None:
            item["error"] = selection["reason"]
            self.state.save(item, "needs_review")
            return self.task_summary(self.state.get(batch, trivia_id))
        metadata = dict(selected["metadata"])
        relationship = "reference" if selected["search_relationship"] == "reference" else selection["relationship"]
        metadata.update(is_reference=relationship == "reference", relationship=relationship,
                        rights_review_required=bool(selection["rights_review_required"] or metadata.get("restrictions")),
                        selection_reason=selection["reason"], codex_review=record,
                        changes=processing_changes(selected["asset"]), display_format=selected["asset"].get("processing"))
        item.update(selected=selected, asset=selected["asset"], metadata=metadata, credit=credit_text(metadata))
        self.state.save(item, "selected")
        try:
            self.stage_one(item)
        except Exception as exc:
            item["error"] = safe_error(exc)
            self.state.save(item, "error")
        return self.task_summary(self.state.get(batch, trivia_id))

    def stage_one(self, item: dict) -> None:
        if "staging" not in item:
            self.asset_bytes(item["asset"])
            item["staging"] = self.r2().confirm_asset(item["asset"])
        item.pop("error", None)
        self.state.save(item, "staged")

    def reformat(self, batch: str, ids: list[int] | None = None) -> list[dict]:
        """Reframe pending photos from local sources without search or AI calls."""
        batch = self.state.resolve_batch(batch)
        results = []
        for item in self.state.items(batch):
            if ids and item["trivia_id"] not in ids:
                continue
            result = {"trivia_id": item["trivia_id"]}
            if item["status"] not in {"staged", "rejected"}:
                results.append(dict(result, status="skipped", reason="未承認の確認用画像だけを調整します"))
                continue
            old_asset = item["asset"]
            if old_asset.get("format_signature") == format_signature(self.settings.image_max_dimension, self.settings.image_webp_quality):
                results.append(dict(result, status="already_formatted"))
                continue
            try:
                self.archive_legacy_rejection(item)
                source = old_asset.get("source", old_asset)
                prepared = prepare_image(self.asset_bytes(source), self.settings.image_max_dimension, self.settings.image_webp_quality)
                asset = self.store_asset(batch, item["trivia_id"], prepared)
                # 元の全体版はR2上のものを再利用する。
                asset["source"] = source
                staging = self.r2().confirm_asset(asset)
                item.setdefault("format_history", []).append({"asset": old_asset, "staging": item["staging"], "metadata": dict(item["metadata"])})
                item.update(asset=asset, staging=staging)
                item["metadata"] = dict(item["metadata"], changes=processing_changes(asset), display_format=asset["processing"])
                item["credit"] = credit_text(item["metadata"])
                item.pop("review", None)
                item.pop("error", None)
                self.state.save(item, "staged")
                result.update(status="formatted", width=asset["width"], height=asset["height"])
            except Exception as exc:
                result.update(status="error", error=safe_error(exc))
            results.append(result)
        return results

    def store_asset(self, batch: str, trivia_id: int, prepared: dict) -> dict:
        source = self.r2().store_asset(batch, trivia_id, prepared["source"], source=True)
        asset = self.r2().store_asset(batch, trivia_id, prepared)
        return dict(asset, source=source)

    def asset_bytes(self, asset: dict) -> bytes:
        return self.r2().read_asset(asset)

    def decision(self, batch: str, trivia_id: int, approve: bool, rights_confirmed: bool = False) -> None:
        item = self.state.get(batch, trivia_id)
        if item["status"] not in {"staged", "approved", "rejected", "held", "reselection_requested"} or "staging" not in item:
            raise ValueError("R2へ保存済みの確認用画像だけを承認・却下できます")
        if approve:
            if item.get("approved_photos"):
                choices = PhotoReview(self).options(item)
                indices = [next((index for index, candidate in enumerate(choices)
                                 if photo_identity(candidate) == photo_identity(photo["selected"], photo["asset"])), -1)
                           for photo in item["approved_photos"]]
                PhotoReview(self).decide(batch, trivia_id, "approved", review_token(item),
                                         rights_confirmed=rights_confirmed, options=indices)
                return
            if matches_rejection(dict(item["selected"], asset=item["asset"]), PhotoReview(self).rejections(trivia_id)):
                raise ValueError("この雑学で却下済みの写真です。別の写真を選んでください")
            self.asset_bytes(item["asset"])
            if item["metadata"].get("rights_review_required") and not rights_confirmed:
                raise ValueError("追加の利用条件を確認し、権利確認済みを指定してください")
        item["review"] = {"decision": "approved" if approve else "rejected", "checked_at": now(), "rights_confirmed": rights_confirmed,
                          "photo": photo_identity(item.get("selected"), item.get("asset"))}
        item.setdefault("review_history", []).append(item["review"])
        self.state.save(item, "approved" if approve else "rejected")

    @staticmethod
    def archive_legacy_rejection(item: dict) -> None:
        if item.get("review", {}).get("decision") == "rejected" and not item.get("review_history"):
            item["review_history"] = [dict(item["review"], photo=photo_identity(item.get("selected"), item.get("asset")))]

    def publish(self, batch: str, ids: list[int] | None = None, apply: bool = False, credits_ready: bool = False) -> list[dict]:
        batch = self.state.resolve_batch(batch)
        items = self.state.items(batch)
        if ids:
            selected = [item for item in items if item["trivia_id"] in ids]
            if len(selected) != len(set(ids)):
                raise ValueError("バッチに存在しない雑学IDが含まれています")
            if any(item["status"] not in {"approved", "published"} for item in selected):
                raise ValueError("未承認の画像は反映できません")
        else:
            selected = [item for item in items if item["status"] in {"approved", "published"}]
        results = []
        for item in selected:
            result = {"trivia_id": item["trivia_id"], "status": "already_published" if item["status"] == "published" else "dry_run"}
            if item["status"] == "published":
                results.append(result)
                continue
            photos = item.get("approved_photos") or [{key: item[key] for key in ("selected", "asset", "staging", "metadata", "credit")}]
            if any(photo["metadata"].get("attribution_required") for photo in photos) and not credits_ready:
                result["status"] = "waiting_for_credit_display"
                results.append(result)
                continue
            if not apply:
                results.append(result)
                continue
            try:
                if not 1 <= len(photos) <= 10:
                    raise ValueError("反映する写真は1〜10枚で指定してください")
                for photo in photos:
                    self.asset_bytes(photo["asset"])
                current = self.neon.current(item["trivia_id"])
                if fingerprint(current) != fingerprint(item["trivia"]):
                    raise ValueError("雑学が変更されています。画像を再確認してください")
                expected_url = item.get("published_url")
                expected_gallery = [photo["url"] for photo in item.get("published_photos", [])]
                if ((current.get("image_url") and current["image_url"].strip() != expected_url)
                        or (current.get("image_urls") and current["image_urls"] != expected_gallery)):
                    raise ValueError("画像URLが既に登録されています。上書きしません")
                for photo in photos:
                    refreshed = self.commons.refresh_metadata(photo["selected"])
                    if non_photo(refreshed):
                        raise ValueError("図版・イラストなどの候補は写真として反映できません")
                    original = photo["selected"]["metadata"]
                    if any(refreshed.get(key) != original.get(key) for key in ("license", "license_url", "author", "attribution", "copyright_notice", "credit_line", "restrictions")):
                        raise ValueError("出典の利用条件が変わっています。再確認してください")
                published = []
                for photo in photos:
                    url = self.r2().publish(dict(item, **photo))
                    published.append(dict(url=url, credit=photo["credit"], metadata=dict(photo["metadata"], review=item["review"])))
                if len({photo["url"] for photo in published}) != len(published):
                    raise ValueError("反映先の写真URLが重複しています")
                url = published[0]["url"]
                item["published_url"] = url
                item["published_photos"] = published
                self.state.save(item, "approved")
                if len(published) == 1:
                    self.neon.publish(item["trivia"], url, published[0]["credit"], published[0]["metadata"])
                else:
                    self.neon.publish_gallery(item["trivia"], published)
                item["published_at"] = now()
                item.pop("error", None)
                self.state.save(item, "published")
                result.update(status="published", url=url, urls=[photo["url"] for photo in published])
            except Exception as exc:
                item["error"] = safe_error(exc)
                self.state.save(item, "approved")
                result.update(status="error", error=item["error"])
            results.append(result)
        return results

    def summary(self, batch: str) -> dict:
        statuses = {}
        for item in self.state.items(batch):
            statuses[item["status"]] = statuses.get(item["status"], 0) + 1
        return {"batch": batch, "statuses": statuses, "executor": "codex", "api_usage_history": self.state.usage(batch),
                "tasks": [self.task_summary(item, export=False) for item in self.state.items(batch)]}

    def task_summary(self, item: dict, export: bool = True) -> dict:
        return {"id": item["trivia_id"], "title": item["trivia"]["title"], "status": item["status"],
                "error": item.get("error"), "task_file": str(export_task(self.state, item, self.r2() if item.get("candidates") else None) if export else task_path(self.state, item))}
