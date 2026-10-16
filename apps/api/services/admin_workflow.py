"""Validated, atomic write operations used by the trivia administration UI."""

from dataclasses import dataclass
from datetime import datetime
import math
import unicodedata

from sqlalchemy.orm import Session

from models import (
    CollectionItem,
    DailyAssignment,
    MapTrivia,
    SocialContentJob,
    Trivia,
    TriviaCandidate,
    TriviaHee,
)
from services.trivia_candidates import CandidateError, DuplicateCandidateError, find_duplicate
from services.trivia_images import merge_trivia_image_values, trivia_image_values


NORMAL_FIELDS = ("title", "content", "explanation", "source", "category", "image_url", "image_urls", "image_sources")
MAP_FIELDS = (
    "map_address", "map_prefecture", "map_latitude", "map_longitude", "map_radius", "map_hint",
)


@dataclass(frozen=True)
class PublicationResult:
    trivia: Trivia | None = None
    map_trivia: MapTrivia | None = None


def _text(value) -> str:
    return str(value or "").strip()


def _number(value, label: str, minimum: float, maximum: float) -> float:
    try:
        if value is None or isinstance(value, bool):
            raise ValueError
        number = float(value)
    except (ValueError, TypeError, OverflowError):
        raise ValueError(f"{label}を数値で入力してください。") from None
    if not math.isfinite(number) or not minimum <= number <= maximum:
        raise ValueError(f"{label}は{minimum:g}〜{maximum:g}の範囲で入力してください。")
    return number


def validate_trivia_values(
    *,
    title: str,
    content: str,
    explanation: str = "",
    source: str = "",
    category: str = "その他",
    image_url: str | None = None,
    image_urls: list[str] | None = None,
    image_sources: dict[str, str] | None = None,
    add_to_map: bool = False,
    map_address: str = "",
    map_prefecture: str = "",
    map_latitude: float | None = None,
    map_longitude: float | None = None,
    map_radius: int = 1200,
    map_hint: str = "",
) -> dict:
    values = {
        "title": _text(title),
        "content": _text(content),
        "explanation": _text(explanation),
        "source": _text(source),
        "category": _text(category) or "その他",
        **trivia_image_values(image_urls, image_url, image_sources),
    }
    if not values["title"] or not values["content"]:
        raise ValueError("タイトルと本文は必須です。空白だけでは登録できません。")
    if not add_to_map:
        return values

    address, prefecture = _text(map_address), _text(map_prefecture)
    if not prefecture:
        raise ValueError("雑学MAPには都道府県が必要です。")
    if not address:
        raise ValueError("雑学MAPには住所・施設名が必要です。")
    radius = _number(map_radius, "解放半径（メートル）", 10, 5000)
    if not radius.is_integer():
        raise ValueError("解放半径は整数で入力してください。")
    values.update(
        map_address=address,
        map_prefecture=prefecture,
        map_latitude=_number(map_latitude, "緯度", -90, 90),
        map_longitude=_number(map_longitude, "経度", -180, 180),
        map_radius=int(radius),
        map_hint=_text(map_hint) or None,
    )
    return values


def _duplicate_key(value) -> str:
    return " ".join(unicodedata.normalize("NFKC", _text(value)).split()).casefold()


def _check_exact_duplicate(
    db: Session, model, values: dict, *, exclude_id: int | None = None,
) -> None:
    query = db.query(model)
    if exclude_id is not None:
        query = query.filter(model.id != exclude_id)
    key = (_duplicate_key(values["title"]), _duplicate_key(values["content"]))
    for item in query.all():
        if key != (_duplicate_key(item.title), _duplicate_key(item.content)):
            continue
        if model is MapTrivia:
            # A fact may legitimately be available at more than one location.
            if (
                _duplicate_key(item.map_address) != _duplicate_key(values["map_address"])
                or round(item.map_latitude, 6) != round(values["map_latitude"], 6)
                or round(item.map_longitude, 6) != round(values["map_longitude"], 6)
            ):
                continue
            destination = "雑学MAP"
        else:
            destination = "通常の雑学"
        raise DuplicateCandidateError(
            f"同じ内容が{destination}に登録済みです（#{item.id}「{item.title}」）。"
        )


def _validate_targets(add_to_normal: bool, add_to_map: bool) -> None:
    if not add_to_normal and not add_to_map:
        raise ValueError("通常の雑学、雑学MAPのどちらかは選択してください。")


def _add_publications(
    db: Session, values: dict, *, add_to_normal: bool, add_to_map: bool, embedding=None,
) -> PublicationResult:
    trivia = None
    map_trivia = None
    if add_to_normal:
        _check_exact_duplicate(db, Trivia, values)
    if add_to_map:
        _check_exact_duplicate(db, MapTrivia, values)
    if add_to_normal:
        trivia = Trivia(**{field: values[field] for field in NORMAL_FIELDS}, embedding=embedding)
        db.add(trivia)
    if add_to_map:
        map_trivia = MapTrivia(**values)
        db.add(map_trivia)
    return PublicationResult(trivia=trivia, map_trivia=map_trivia)


