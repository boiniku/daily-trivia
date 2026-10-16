import csv
from dataclasses import dataclass, field
from io import StringIO

from sqlalchemy.orm import Session

from models import Trivia


TRIVIA_CATEGORIES = [
    "歴史", "地理", "科学", "宇宙・天体", "生物", "人体・医学",
    "生活", "食べ物", "芸術・文化", "デザイン", "エンタメ",
    "スポーツ", "IT・テクノロジー", "心理学", "言語・言葉", "その他",
]
CSV_HEADERS = ("タイトル", "本文", "詳細", "カテゴリ")
MAX_CSV_ROWS = 1000


class TriviaCsvValidationError(ValueError):
    def __init__(self, errors: list[str]):
        self.errors = errors
        super().__init__("\n".join(errors))


@dataclass(frozen=True)
class TriviaCsvRow:
    line_number: int
    title: str
    content: str
    explanation: str
    category: str

    @property
    def duplicate_key(self) -> tuple[str, str]:
        return (_normalize_for_duplicate(self.title), _normalize_for_duplicate(self.content))


@dataclass
class ParsedTriviaCsv:
    rows: list[TriviaCsvRow]
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class TriviaCsvImportResult:
    created_count: int
    skipped_duplicate_count: int


def _normalize_for_duplicate(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _decode_csv(data: bytes) -> str:
    if not data:
        raise TriviaCsvValidationError(["CSVファイルが空です。"])
    for encoding in ("utf-8-sig", "cp932"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            continue
    raise TriviaCsvValidationError([
        "文字コードを読み取れません。UTF-8またはShift_JISで保存してください。"
    ])


def parse_trivia_csv(data: bytes, max_rows: int = MAX_CSV_ROWS) -> ParsedTriviaCsv:
    text = _decode_csv(data)
    if "\x00" in text:
        raise TriviaCsvValidationError(["CSVに読み取れない文字が含まれています。"])

    try:
        records = list(csv.reader(StringIO(text, newline="")))
    except csv.Error as exc:
        raise TriviaCsvValidationError([f"CSVの形式が正しくありません: {exc}"]) from exc

    if not records:
        raise TriviaCsvValidationError(["CSVファイルが空です。"])

    headers = [cell.strip() for cell in records[0]]
    if headers != list(CSV_HEADERS):
        raise TriviaCsvValidationError([
            "1行目の見出しを「タイトル,本文,詳細,カテゴリ」の順にしてください。"
        ])

    non_empty_records = [
        (line_number, record)
        for line_number, record in enumerate(records[1:], start=2)
        if any(cell.strip() for cell in record)
    ]
    if len(non_empty_records) > max_rows:
        raise TriviaCsvValidationError([f"一度に登録できるのは{max_rows}件までです。"])

    errors: list[str] = []
    warnings: list[str] = []
    rows: list[TriviaCsvRow] = []
    seen_keys: set[tuple[str, str]] = set()

    for line_number, record in non_empty_records:
        if len(record) != len(CSV_HEADERS):
            errors.append(f"{line_number}行目: 列数が{len(record)}列です。4列にしてください。")
            continue

        title, content, explanation, category = (cell.strip() for cell in record)
        row_errors = []
        if not title:
            row_errors.append("タイトルは必須です")
        elif len(title) > 50:
            row_errors.append("タイトルは50文字以内です")
        if not content:
            row_errors.append("本文は必須です")
        elif len(content) > 100:
            row_errors.append("本文は100文字以内です")
        if not category:
            row_errors.append("カテゴリは必須です")
        elif category not in TRIVIA_CATEGORIES:
            row_errors.append(f"未対応のカテゴリ「{category}」です")
        if row_errors:
            errors.append(f"{line_number}行目: " + " / ".join(row_errors))
            continue

        row = TriviaCsvRow(line_number, title, content, explanation, category)
        if row.duplicate_key in seen_keys:
            warnings.append(f"{line_number}行目: CSV内の重複のため登録対象から除外しました。")
            continue
        seen_keys.add(row.duplicate_key)
        rows.append(row)

    if not non_empty_records:
        errors.append("2行目以降に登録データがありません。")
    if errors:
        raise TriviaCsvValidationError(errors)
    return ParsedTriviaCsv(rows=rows, warnings=warnings)


def find_existing_duplicate_keys(db: Session, rows: list[TriviaCsvRow]) -> set[tuple[str, str]]:
    if not rows:
        return set()
    titles = list({row.title for row in rows})
    existing = db.query(Trivia.title, Trivia.content).filter(Trivia.title.in_(titles)).all()
    row_keys = {row.duplicate_key for row in rows}
    return {
        (_normalize_for_duplicate(title), _normalize_for_duplicate(content))
        for title, content in existing
        if (_normalize_for_duplicate(title), _normalize_for_duplicate(content)) in row_keys
    }


def import_trivia_rows(db: Session, rows: list[TriviaCsvRow]) -> TriviaCsvImportResult:
    duplicate_keys = find_existing_duplicate_keys(db, rows)
    new_rows = [row for row in rows if row.duplicate_key not in duplicate_keys]
    try:
        db.add_all([
            Trivia(
                title=row.title,
                content=row.content,
                explanation=row.explanation,
                source="",
                category=row.category,
            )
            for row in new_rows
        ])
        db.commit()
    except Exception:
        db.rollback()
        raise
    return TriviaCsvImportResult(
        created_count=len(new_rows),
        skipped_duplicate_count=len(rows) - len(new_rows),
    )
