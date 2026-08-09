import argparse
import os
import sys
import zipfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Iterable

from sqlalchemy.orm import Session

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from database import SessionLocal
from models import MapTrivia


NS = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


@dataclass
class MapTriviaRow:
    map_id: str
    title: str
    content: str
    explanation: str
    category: str
    prefecture: str
    address: str
    latitude: float
    longitude: float
    source_url: str
    status: str


def _cell_value(cell: ET.Element, shared_strings: list[str]) -> str:
    cell_type = cell.attrib.get("t")
    value = cell.find("a:v", NS)
    inline = cell.find("a:is", NS)
    if cell_type == "s" and value is not None and value.text is not None:
        return shared_strings[int(value.text)]
    if cell_type == "inlineStr" and inline is not None:
        return "".join(node.text or "" for node in inline.iter(f"{{{NS['a']}}}t"))
    if value is not None and value.text is not None:
        return value.text
    return ""


def _load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in zf.namelist():
        return []
    root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    return [
        "".join(node.text or "" for node in item.iter(f"{{{NS['a']}}}t"))
        for item in root
    ]


def _get_first_sheet_path(zf: zipfile.ZipFile) -> str:
    rel_ns = {"r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
    pkg_ns = {"pr": "http://schemas.openxmlformats.org/package/2006/relationships"}
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    rel_map = {rel.attrib["Id"]: rel.attrib["Target"] for rel in rels.findall("pr:Relationship", pkg_ns)}
    first_sheet = workbook.find("a:sheets", NS)
    if first_sheet is None or not list(first_sheet):
        raise ValueError("Excel ファイルにシートが見つかりません。")
    first = list(first_sheet)[0]
    rel_id = first.attrib[f"{{{rel_ns['r']}}}id"]
    target = rel_map[rel_id].lstrip("/")
    return target if target.startswith("xl/") else f"xl/{target}"


def _iter_sheet_rows(xlsx_path: str) -> Iterable[list[str]]:
    with zipfile.ZipFile(xlsx_path) as zf:
        shared_strings = _load_shared_strings(zf)
        sheet_path = _get_first_sheet_path(zf)
        worksheet = ET.fromstring(zf.read(sheet_path))
        sheet_data = worksheet.find("a:sheetData", NS)
        if sheet_data is None:
            return
        for row in sheet_data.findall("a:row", NS):
            yield [_cell_value(cell, shared_strings).strip() for cell in row.findall("a:c", NS)]


def _parse_float(value: str, field_name: str) -> float:
    try:
        return float(value)
    except ValueError as exc:
        raise ValueError(f"{field_name} の値が不正です: {value}") from exc


def load_rows(xlsx_path: str) -> list[MapTriviaRow]:
    rows = list(_iter_sheet_rows(xlsx_path))
    if not rows:
        raise ValueError("Excel ファイルにデータがありません。")

    header = rows[0]
    expected = [
        "MAP ID",
        "タイトル",
        "本文",
        "解説",
        "カテゴリ",
        "都道府県",
        "住所・施設名",
        "緯度",
        "経度",
        "出典URL",
        "確認状況",
    ]
    if header[: len(expected)] != expected:
        raise ValueError(f"想定外のヘッダーです: {header}")

    items: list[MapTriviaRow] = []
    for index, raw in enumerate(rows[1:], start=2):
        if not any(raw):
            continue
        padded = raw + [""] * (len(expected) - len(raw))
        items.append(
            MapTriviaRow(
                map_id=padded[0],
                title=padded[1],
                content=padded[2],
                explanation=padded[3],
                category=padded[4] or "その他",
                prefecture=padded[5],
                address=padded[6],
                latitude=_parse_float(padded[7], f"{index}行目の緯度"),
                longitude=_parse_float(padded[8], f"{index}行目の経度"),
                source_url=padded[9],
                status=padded[10],
            )
        )
    return items


def _normalize(value: str) -> str:
    return " ".join((value or "").strip().split())


def find_existing_match(db: Session, row: MapTriviaRow) -> MapTrivia | None:
    existing_items = db.query(MapTrivia).filter(MapTrivia.title == row.title.strip()).all()
    normalized_content = _normalize(row.content)
    normalized_address = _normalize(row.address)
    for item in existing_items:
        if _normalize(item.map_address) == normalized_address:
            return item
        if _normalize(item.content) == normalized_content:
            return item
    return None


def find_exact_row_match(db: Session, row: MapTriviaRow) -> MapTrivia | None:
    existing_items = (
        db.query(MapTrivia)
        .filter(MapTrivia.map_address == row.address.strip())
        .filter(MapTrivia.map_prefecture == row.prefecture.strip())
        .all()
    )
    normalized_content = _normalize(row.content)
    normalized_explanation = _normalize(row.explanation)
    normalized_address = _normalize(row.address)
    normalized_prefecture = _normalize(row.prefecture)
    normalized_source = _normalize(row.source_url)
    normalized_category = _normalize(row.category or "その他")

    for item in existing_items:
        if _normalize(item.content) != normalized_content:
            continue
        if _normalize(item.explanation or "") != normalized_explanation:
            continue
        if _normalize(item.map_address) != normalized_address:
            continue
        if _normalize(item.map_prefecture) != normalized_prefecture:
            continue
        if _normalize(item.source or "") != normalized_source:
            continue
        if _normalize(item.category or "その他") != normalized_category:
            continue
        if float(item.map_latitude) != float(row.latitude):
            continue
        if float(item.map_longitude) != float(row.longitude):
            continue
        return item
    return None


def import_rows(xlsx_path: str, dry_run: bool = False) -> tuple[int, int]:
    db = SessionLocal()
    inserted = 0
    skipped = 0
    try:
        for row in load_rows(xlsx_path):
            if find_existing_match(db, row):
                skipped += 1
                continue

            db.add(
                MapTrivia(
                    title=row.title.strip(),
                    content=row.content.strip(),
                    explanation=row.explanation.strip(),
                    source=row.source_url.strip(),
                    category=(row.category or "その他").strip(),
                    image_url=None,
                    map_address=row.address.strip(),
                    map_prefecture=row.prefecture.strip(),
                    map_latitude=row.latitude,
                    map_longitude=row.longitude,
                    map_radius=500,
                    map_hint=row.status.strip() or None,
                )
            )
            inserted += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return inserted, skipped
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def delete_rows(xlsx_path: str, dry_run: bool = False) -> tuple[int, int]:
    db = SessionLocal()
    deleted = 0
    skipped = 0
    try:
        for row in load_rows(xlsx_path):
            item = find_exact_row_match(db, row)
            if item is None:
                skipped += 1
                continue
            db.delete(item)
            deleted += 1

        if dry_run:
            db.rollback()
        else:
            db.commit()
        return deleted, skipped
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description="雑学MAP 用の Excel を map_trivia に追加入力します。")
    parser.add_argument("xlsx_path", help="取り込む .xlsx ファイルのパス")
    parser.add_argument("--dry-run", action="store_true", help="DB に保存せず件数だけ確認します")
    parser.add_argument("--delete", action="store_true", help="Excel と一致する雑学MAPデータを削除します")
    args = parser.parse_args()

    if args.delete:
        deleted, skipped = delete_rows(args.xlsx_path, dry_run=args.dry_run)
        mode = "DRY RUN" if args.dry_run else "DELETED"
        print(f"{mode}: deleted={deleted} skipped={skipped}")
    else:
        inserted, skipped = import_rows(args.xlsx_path, dry_run=args.dry_run)
        mode = "DRY RUN" if args.dry_run else "IMPORTED"
        print(f"{mode}: inserted={inserted} skipped={skipped}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
