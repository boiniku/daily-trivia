"""Codexとの受け渡し。判断をAPIへ委託せず、検証可能な記録にする。"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .config import ROOT


class Plan(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    subject: str = Field(min_length=1, max_length=300)
    exact_queries: list[str] = Field(min_length=1, max_length=2)
    reference_queries: list[str] = Field(max_length=1)
    required_features: str = Field(min_length=1, max_length=1500)
    avoid: str = Field(min_length=1, max_length=1500)


class Selection(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, str_strip_whitespace=True)
    candidate_snapshot: str = Field(pattern=r"^[0-9a-f]{64}$")
    candidate_index: int | None
    relationship: Literal["exact", "general", "reference", "unusable"]
    reason: str = Field(min_length=1, max_length=1500)
    rights_review_required: bool
    is_photograph: bool
    inspected_image_sha256: str | None
    visual_review: str = Field(min_length=1, max_length=1500)
    rights_review: str = Field(min_length=1, max_length=1500)


def validate(schema, value: dict) -> dict:
    try:
        result = schema.model_validate(value).model_dump()
    except ValidationError as exc:
        fields = ", ".join(".".join(str(x) for x in e["loc"]) for e in exc.errors())
        raise ValueError("判断JSONの形式を確認してください: " + fields) from None
    if schema is Plan:
        for query in result["exact_queries"] + result["reference_queries"]:
            if not query.strip() or len(query) > 200:
                raise ValueError("検索語は空でない200文字以内の文字列にしてください")
    return result


def read_json(path: Path) -> dict:
    if path.stat().st_size > 64 * 1024:
        raise ValueError("判断JSONは64KB以内にしてください")
    try:
        value = json.loads(path.read_text(encoding="utf-8-sig"))
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError("UTF-8のJSONファイルを指定してください") from None
    if not isinstance(value, dict):
        raise ValueError("判断JSONはオブジェクト形式にしてください")
    return value


def digest(value) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def candidate_snapshot(item: dict) -> str:
    # 並び替え・検索し直し・加工し直し後に、古い候補番号を使わせない。
    return digest({"trivia": item["trivia"], "plan": item.get("plan"), "candidates": item.get("candidates", [])})


def instructions_version() -> str:
    paths = [ROOT / "AGENTS.md", *sorted((ROOT / "docs" / "harness").glob("*.md")), *sorted((ROOT / "prompts").glob("*.txt"))]
    return digest({str(path.relative_to(ROOT)): path.read_text(encoding="utf-8") for path in paths})


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def task_path(state, item: dict) -> Path:
    folder = state.asset_dir(item["batch_id"]).parent / "tasks" / str(item["trivia_id"])
    return folder / "task.json"


def export_task(state, item: dict, storage=None) -> Path:
    path = task_path(state, item)
    folder = path.parent
    candidates = []
    for index, candidate in enumerate(item.get("candidates", [])):
        metadata = candidate["metadata"]
        evidence_file = folder / f"evidence-{index}.json"
        write_json(evidence_file, metadata.get("evidence", {}))
        # HTMLの利用条件全文は別ファイルへ置き、普段読む候補一覧を小さく保つ。
        candidates.append(dict(candidate, index=index,
                               metadata={k: v for k, v in metadata.items() if k != "evidence"},
                               categories=metadata.get("evidence", {}).get("extmetadata", {}).get("Categories", {}).get("value", ""),
                               metadata_evidence_file=str(evidence_file)))
        if storage and candidate["asset"].get("r2"):
            candidates[-1]["preview_url"] = storage.image_url(candidate["asset"])
            source = candidate["asset"].get("source", {})
            candidates[-1]["source_preview_url"] = storage.image_url(source) if source.get("r2") else ""
    packet = {"batch": item["batch_id"], "trivia_id": item["trivia_id"], "status": item["status"],
              "reselection_request": item.get("reselection_request"), "excluded_photos": item.get("excluded_photos", []),
              "trivia": item["trivia"], "plan": item.get("plan"), "error": item.get("error"),
              "candidate_snapshot": candidate_snapshot(item), "candidates": candidates,
              "instructions": str(ROOT / "docs" / "harness" / "collect.md"),
              "image_inspection": "inspect --batch " + item["batch_id"] + " --id " + str(item["trivia_id"]) + " --candidate <index>",
              "plan_file": str(folder / "plan.json"), "selection_file": str(folder / "selection.json")}
    write_json(path, packet)
    return path
