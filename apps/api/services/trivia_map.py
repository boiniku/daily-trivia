import json
import os
import re
import unicodedata
from datetime import datetime


BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PROJECT_DIR = os.path.dirname(BASE_DIR)
TRIVIA_SPOTS_PATH = os.path.join(PROJECT_DIR, "mobile", "data", "triviaSpots.ts")


def slugify_spot_part(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value or "").lower()
    return re.sub(r"[^a-z0-9]+", "_", normalized).strip("_")


def get_existing_trivia_spot_ids() -> set[str]:
    try:
        with open(TRIVIA_SPOTS_PATH, "r", encoding="utf-8") as f:
            content = f.read()
    except FileNotFoundError:
        return set()
    return set(re.findall(r"\bid:\s*['\"]([^'\"]+)['\"]", content))


def build_trivia_spot_id(prefecture: str, title: str) -> str:
    existing_ids = get_existing_trivia_spot_ids()
    base = "_".join(part for part in [
        slugify_spot_part(prefecture),
        slugify_spot_part(title)[:24],
    ] if part)
    if not base:
        base = f"spot_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    spot_id = base
    suffix = 2
    while spot_id in existing_ids:
        spot_id = f"{base}_{suffix}"
        suffix += 1
    return spot_id


def ts_value(value):
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


def parse_ts_value(raw: str):
    value = (raw or "").strip().rstrip(",")
    if value == "null":
        return None
    if value == "true":
        return True
    if value == "false":
        return False
    if value.startswith(("'", '"')):
        quote = value[0]
        end = value.rfind(quote)
        if end > 0:
            try:
                return json.loads(value[:end + 1])
            except json.JSONDecodeError:
                return value[1:end]
    try:
        return float(value) if "." in value else int(value)
    except ValueError:
        return value


def format_trivia_spot_block(spot: dict) -> str:
    return "\n".join([
        "    {",
        f"        id: {ts_value(spot['id'])},",
        f"        title: {ts_value(spot['title'])},",
        f"        description: {ts_value(spot['description'])},",
        f"        explanation: {ts_value(spot.get('explanation') or '')},",
        f"        latitude: {ts_value(spot['latitude'])},",
        f"        longitude: {ts_value(spot['longitude'])},",
        f"        unlockRadiusMeters: {ts_value(spot['unlockRadiusMeters'])},",
        "        isUnlocked: false,",
        "        unlockedAt: null,",
        f"        prefecture: {ts_value(spot['prefecture'])},",
        f"        address: {ts_value(spot.get('address') or '')},",
        f"        category: {ts_value(spot['category'])},",
        f"        hint: {ts_value(spot.get('hint') or '')},",
        "    },",
    ])


def read_trivia_spots_file() -> str:
    if not os.path.exists(TRIVIA_SPOTS_PATH):
        raise FileNotFoundError(f"MAPデータファイルが見つかりません: {TRIVIA_SPOTS_PATH}")
    with open(TRIVIA_SPOTS_PATH, "r", encoding="utf-8") as f:
        return f.read()


def iter_trivia_spot_blocks(content: str):
    array_start = content.find("[")
    array_end = content.rfind("];")
    if array_start == -1 or array_end == -1 or array_start >= array_end:
        return

    index = array_start
    while index < array_end:
        start = content.find("{", index, array_end)
        if start == -1:
            break
        depth = 0
        in_string = ""
        escape = False
        end = start
        while end < array_end:
            char = content[end]
            if in_string:
                if escape:
                    escape = False
                elif char == "\\":
                    escape = True
                elif char == in_string:
                    in_string = ""
            else:
                if char in ("'", '"'):
                    in_string = char
                elif char == "{":
                    depth += 1
                elif char == "}":
                    depth -= 1
                    if depth == 0:
                        block_end = end + 1
                        comma_end = block_end
                        while comma_end < len(content) and content[comma_end] in (" ", "\t", "\r", "\n", ","):
                            if content[comma_end] == ",":
                                comma_end += 1
                                break
                            comma_end += 1
                        yield start, comma_end, content[start:comma_end]
                        index = comma_end
                        break
            end += 1
        else:
            break


def parse_trivia_spot_block(block: str) -> dict:
    spot = {}
    for key, raw_value in re.findall(r"^\s*([A-Za-z0-9_]+)\s*:\s*(.+?)\s*,?\s*$", block, flags=re.MULTILINE):
        spot[key] = parse_ts_value(raw_value)
    return spot


def load_trivia_spots() -> list[dict]:
    content = read_trivia_spots_file()
    return [
        parse_trivia_spot_block(block)
        for _, _, block in iter_trivia_spot_blocks(content)
    ]


def save_trivia_spot(spot_id: str, spot: dict) -> str:
    content = read_trivia_spots_file()
    for start, end, block in iter_trivia_spot_blocks(content):
        current = parse_trivia_spot_block(block)
        if current.get("id") == spot_id:
            new_block = format_trivia_spot_block(spot)
            new_content = content[:start] + new_block + content[end:]
            with open(TRIVIA_SPOTS_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
            return spot["id"]
    raise ValueError(f"MAP ID '{spot_id}' が見つかりません。")


def delete_trivia_spot(spot_id: str) -> None:
    content = read_trivia_spots_file()
    for start, end, block in iter_trivia_spot_blocks(content):
        current = parse_trivia_spot_block(block)
        if current.get("id") == spot_id:
            new_content = content[:start] + content[end:]
            with open(TRIVIA_SPOTS_PATH, "w", encoding="utf-8") as f:
                f.write(new_content)
            return
    raise ValueError(f"MAP ID '{spot_id}' が見つかりません。")


def build_trivia_spot(
    *,
    title: str,
    description: str,
    prefecture: str,
    latitude: float,
    longitude: float,
    category: str,
    explanation: str = "",
    spot_id: str = "",
    address: str = "",
    unlock_radius_meters: int = 300,
    hint: str = "",
) -> dict:
    final_spot_id = (spot_id or "").strip() or build_trivia_spot_id(prefecture, title)
    if final_spot_id in get_existing_trivia_spot_ids():
        raise ValueError(f"MAP ID '{final_spot_id}' は既に使われています。")
    if not (prefecture or "").strip():
        raise ValueError("雑学MAPに追加する場合は都道府県を入力してください。")

    return {
        "id": final_spot_id,
        "title": title,
        "description": description,
        "explanation": (explanation or "").strip(),
        "latitude": float(latitude),
        "longitude": float(longitude),
        "unlockRadiusMeters": int(unlock_radius_meters),
        "prefecture": prefecture.strip(),
        "address": (address or "").strip(),
        "category": (category or "その他").strip(),
        "hint": (hint or "").strip(),
    }


def append_trivia_spot_to_file(spot: dict) -> str:
    if not os.path.exists(TRIVIA_SPOTS_PATH):
        raise FileNotFoundError(f"MAPデータファイルが見つかりません: {TRIVIA_SPOTS_PATH}")

    with open(TRIVIA_SPOTS_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    insert_at = content.rfind("];")
    if insert_at == -1:
        raise ValueError("MAPデータファイルの配列末尾が見つかりません。")

    new_content = content[:insert_at] + "\n" + format_trivia_spot_block(spot) + "\n" + content[insert_at:]

    with open(TRIVIA_SPOTS_PATH, "w", encoding="utf-8") as f:
        f.write(new_content)

    return spot["id"]


def append_trivia_to_map(**kwargs) -> str:
    spot = build_trivia_spot(**kwargs)
    return append_trivia_spot_to_file(spot)
