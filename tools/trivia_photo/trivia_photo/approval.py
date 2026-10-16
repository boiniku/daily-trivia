"""管理画面とCodexで共有する写真の判断。画像・履歴はR2が正本。"""
from __future__ import annotations

from .harness import digest
from .image_format import format_signature, processing_changes
from .licenses import credit_text, licensed_metadata, non_photo
from .state import now


def review_token(item: dict) -> str:
    # 候補だけでなく、保留・却下・再加工などの変更も検出する。
    return digest({k: v for k, v in item.items() if k != "_revision"})


def photo_identity(candidate: dict | None, asset: dict | None = None) -> dict:
    candidate = candidate or {}
    asset = asset or candidate.get("asset", {})
    return {"page_id": candidate.get("page_id"),
            "source_url": candidate.get("metadata", {}).get("source_url"),
            "sha256": asset.get("sha256"),
            "source_sha256": asset.get("source", {}).get("sha256")}


def matches_rejection(candidate: dict, records: list[dict]) -> bool:
    identity = photo_identity(candidate)
    for record in records:
        old = record.get("photo", {})
        if any(identity.get(k) and identity[k] == old.get(k) for k in ("page_id", "source_url")):
            return True
        hashes = {identity.get("sha256"), identity.get("source_sha256")} - {None, ""}
        if hashes & ({old.get("sha256"), old.get("source_sha256")} - {None, ""}):
            return True
    return False