def create_manual_trivia(
    db: Session, *, add_to_normal: bool = True, add_to_map: bool = False, **values,
) -> PublicationResult:
    try:
        _validate_targets(add_to_normal, add_to_map)
        normalized = validate_trivia_values(add_to_map=add_to_map, **values)
        result = _add_publications(
            db, normalized, add_to_normal=add_to_normal, add_to_map=add_to_map,
        )
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def publish_candidate(
    db: Session,
    candidate_id: int,
    *,
    add_to_normal: bool = True,
    add_to_map: bool = False,
    reviewed_by: str = "streamlit",
    **values,
) -> PublicationResult:
    try:
        _validate_targets(add_to_normal, add_to_map)
        candidate = (
            db.query(TriviaCandidate)
            .filter(TriviaCandidate.id == candidate_id)
            .with_for_update()
            .first()
        )
        if candidate is None:
            raise CandidateError("候補が見つかりません。一覧を再読み込みしてください。")
        if candidate.status != "pending":
            raise CandidateError("この候補は既に確認済みです。一覧を再読み込みしてください。")
        previous = {field: getattr(candidate, field) for field in NORMAL_FIELDS + MAP_FIELDS}
        previous.update(values)
        previous.update(merge_trivia_image_values(candidate, values))
        normalized = validate_trivia_values(add_to_map=add_to_map, **previous)
        if add_to_normal:
            duplicate = find_duplicate(
                db,
                title=normalized["title"],
                content=normalized["content"],
                explanation=normalized["explanation"],
                source=normalized["source"],
                exclude_candidate_id=candidate_id,
                include_pending=False,
            )
            if duplicate:
                raise DuplicateCandidateError(duplicate)
        embedding = candidate.embedding
        if any(getattr(candidate, field) != normalized[field] for field in ("title", "content", "explanation")):
            embedding = None
        result = _add_publications(
            db, normalized, add_to_normal=add_to_normal, add_to_map=add_to_map,
            embedding=embedding,
        )
        for field, value in normalized.items():
            setattr(candidate, field, value)
        candidate.embedding = embedding
        # Existing LINE/mobile flows record map-only publication as a reviewed,
        # rejected candidate; there is no candidate-to-map foreign key yet.
        candidate.status = "approved" if add_to_normal else "rejected"
        candidate.reviewed_at = datetime.utcnow()
        candidate.reviewed_by = reviewed_by if add_to_normal else f"{reviewed_by}:map-published"
        db.flush()
        candidate.published_trivia_id = result.trivia.id if result.trivia else None
        db.commit()
        return result
    except Exception:
        db.rollback()
        raise


def update_normal_trivia(db: Session, trivia_id: int, **values) -> Trivia:
    try:
        item = db.query(Trivia).filter(Trivia.id == trivia_id).first()
        if item is None:
            raise ValueError("公開済み雑学が見つかりません。")
        previous = {field: getattr(item, field) for field in NORMAL_FIELDS}
        previous.update(values)
        previous.update(merge_trivia_image_values(item, values))
        normalized = validate_trivia_values(**previous)
        _check_exact_duplicate(db, Trivia, normalized, exclude_id=trivia_id)
        if any(getattr(item, field) != normalized[field] for field in ("title", "content", "explanation")):
            item.embedding = None
        for field, value in normalized.items():
            setattr(item, field, value)
        db.commit()
        return item
    except Exception:
        db.rollback()
        raise


def update_map_trivia(db: Session, map_trivia_id: int, **values) -> MapTrivia:
    try:
        item = db.query(MapTrivia).filter(MapTrivia.id == map_trivia_id).first()
        if item is None:
            raise ValueError("公開済みMAP雑学が見つかりません。")
        previous = {field: getattr(item, field) for field in NORMAL_FIELDS + MAP_FIELDS}
        previous.update(values)
        previous.update(merge_trivia_image_values(item, values))
        normalized = validate_trivia_values(add_to_map=True, **previous)
        _check_exact_duplicate(db, MapTrivia, normalized, exclude_id=map_trivia_id)
        for field, value in normalized.items():
            setattr(item, field, value)
        db.commit()
        return item
    except Exception:
        db.rollback()
        raise


def delete_normal_trivia(db: Session, trivia_id: int) -> None:
    try:
        item = db.query(Trivia).filter(Trivia.id == trivia_id).with_for_update().first()
        if item is None:
            raise ValueError("公開済み雑学が見つかりません。")
        if db.query(SocialContentJob.id).filter(SocialContentJob.trivia_id == trivia_id).first():
            raise ValueError("SNS投稿データで使用中のため削除できません。SNSの管理画面で関連データを確認してください。")
        for model in (DailyAssignment, CollectionItem, TriviaHee):
            db.query(model).filter(model.trivia_id == trivia_id).delete(synchronize_session="fetch")
        db.query(TriviaCandidate).filter(TriviaCandidate.published_trivia_id == trivia_id).update(
            {TriviaCandidate.published_trivia_id: None}, synchronize_session="fetch",
        )
        db.delete(item)
        db.commit()
    except Exception:
        db.rollback()
        raise