class PhotoReview:
    def __init__(self, workflow):
        self.workflow = workflow
        self.state = workflow.state

    def rejections(self, trivia_id: int) -> list[dict]:
        # バッチを作り直した場合や旧版で却下した場合も除外対象になる。
        if hasattr(self.state, "batch_ids"):
            batches = self.state.batch_ids()
        else:  # 移行用SQLiteとテスト互換。実運用はCloudState。
            with self.state.connect() as db:
                batches = [row[0] for row in db.execute("SELECT id FROM batches")]
        result = []
        for batch in batches:
            for item in self.state.items(batch):
                if item["trivia_id"] != trivia_id:
                    continue
                records = [r for r in item.get("review_history", []) if r["decision"] in {"rejected", "reselection_requested"}]
                review = item.get("review", {})
                if not records and review.get("decision") == "rejected":
                    records = [dict(review, photo=photo_identity(item.get("selected"), item.get("asset")))]
                result.extend(dict(r, batch=batch) for r in records)
        return result

    def queue(self, batch: str | None = None) -> list[dict]:
        batches = [self.state.resolve_batch(batch)] if batch else self.state.batch_ids()
        return [{"batch": b, "id": item["trivia_id"], "title": item["trivia"]["title"],
                 "request": item.get("reselection_request", item.get("review", {}))}
                for b in batches for item in self.state.items(b)
                if item["status"] in {"reselection_requested", "rejected"}]

    def options(self, item: dict) -> list[dict]:
        result = []
        # 再加工された推薦画像を優先。古い候補の加工版と混同しない。
        if item.get("selected") and item.get("asset"):
            result.append(dict(item["selected"], asset=item["asset"], recommended=True))
        identities = {digest(photo_identity(c)) for c in result}
        signature = format_signature(self.workflow.settings.image_max_dimension, self.workflow.settings.image_webp_quality)
        for candidate in item.get("candidates", []):
            identity = digest(photo_identity(candidate))
            asset = candidate.get("asset", {})
            if identity not in identities and asset.get("r2") and not asset.get("missing") and asset.get("format_signature") == signature:
                result.append(dict(candidate, recommended=False))
                identities.add(identity)
            if len(result) == 3:
                break
        return result

    def decide(self, batch: str, trivia_id: int, action: str, token: str,
               option: int = 0, reason: str = "", rights_confirmed: bool = False,
               options: list[int] | None = None) -> None:
        item = self.state.get(batch, trivia_id)
        if token != review_token(item):
            raise ValueError("画面を開いた後に変更されています。読み直して写真を確認してください")
        if item["status"] in {"published", "publishing"}:
            raise ValueError("反映済み・反映中の画像は変更できません")
        if action not in {"approved", "reselection_requested", "held"}:
            raise ValueError("判断が不正です")
        reason = reason.strip()
        if len(reason) > 1500 or (action == "reselection_requested" and not reason):
            raise ValueError("選び直しの理由は空でない1500文字以内で指定してください")
        choices = self.options(item)
        selected_options = options if action == "approved" and options is not None else [option]
        if (not selected_options or len(selected_options) > 10
                or any(not isinstance(index, int) or isinstance(index, bool) or not 0 <= index < len(choices)
                       for index in selected_options) or len(set(selected_options)) != len(selected_options)):
            raise ValueError("候補を選んでください")
        chosen = choices[selected_options[0]]
        asset = chosen["asset"]
        approved_photos = []
        if action == "approved":
            if item["status"] not in {"staged", "held", "approved", "rejected", "reselection_requested"}:
                raise ValueError("Codexの選定が完了した写真だけを採用できます")
            rejected = self.rejections(trivia_id)
            hashes = set()
            for index in selected_options:
                candidate = choices[index]
                photo = self._approved_photo(item, candidate, rejected, rights_confirmed)
                if photo["asset"]["sha256"] in hashes:
                    raise ValueError("同じ写真を重複して採用することはできません")
                hashes.add(photo["asset"]["sha256"])
                approved_photos.append(photo)
            if not chosen["recommended"]:
                item.setdefault("selection_history", []).append({k: item.get(k) for k in
                    ("selected", "asset", "metadata", "approved_photos", "selection", "staging", "codex_review", "review")})
                item.pop("selection", None)
                item.pop("codex_review", None)
            # 先頭は旧データ・既存CLI向けの表紙として残し、採用した全写真を別に保持する。
            item.update(approved_photos[0])
            item["approved_photos"] = approved_photos
            item.pop("reselection_request", None)
            item.pop("error", None)
        record = {"decision": action, "actor": "human", "checked_at": now(), "reason": reason,
                  "rights_confirmed": rights_confirmed, "photo": photo_identity(chosen, asset)}
        if approved_photos:
            record["photos"] = [photo_identity(photo["selected"], photo["asset"]) for photo in approved_photos]
        item["review"] = record
        item.setdefault("review_history", []).append(record)
        if action == "reselection_requested":
            item["reselection_request"] = record
        self.state.save(item, action)

    def _approved_photo(self, item, chosen, rejected, rights_confirmed):
        asset = chosen["asset"]
        if matches_rejection(chosen, rejected):
            raise ValueError("この雑学で却下済みの写真です。別の写真を選んでください")
        if asset.get("format_signature") != format_signature(self.workflow.settings.image_max_dimension, self.workflow.settings.image_webp_quality):
            raise ValueError("アプリの表示サイズに調整してから写真を確認してください")
        metadata = dict(chosen["metadata"])
        licensed_metadata({"descriptionurl": metadata.get("source_url"),
                           "extmetadata": metadata.get("evidence", {}).get("extmetadata", {})}, chosen["file_title"])
        if non_photo(metadata):
            raise ValueError("図版・イラストは採用できません")
        recommended = chosen["recommended"]
        needs_rights = not recommended or item.get("metadata", {}).get("rights_review_required") or bool(metadata.get("restrictions"))
        if needs_rights and not rights_confirmed:
            raise ValueError("追加の利用条件を確認し、権利確認済みを指定してください")
        self.workflow.asset_bytes(asset)
        staging = self.workflow.r2().confirm_asset(asset)
        relationship = item.get("metadata", {}).get("relationship", "reference") if recommended else "reference"
        metadata.update(relationship=relationship, is_reference=relationship == "reference",
                        rights_review_required=bool(needs_rights), changes=processing_changes(asset),
                        display_format=asset.get("processing"), selection_reason="管理画面で写真を確認し採用")
        if recommended:
            metadata = dict(item["metadata"])
        selected = {k: v for k, v in chosen.items() if k != "recommended"}
        return dict(selected=selected, asset=asset, staging=staging, metadata=metadata, credit=credit_text(metadata))
