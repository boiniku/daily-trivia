import os
import json
import socket
from io import BytesIO
from dotenv import load_dotenv
from openai import OpenAI
import streamlit as st
import pandas as pd
import difflib
import requests
try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:
    boto3 = None
    BotoConfig = None
try:
    from PIL import Image, ImageOps, UnidentifiedImageError
except ImportError:
    Image = None
    ImageOps = None
    UnidentifiedImageError = Exception
from sqlalchemy.orm import Session
from sqlalchemy import and_, or_, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from database import SessionLocal
from models import Trivia, TriviaCandidate, DailyAssignment, CollectionItem, TriviaHee
from services.trivia_candidates import (
    approve_candidate,
    create_candidates,
    reject_candidate,
    update_candidate,
)
from services.trivia_map import (
    append_trivia_spot_to_file,
    append_trivia_to_map,
    build_trivia_spot,
    delete_trivia_spot,
    load_trivia_spots,
    save_trivia_spot,
)
from datetime import datetime

# Load env vars
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

# Configure OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.warning("⚠️ OPENAI_API_KEY not found in .env file.")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

# Constants
TRIVIA_CATEGORIES = [
    "歴史", "地理", "科学", "宇宙・天体", "生物", "人体・医学", 
    "生活", "食べ物", "芸術・文化", "デザイン", "エンタメ", 
    "スポーツ", "IT・テクノロジー", "心理学", "言語・言葉", 
    "その他"
]
CATEGORIES_STR = ", ".join(TRIVIA_CATEGORIES)
IMAGE_CROP_OPTIONS = {
    "トリミングなし": None,
    "正方形": 1,
    "横長 4:3": 4 / 3,
    "横長 16:9": 16 / 9,
    "アプリ表示サイズ 16:9 手動調整": "manual_16_9",
}
TRIVIA_IMAGE_R2_BASE_URL = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
ADMIN_DASHBOARD_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "").strip()
R2_PREFIX = os.getenv("R2_TRIVIA_IMAGE_PREFIX", "trivia").strip().strip("/")
TRIVIA_IMAGE_MAX_DIMENSION = int(os.getenv("TRIVIA_IMAGE_MAX_DIMENSION", "1600"))
TRIVIA_IMAGE_WEBP_QUALITY = int(os.getenv("TRIVIA_IMAGE_WEBP_QUALITY", "78"))


def get_missing_r2_settings() -> list[str]:
    required_settings = {
        "R2_ENDPOINT_URL": R2_ENDPOINT_URL,
        "R2_ACCESS_KEY_ID": R2_ACCESS_KEY_ID,
        "R2_SECRET_ACCESS_KEY": R2_SECRET_ACCESS_KEY,
        "R2_BUCKET_NAME": R2_BUCKET_NAME,
    }
    return [key for key, value in required_settings.items() if not value]


def get_r2_client():
    if boto3 is None:
        return None
    if not all([R2_ENDPOINT_URL, R2_ACCESS_KEY_ID, R2_SECRET_ACCESS_KEY, R2_BUCKET_NAME]):
        return None
    return boto3.client(
        "s3",
        endpoint_url=R2_ENDPOINT_URL,
        aws_access_key_id=R2_ACCESS_KEY_ID,
        aws_secret_access_key=R2_SECRET_ACCESS_KEY,
        region_name="auto",
        config=BotoConfig(
            connect_timeout=5,
            read_timeout=10,
            retries={"max_attempts": 1},
        ),
    )


def get_r2_unavailable_reason() -> str:
    if boto3 is None:
        return "boto3 is not installed in the Python environment running Streamlit."
    missing = get_missing_r2_settings()
    if missing:
        return f"Missing: {', '.join(missing)}"
    return ""


def crop_image_to_aspect(img, aspect_ratio: float):
    width, height = img.size
    current_ratio = width / height

    if current_ratio > aspect_ratio:
        new_width = int(height * aspect_ratio)
        left = (width - new_width) // 2
        return img.crop((left, 0, left + new_width, height))

    new_height = int(width / aspect_ratio)
    top = (height - new_height) // 2
    return img.crop((0, top, width, top + new_height))


def prepare_image_for_r2(img):
    img.thumbnail(
        (TRIVIA_IMAGE_MAX_DIMENSION, TRIVIA_IMAGE_MAX_DIMENSION),
        Image.Resampling.LANCZOS,
    )

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() else "RGB")

    optimized = BytesIO()
    img.save(
        optimized,
        format="WEBP",
        quality=TRIVIA_IMAGE_WEBP_QUALITY,
        method=6,
    )
    optimized.seek(0)
    optimized.name = "image.webp"
    optimized.type = "image/webp"
    return optimized


def load_pil_image(uploaded_file):
    uploaded_file.seek(0)
    with Image.open(uploaded_file) as img:
        return ImageOps.exif_transpose(img).copy()


def pil_image_to_upload_file(img):
    image_stream = prepare_image_for_r2(img.copy())
    image_stream.seek(0)
    return image_stream


def optimize_image_for_r2(uploaded_file, crop_mode: str | None = None):
    filename = uploaded_file.name or "image"
    _, ext = os.path.splitext(filename)
    ext = ext.lower() if ext else ".jpg"
    safe_ext = ext if ext in [".jpg", ".jpeg", ".png", ".webp", ".gif"] else ".jpg"
    content_type = uploaded_file.type or "image/jpeg"

    uploaded_file.seek(0)
    original_bytes = uploaded_file.getvalue()

    if Image is None or safe_ext == ".gif":
        return BytesIO(original_bytes), safe_ext, content_type

    try:
        with Image.open(BytesIO(original_bytes)) as img:
            img = ImageOps.exif_transpose(img)
            aspect_ratio = IMAGE_CROP_OPTIONS.get(crop_mode or "トリミングなし")
            if isinstance(aspect_ratio, (int, float)):
                img = crop_image_to_aspect(img, aspect_ratio)
            optimized = prepare_image_for_r2(img)

        if optimized.getbuffer().nbytes >= len(original_bytes):
            return BytesIO(original_bytes), safe_ext, content_type

        return optimized, ".webp", "image/webp"
    except (OSError, UnidentifiedImageError):
        return BytesIO(original_bytes), safe_ext, content_type


def get_processed_image_preview(uploaded_file, crop_mode: str | None = None):
    if not uploaded_file:
        return None
    image_stream, _, _ = optimize_image_for_r2(uploaded_file, crop_mode)
    image_stream.seek(0)
    return image_stream


def crop_image_with_focus(img, aspect_ratio: float, zoom: float, focus_x: int, focus_y: int):
    width, height = img.size
    base_width = width
    base_height = int(base_width / aspect_ratio)
    if base_height > height:
        base_height = height
        base_width = int(base_height * aspect_ratio)

    crop_width = max(1, int(base_width / zoom))
    crop_height = max(1, int(crop_width / aspect_ratio))
    if crop_height > height:
        crop_height = height
        crop_width = int(crop_height * aspect_ratio)

    max_left = max(0, width - crop_width)
    max_top = max(0, height - crop_height)
    left = int(max_left * (focus_x / 100))
    top = int(max_top * (focus_y / 100))
    return img.crop((left, top, left + crop_width, top + crop_height))


def render_manual_cropper(uploaded_file, key: str):
    if not uploaded_file or Image is None:
        return None

    try:
        img = load_pil_image(uploaded_file)
    except (OSError, UnidentifiedImageError):
        return None

    zoom = st.slider(
        "ズーム",
        min_value=1.0,
        max_value=3.0,
        value=1.0,
        step=0.05,
        key=f"{key}_zoom",
    )
    focus_x = st.slider(
        "左右位置",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{key}_focus_x",
    )
    focus_y = st.slider(
        "上下位置",
        min_value=0,
        max_value=100,
        value=50,
        step=1,
        key=f"{key}_focus_y",
    )
    return crop_image_with_focus(img, 16 / 9, zoom, focus_x, focus_y)


def download_image_for_processing(image_url: str):
    resolved_url = normalize_image_url(image_url)

    object_key = get_r2_object_key(resolved_url or image_url)
    if object_key:
        client = get_r2_client()
        if client is None:
            reason = get_r2_unavailable_reason()
            raise RuntimeError(f"R2 settings are incomplete. {reason}")

        response = client.get_object(Bucket=R2_BUCKET_NAME, Key=object_key)
        body = response["Body"].read()
        image_stream = BytesIO(body)
        image_stream.name = os.path.basename(object_key) or "image.jpg"
        image_stream.type = response.get("ContentType", "image/jpeg")
        return image_stream

    if not resolved_url or not resolved_url.startswith(("http://", "https://")):
        raise RuntimeError("既存画像を取得できません。写真URLが有効なhttp/https URLではありません。")

    response = requests.get(
        resolved_url,
        timeout=(5, 10),
        headers={"User-Agent": "daily-trivia-admin/1.0"},
    )
    response.raise_for_status()

    image_stream = BytesIO(response.content)
    filename = os.path.basename(resolved_url.split("?", 1)[0]) or "image.jpg"
    image_stream.name = filename
    image_stream.type = response.headers.get("Content-Type", "image/jpeg")
    return image_stream


def upload_image_to_r2(uploaded_file, trivia_id: int | None = None, crop_mode: str | None = None) -> str:
    client = get_r2_client()
    if client is None:
        reason = get_r2_unavailable_reason()
        raise RuntimeError(f"R2 settings are incomplete. {reason}")

    image_stream, safe_ext, content_type = optimize_image_for_r2(uploaded_file, crop_mode)
    timestamp = datetime.utcnow().strftime("%Y%m%d%H%M%S")
    base_name = f"{trivia_id or 'new'}-{timestamp}{safe_ext}"
    object_key = f"{R2_PREFIX}/{base_name}" if R2_PREFIX else base_name

    image_stream.seek(0)
    client.put_object(
        Bucket=R2_BUCKET_NAME,
        Key=object_key,
        Body=image_stream.read(),
        ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )

    if not TRIVIA_IMAGE_R2_BASE_URL:
        return object_key
    return f"{TRIVIA_IMAGE_R2_BASE_URL}/{object_key}"


def get_r2_object_key(image_url: str) -> str:
    value = (image_url or "").strip()
    if not value or value.startswith("data:"):
        return ""

    if value.startswith(("http://", "https://")):
        if not TRIVIA_IMAGE_R2_BASE_URL:
            return ""
        base_url = TRIVIA_IMAGE_R2_BASE_URL.rstrip("/") + "/"
        if not value.startswith(base_url):
            return ""
        return value[len(base_url):].lstrip("/")

    return value.lstrip("/")


def delete_image_from_r2(image_url: str) -> bool:
    object_key = get_r2_object_key(image_url)
    if not object_key:
        return False

    client = get_r2_client()
    if client is None:
        reason = get_r2_unavailable_reason()
        raise RuntimeError(f"R2 settings are incomplete. {reason}")

    try:
        client.delete_object(Bucket=R2_BUCKET_NAME, Key=object_key)
        return True
    except Exception as e:
        print(f"R2 image delete skipped/failed for {object_key}: {e}")
        return False


def normalize_image_url(raw_value: str) -> str:
    value = (raw_value or "").strip()
    if not value:
        return ""
    if value.startswith(("http://", "https://", "data:")):
        return value
    if not TRIVIA_IMAGE_R2_BASE_URL:
        return value.lstrip("/")
    return f"{TRIVIA_IMAGE_R2_BASE_URL}/{value.lstrip('/')}"


def get_lan_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            return s.getsockname()[0]
    except OSError:
        return "localhost"


def require_admin_password() -> None:
    if not ADMIN_DASHBOARD_PASSWORD:
        st.sidebar.warning("ADMIN_DASHBOARD_PASSWORD が未設定です。iPhoneから開く前に設定推奨です。")
        return

    if st.session_state.get("admin_authenticated"):
        return

    st.title("毎日雑学 管理ツール")
    with st.form("admin_login"):
        password = st.text_input("管理パスワード", type="password")
        submitted = st.form_submit_button("ログイン", type="primary")

    if submitted:
        if password == ADMIN_DASHBOARD_PASSWORD:
            st.session_state.admin_authenticated = True
            st.rerun()
        else:
            st.error("パスワードが違います。")
    st.stop()

# Page Config
st.set_page_config(page_title="Trivia Manager", layout="wide", page_icon="📝")
require_admin_password()

st.title("📝 毎日雑学 管理ツール")
lan_ip = get_lan_ip()
st.sidebar.header("iPhone接続")
st.sidebar.code(f"http://{lan_ip}:8501")
st.sidebar.caption("同じWi-Fiで、PC側のStreamlitを --server.address 0.0.0.0 で起動すると開けます。")
if TRIVIA_IMAGE_R2_BASE_URL:
    st.sidebar.caption(f"R2 base: {TRIVIA_IMAGE_R2_BASE_URL}")
missing_r2_settings = get_missing_r2_settings()
r2_unavailable_reason = get_r2_unavailable_reason()
if r2_unavailable_reason:
    st.sidebar.warning(f"R2アップロード設定が未完了です: {r2_unavailable_reason}")

# Database Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db = next(get_db())
try:
    db.execute(text("SELECT 1"))
    from migrate_trivia_candidates import migrate as migrate_trivia_candidates
    migrate_trivia_candidates()
except OperationalError:
    st.error("データベースに接続できません。NeonのDATABASE_URLのパスワードが違う、または古い可能性があります。")
    st.info("Neonダッシュボードで現在の接続文字列をコピーし、backend/.env の DATABASE_URL を更新してから Streamlit を再起動してください。")
    st.stop()
except SQLAlchemyError as e:
    st.error(f"データベース接続の確認に失敗しました: {e}")
    st.stop()


def _candidate_has_complete_map(candidate: TriviaCandidate) -> bool:
    return bool(
        candidate.map_address
        and candidate.map_prefecture
        and candidate.map_latitude is not None
        and candidate.map_longitude is not None
    )


def _candidate_to_admin_map_spot(candidate: TriviaCandidate) -> dict:
    return {
        "id": f"candidate_{candidate.id}",
        "title": candidate.title or "",
        "description": candidate.content or "",
        "explanation": candidate.explanation or "",
        "latitude": float(candidate.map_latitude),
        "longitude": float(candidate.map_longitude),
        "unlockRadiusMeters": int(candidate.map_radius or 300),
        "isUnlocked": False,
        "unlockedAt": None,
        "prefecture": candidate.map_prefecture or "",
        "address": candidate.map_address or "",
        "category": candidate.category or "その他",
        "hint": candidate.map_hint or "",
        "_source": "db-candidate",
        "_candidate_id": candidate.id,
    }


def _map_spot_identity(spot: dict) -> tuple:
    def normalize(value):
        return str(value or "").strip().lower()

    return (
        normalize(spot.get("title")),
        normalize(spot.get("address")),
        round(float(spot.get("latitude") or 0), 6),
        round(float(spot.get("longitude") or 0), 6),
    )


def _load_published_candidate_map_spots(db_session: Session) -> list[dict]:
    candidates = (
        db_session.query(TriviaCandidate)
        .filter(
            TriviaCandidate.status == "rejected",
            TriviaCandidate.reviewed_by.like("%map-only%"),
            TriviaCandidate.map_address.isnot(None),
            TriviaCandidate.map_prefecture.isnot(None),
            TriviaCandidate.map_latitude.isnot(None),
            TriviaCandidate.map_longitude.isnot(None),
        )
        .order_by(TriviaCandidate.reviewed_at.desc().nullslast(), TriviaCandidate.created_at.desc())
        .all()
    )
    return [
        _candidate_to_admin_map_spot(candidate)
        for candidate in candidates
        if _candidate_has_complete_map(candidate)
    ]


def _load_admin_map_spots(db_session: Session) -> tuple[list[dict], str | None]:
    file_warning = None
    try:
        spots = load_trivia_spots()
    except Exception as e:
        spots = []
        file_warning = f"MAPデータファイルを読み込めませんでした。DBに残っているLINE公開分だけ表示します: {e}"

    seen = {_map_spot_identity(spot) for spot in spots}
    for spot in _load_published_candidate_map_spots(db_session):
        identity = _map_spot_identity(spot)
        if identity not in seen:
            spots.append(spot)
            seen.add(identity)
    return spots, file_warning


def _is_db_candidate_map_spot(spot: dict) -> bool:
    return spot.get("_source") == "db-candidate" and spot.get("_candidate_id") is not None


def _update_candidate_map_spot(db_session: Session, candidate_id: int, values: dict) -> None:
    candidate = db_session.query(TriviaCandidate).filter(TriviaCandidate.id == candidate_id).first()
    if not candidate:
        raise ValueError("DB候補が見つかりません。")

    candidate.title = values["title"]
    candidate.content = values["description"]
    candidate.explanation = values["explanation"]
    candidate.category = values["category"]
    candidate.map_prefecture = values["prefecture"]
    candidate.map_address = values["address"]
    candidate.map_latitude = values["latitude"]
    candidate.map_longitude = values["longitude"]
    candidate.map_radius = values["unlockRadiusMeters"]
    candidate.map_hint = values.get("hint") or ""
    db_session.commit()


def _hide_candidate_map_spot(db_session: Session, candidate_id: int) -> None:
    candidate = db_session.query(TriviaCandidate).filter(TriviaCandidate.id == candidate_id).first()
    if not candidate:
        raise ValueError("DB候補が見つかりません。")

    candidate.map_address = None
    candidate.map_prefecture = None
    candidate.map_latitude = None
    candidate.map_longitude = None
    candidate.map_radius = None
    candidate.map_hint = None
    db_session.commit()


def render_trivia_map_admin():
    st.subheader("雑学MAPを管理")
    spots, file_warning = _load_admin_map_spots(db)
    if file_warning:
        st.warning(file_warning)

    search_query = st.text_input("🔍 MAP検索 (タイトル・本文・住所)", "", key="map_search")
    if search_query:
        needle = search_query.lower()
        spots = [
            spot for spot in spots
            if needle in " ".join(str(spot.get(key) or "") for key in ["title", "description", "explanation", "prefecture", "address", "category"]).lower()
        ]

    st.write(f"全 {len(spots)} 件")
    if not spots:
        st.info("雑学MAPのデータが見つかりません。")
        return

    labels = {}
    for spot in spots:
        source_label = "DB/LINE" if _is_db_candidate_map_spot(spot) else "ファイル"
        labels[f"{spot.get('id')}: {spot.get('title', '無題')} ({spot.get('prefecture') or '未設定'} / {source_label})"] = spot
    selected_label = st.selectbox("編集するMAP雑学", list(labels.keys()), key="map_edit_select")
    spot = labels[selected_label]
    original_id = str(spot.get("id") or "")
    is_db_candidate_spot = _is_db_candidate_map_spot(spot)

    st.subheader(f"MAP編集: {original_id}")
    if is_db_candidate_spot:
        st.info("LINEやスマホ編集からMAP公開されたDB候補です。管理画面で編集できますが、アプリ内の静的MAPデータへ反映するには別途ファイルへの同期が必要です。")
    m_title = st.text_input("タイトル", value=str(spot.get("title") or ""), key=f"map_title_{original_id}")
    m_description = st.text_area("本文", value=str(spot.get("description") or ""), key=f"map_description_{original_id}")
    m_explanation = st.text_area("解説", value=str(spot.get("explanation") or ""), key=f"map_explanation_{original_id}")
    map_col1, map_col2 = st.columns(2)
    with map_col1:
        m_id = st.text_input("MAP ID", value=original_id, disabled=is_db_candidate_spot, key=f"map_id_{original_id}")
        m_prefecture = st.text_input("都道府県", value=str(spot.get("prefecture") or ""), key=f"map_prefecture_{original_id}")
        m_latitude = st.number_input(
            "緯度",
            min_value=-90.0,
            max_value=90.0,
            value=float(spot.get("latitude") or 35.6812),
            format="%.6f",
            key=f"map_latitude_{original_id}",
        )
    with map_col2:
        m_category = st.selectbox(
            "カテゴリ",
            TRIVIA_CATEGORIES,
            index=TRIVIA_CATEGORIES.index(spot.get("category")) if spot.get("category") in TRIVIA_CATEGORIES else TRIVIA_CATEGORIES.index("その他"),
            key=f"map_category_{original_id}",
        )
        m_address = st.text_input("住所・施設名", value=str(spot.get("address") or ""), key=f"map_address_{original_id}")
        m_longitude = st.number_input(
            "経度",
            min_value=-180.0,
            max_value=180.0,
            value=float(spot.get("longitude") or 139.7671),
            format="%.6f",
            key=f"map_longitude_{original_id}",
        )
    m_radius = st.number_input(
        "解放半径（メートル）",
        min_value=10,
        max_value=5000,
        value=int(spot.get("unlockRadiusMeters") or 300),
        step=10,
        key=f"map_radius_{original_id}",
    )

    action_col1, action_col2, action_col3 = st.columns([1, 1, 3])
    with action_col1:
        update_map = st.button("MAP更新", type="primary", key=f"map_update_{original_id}")
    with action_col2:
        delete_map = st.button("MAP削除", key=f"map_delete_{original_id}")

    if update_map:
        try:
            if not m_id.strip():
                raise ValueError("MAP IDは必須です。")
            spot_values = {
                "id": m_id.strip(),
                "title": m_title,
                "description": m_description,
                "explanation": m_explanation,
                "latitude": float(m_latitude),
                "longitude": float(m_longitude),
                "unlockRadiusMeters": int(m_radius),
                "prefecture": m_prefecture,
                "address": m_address,
                "category": m_category,
                "hint": "",
            }
            if is_db_candidate_spot:
                _update_candidate_map_spot(db, int(spot["_candidate_id"]), spot_values)
            else:
                existing_ids = {str(item.get("id") or "") for item in load_trivia_spots()}
                if m_id != original_id and m_id in existing_ids:
                    raise ValueError(f"MAP ID '{m_id}' は既に使われています。")
                save_trivia_spot(original_id, spot_values)
            st.success("雑学MAPを更新しました。")
            st.rerun()
        except Exception as e:
            st.error(f"MAP更新エラー: {e}")

    if delete_map:
        try:
            if is_db_candidate_spot:
                _hide_candidate_map_spot(db, int(spot["_candidate_id"]))
            else:
                delete_trivia_spot(original_id)
            st.warning("雑学MAPから削除しました。")
            st.rerun()
        except Exception as e:
            st.error(f"MAP削除エラー: {e}")


# Tabs
tab1, tab2, tab3 = st.tabs(["🆕 新規登録", "🤖 AI収集", "🛠️ 管理・編集"])

# --- Tab 1: Register ---
with tab1:
    st.header("新しい雑学を登録")
    
    with st.form("register_form", clear_on_submit=True):
        register_target = st.radio(
            "登録先",
            ["通常の雑学", "新規作成（地図用）", "通常 + 地図"],
            horizontal=True,
            key="new_register_target",
        )
        add_to_normal_trivia = register_target in {"通常の雑学", "通常 + 地図"}
        add_to_trivia_map = register_target in {"新規作成（地図用）", "通常 + 地図"}
        col1, col2 = st.columns([2, 1])
        
        with col1:
            title = st.text_input("タイトル (必須)", max_chars=50, placeholder="例: 富士山の高さ")
            content = st.text_area("本文 (必須)", max_chars=100, height=80, placeholder="雑学のメインコンテンツ。50〜80文字程度で簡潔に。")
            explanation = st.text_area("解説・詳細", height=120, placeholder="詳細な背景や理由など。100〜150文字程度。")

            if add_to_trivia_map:
                st.subheader("雑学MAPの場所")
                map_col1, map_col2 = st.columns(2)
                with map_col1:
                    map_prefecture = st.text_input("都道府県", placeholder="東京都")
                    map_latitude = st.number_input("緯度", min_value=-90.0, max_value=90.0, value=35.6812, format="%.6f")
                with map_col2:
                    map_spot_id = st.text_input("MAP ID（空欄なら自動生成）", placeholder="tokyo_001")
                    map_longitude = st.number_input("経度", min_value=-180.0, max_value=180.0, value=139.7671, format="%.6f")
                map_address = st.text_input("住所・施設名", placeholder="東京都港区芝公園4-2-8 / 東京タワー")
                map_radius = st.number_input("解放半径（メートル）", min_value=10, max_value=5000, value=300, step=10)
                map_hint = ""
            else:
                map_address = ""
                map_prefecture = ""
                map_spot_id = ""
                map_latitude = 0.0
                map_longitude = 0.0
                map_radius = 300
                map_hint = ""
        
        with col2:
            category = st.selectbox("カテゴリ", TRIVIA_CATEGORIES)
            source = st.text_input("ソースURL", placeholder="https://...")
            image_url = st.text_input("写真URL / R2キー", placeholder="https://... または trivia/123.jpg")
            uploaded_image = st.file_uploader(
                "写真をR2へアップロード",
                type=["jpg", "jpeg", "png", "webp", "gif"],
                disabled=bool(r2_unavailable_reason),
            )
            if r2_unavailable_reason:
                st.caption("R2設定が未完了のため、アップロードは無効です。写真URL / R2キーを入力してください。")
            image_crop_mode = st.selectbox("トリミング", list(IMAGE_CROP_OPTIONS.keys()), key="new_image_crop")
            image_to_upload = uploaded_image
            if uploaded_image:
                if image_crop_mode == "アプリ表示サイズ 16:9 手動調整":
                    cropped_image = render_manual_cropper(uploaded_image, "new_manual_crop")
                    if cropped_image is not None:
                        image_to_upload = pil_image_to_upload_file(cropped_image)
                        st.image(image_to_upload, caption="アプリ表示サイズ 16:9 プレビュー", use_container_width=True)
                else:
                    preview_image = get_processed_image_preview(uploaded_image, image_crop_mode)
                    st.image(preview_image or uploaded_image, caption="アップロード予定", use_container_width=True)
            preview_url = normalize_image_url(image_url)
            if preview_url:
                st.image(preview_url, caption="写真プレビュー", use_container_width=True)
            
        submitted = st.form_submit_button("登録する", type="primary")
        
        if submitted:
            if not title or not content:
                st.error("タイトルと本文は必須です。")
            elif not add_to_normal_trivia and not add_to_trivia_map:
                st.error("通常の雑学、雑学MAPのどちらかは選択してください。")
            elif add_to_trivia_map and not map_prefecture:
                st.error("雑学MAPに追加する場合は都道府県を入力してください。")
            elif add_to_trivia_map and not map_address:
                st.error("雑学MAPに追加する場合は住所・施設名を入力してください。")
            else:
                try:
                    messages = []
                    map_spot = None
                    if add_to_trivia_map:
                        map_spot = build_trivia_spot(
                            title=title,
                            description=content,
                            explanation=explanation,
                            spot_id=map_spot_id,
                            latitude=float(map_latitude),
                            longitude=float(map_longitude),
                            unlock_radius_meters=int(map_radius),
                            prefecture=map_prefecture,
                            address=map_address,
                            category=category,
                            hint="",
                        )

                    final_image_url = normalize_image_url(image_url)
                    if add_to_normal_trivia:
                        if image_to_upload:
                            final_image_url = upload_image_to_r2(image_to_upload, crop_mode=None if image_to_upload is not uploaded_image else image_crop_mode)
                        new_trivia = Trivia(
                            title=title,
                            content=content,
                            explanation=explanation,
                            source=source,
                            category=category,
                            image_url=final_image_url,
                            # embedding is null for manual entry
                        )
                        db.add(new_trivia)
                        db.commit()
                        messages.append("通常の雑学")

                    if map_spot:
                        spot_id = append_trivia_spot_to_file(map_spot)
                        messages.append(f"雑学MAP（{spot_id}）")

                    st.success(f"登録しました: {title} → {' / '.join(messages)}")
                except Exception as e:
                    db.rollback()
                    st.error(f"エラーが発生しました: {e}")

# --- Tab 2: AI Collection ---
with tab2:
    st.header("🤖 AIで雑学を収集")

    if not client:
        st.error("APIキーが設定されていません。.envファイルに OPENAI_API_KEY を設定してください。")
    else:
        # Load the shared DB-backed review queue used by both Streamlit and LINE.
        pending_candidates = (
            db.query(TriviaCandidate)
            .filter(TriviaCandidate.status == "pending")
            .order_by(TriviaCandidate.created_at.desc())
            .all()
        )
        st.session_state.ai_trivia_list = [
            {
                "id": candidate.id,
                "title": candidate.title,
                "content": candidate.content,
                "explanation": candidate.explanation,
                "source": candidate.source,
                "category": candidate.category,
                "image_url": candidate.image_url,
                "map_address": candidate.map_address,
                "map_prefecture": candidate.map_prefecture,
                "map_latitude": candidate.map_latitude,
                "map_longitude": candidate.map_longitude,
                "map_radius": candidate.map_radius,
                "map_hint": candidate.map_hint,
                "map_collection": False,
            }
            for candidate in pending_candidates
        ]

        with st.form("ai_gen_form"):
            collection_target = st.radio(
                "収集タイプ",
                ["収集（通常）", "収集（地図用）"],
                horizontal=True,
                key="ai_collection_target",
            )
            col_ai1, col_ai2 = st.columns([3, 1])
            with col_ai1:
                topic = st.text_input("トピック (例: 宇宙, 猫, 歴史)", placeholder="何についての雑学を集めますか？")
            with col_ai2:
                count = st.number_input("生成件数", min_value=1, max_value=10, value=3)
            
            generate_submitted = st.form_submit_button("生成開始", type="primary")

        if generate_submitted:
            map_collection = collection_target == "収集（地図用）"
            target_topic = topic if topic else "ランダムで幅広いジャンル"
            with st.spinner(f"「{target_topic}」に関する{'地図用' if map_collection else '雑学・豆知識'}を {count} 件生成中..."):
                try:
                    # 1. Fetch ALL existing trivia titles to prevent duplicates
                    all_existing_data = db.query(Trivia.title, Trivia.content).all()
                    all_existing_titles = [e[0] for e in all_existing_data]
                    
                    # Also include pending approval items
                    pending_titles = [item.get('title', '') for item in st.session_state.ai_trivia_list if isinstance(item, dict)]
                    
                    exclusion_titles = all_existing_titles + pending_titles
                    exclusion_text = ""
                    if exclusion_titles:
                        exclusion_text = f"\n\n【除外リスト】以下の雑学は既にデータベースに存在します。これらと重複する内容（タイトルやネタ被り、同じ事実の言い換え）は絶対に避けてください：\n" + "\n".join([f"- {t}" for t in exclusion_titles])
                    map_collection_instruction = ""
                    if map_collection:
                        map_collection_instruction = """
                    【最重要：雑学MAP用に収集】
                    - 今回は雑学MAPへ登録できる候補だけを生成してください。
                    - 地名、建物、史跡、駅、橋、公園、神社仏閣、城跡、観光地、地域文化、特定の店や施設など、現地に行ける具体的な場所に紐づく雑学だけを採用してください。
                    - 場所に紐づかない一般雑学は採用しないでください。
                    - map_address、map_prefecture、map_latitude、map_longitude、map_radiusは全件必ず入れてください。
                    - map_addressは「施設名 / 住所」の形を優先してください。
                    - 座標が分からない候補は出力しないでください。
                    """

                    prompt = f"""
                    「{target_topic}」に関する面白い雑学・豆知識を{count}件生成してください。
                    以下のJSONフォーマットのオブジェクト形式で出力してください。
                    キーは "trivia" とし、値はそのリストにしてください。
                    
                    keys = "trivia"
                    
                    【最重要：タイトルについて】
                    タイトルはアプリの「顔」です。タイトルを読むだけで「何の話か」がわかり、かつ「へぇ！面白い！」と思わせるものにしてください。
                    説明的であることは大事ですが、ただの説明で終わらず、意外性・驚き・面白さを必ず詰め込んでください。
                    
                    タイトルのルール：
                    - 30文字以内
                    - タイトルだけで「何の話か」と「面白いポイント」の両方が伝わること
                    - 具体的な数字や意外な事実を盛り込む
                    - 「〜の雑学」「〜の豆知識」のような中身のないタイトルは禁止
                    - ただの事実の要約ではなく、「えっ！？」と驚く切り口で書く
                    
                    良いタイトルの例：
                    ✅「バナナは実はベリーの仲間だった」（内容がわかる＋意外性がある）
                    ✅「宇宙では爆発しても音が聞こえない」（説明的＋驚きがある）
                    ✅「1日の唾液量はペットボトル1本分もある」（具体的な数字＋インパクト）
                    ✅「ハチミツは3000年経っても腐らない」（事実がわかる＋衝撃的）
                    ✅「タコは心臓を3つ持っている」（シンプルだが意外）
                    ✅「金魚の記憶力は実は数ヶ月もある」（常識を覆す面白さ）
                    
                    悪いタイトルの例：
                    ❌「バナナの分類について」（面白さがゼロ）
                    ❌「宇宙空間の特徴」（漠然としている）
                    ❌「唾液に関する雑学」（中身が伝わらない）
                    ❌「心臓」（意味不明）
                    
                    【重要】ソース（出典）は**必ず「http://」または「https://」で始まる有効なURL**にしてください。
                    書籍名だけや、「不明」などの単語はNGです。
                    URLが存在しない場合は、その雑学自体を生成しないでください。
                    地名、建物、史跡、駅、観光地、地域文化など場所に紐づく雑学では、雑学MAP用の住所・都道府県・座標も入れてください。
                    場所に関係しない雑学では、map_address/map_prefectureは空文字、map_latitude/map_longitude/map_radiusはnullにしてください。
                    {map_collection_instruction}
                    
                    【重要】生成する{count}件の雑学は互いに全く異なるテーマ・事実にしてください。同じ事実の言い換えや類似ネタは禁止です。
                    {exclusion_text}

                    {{
                        "trivia": [
                            {{
                                "title": "内容がわかり、かつ面白さ・意外性のあるタイトル（30文字以内）",
                                "content": "本文（です・ます調。50〜80文字程度。改行は含めないでください）",
                                "explanation": "詳細な解説や背景（100〜150文字程度）",
                                "category": f"カテゴリ（{CATEGORIES_STR} から選択）",
                                "source": "https://example.com/article... (必須。http/httpsから始まるURL)",
                                "map_address": "雑学MAPに置ける具体的な住所や施設名。場所に関係しない雑学なら空文字",
                                "map_prefecture": "都道府県。場所に関係しない雑学なら空文字",
                                "map_latitude": 35.6812,
                                "map_longitude": 139.7671,
                                "map_radius": 300,
                                "map_hint": ""
                            }}
                        ]
                    }}
                    """
                    
                    response = client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {"role": "system", "content": "You are a trivia content creator for a mobile app. Your #1 priority is writing titles that make people stop scrolling and think 'Wait, what!?' - titles must be specific, surprising, and instantly intriguing. You always provide reliable sources. Never generate duplicate or similar trivia. Output in JSON format."},
                            {"role": "user", "content": prompt}
                        ],
                        response_format={"type": "json_object"}
                    )
                    text_response = response.choices[0].message.content.strip()
                    # Remove markdown code blocks if present
                    if text_response.startswith("```json"):
                        text_response = text_response[7:-3].strip()
                    elif text_response.startswith("```"):
                        text_response = text_response[3:-3].strip()
                    
                    data = json.loads(text_response)
                    new_items = data.get("trivia", [])
                    
                    # 2. Filter out duplicates (check against ALL titles and Content using Fuzzy Match)
                    unique_items = []
                    duplicates_count = 0
                    
                    for item in new_items:
                        if not isinstance(item, dict):
                            continue
                            
                        is_duplicate = False
                        new_title = item.get("title", "")
                        new_content = item.get("content", "")
                        
                        # Check against DB entries
                        for db_title, db_content in all_existing_data:
                            title_ratio = difflib.SequenceMatcher(None, new_title, db_title).ratio()
                            content_ratio = difflib.SequenceMatcher(None, new_content, db_content).ratio()
                            
                            # Threshold: 0.7 (70% similar) - stricter to catch paraphrases
                            if title_ratio > 0.7 or content_ratio > 0.7:
                                is_duplicate = True
                                break
                        
                        # Check against pending approval list
                        if not is_duplicate:
                            for pending in st.session_state.ai_trivia_list:
                                if not isinstance(pending, dict):
                                    continue
                                p_title = pending.get("title", "")
                                p_content = pending.get("content", "")
                                if difflib.SequenceMatcher(None, new_title, p_title).ratio() > 0.7 or \
                                   difflib.SequenceMatcher(None, new_content, p_content).ratio() > 0.7:
                                    is_duplicate = True
                                    break
                        
                        # Check against items already accepted in this batch
                        if not is_duplicate:
                            for accepted in unique_items:
                                a_title = accepted.get("title", "")
                                a_content = accepted.get("content", "")
                                if difflib.SequenceMatcher(None, new_title, a_title).ratio() > 0.7 or \
                                   difflib.SequenceMatcher(None, new_content, a_content).ratio() > 0.7:
                                    is_duplicate = True
                                    break
                        
                        if not is_duplicate:
                            if map_collection and not (
                                item.get("map_address")
                                and item.get("map_prefecture")
                                and item.get("map_latitude") is not None
                                and item.get("map_longitude") is not None
                                and item.get("map_radius") is not None
                            ):
                                duplicates_count += 1
                                continue
                            item["map_collection"] = map_collection
                            unique_items.append(item)
                        else:
                            duplicates_count += 1
                    
                    saved_candidates = create_candidates(db, unique_items)
                    st.session_state.ai_trivia_list.extend([
                        {
                            "id": candidate.id,
                            "title": candidate.title,
                            "content": candidate.content,
                            "explanation": candidate.explanation,
                            "source": candidate.source,
                            "category": candidate.category,
                            "image_url": candidate.image_url,
                            "map_address": candidate.map_address,
                            "map_prefecture": candidate.map_prefecture,
                            "map_latitude": candidate.map_latitude,
                            "map_longitude": candidate.map_longitude,
                            "map_radius": candidate.map_radius,
                            "map_hint": candidate.map_hint,
                            "map_collection": map_collection,
                        }
                        for candidate in saved_candidates
                    ])
                    
                    msg = f"{len(unique_items)} 件生成しました！下のリストから確認・承認してください。"
                    if duplicates_count > 0:
                        msg += f" (※重複・類似 {duplicates_count} 件を除外しました)"
                    st.success(msg)
                except Exception as e:
                    st.error(f"生成エラー: {e}")

        st.divider()
        st.subheader("承認待ちリスト")
        
        if st.button("リストをクリア"):
            for item in st.session_state.ai_trivia_list:
                candidate_id = item.get("id")
                if candidate_id:
                    reject_candidate(db, candidate_id, "streamlit:clear")
            st.session_state.ai_trivia_list = []
            st.rerun()

        if not st.session_state.ai_trivia_list:
            st.info("承認待ちの雑学はありません。")
        else:
            # Display items (iterate copy to modify original)
            for i, item in enumerate(st.session_state.ai_trivia_list):
                if not isinstance(item, dict):
                    continue
                
                # Validate URL status
                source_url = item.get('source', '')
                url_status_icon = "❓"
                url_status_msg = "未チェック"
                
                if source_url.startswith("http"):
                    try:
                        r = requests.head(source_url, timeout=3)
                        if r.status_code == 200:
                            url_status_icon = "✅"
                            url_status_msg = "OK"
                        else:
                            url_status_icon = "⚠️"
                            url_status_msg = f"Status: {r.status_code}"
                    except:
                        url_status_icon = "❌"
                        url_status_msg = "接続不可"
                else:
                    url_status_icon = "🚫"
                    url_status_msg = "無効なURL"

                with st.expander(f"WAITING: {item.get('title', '無題')}", expanded=True):
                    with st.form(f"approve_form_{i}"):
                        c1, c2 = st.columns([2, 1])
                        with c1:
                            a_title = st.text_input("タイトル", item.get('title', ''))
                            a_content = st.text_area("本文", item.get('content', ''), height=100)
                            a_explanation = st.text_area("解説", item.get('explanation', ''))
                        with c2:
                            a_category = st.selectbox("カテゴリ", TRIVIA_CATEGORIES, index=TRIVIA_CATEGORIES.index(item.get('category', '一般')) if item.get('category') in TRIVIA_CATEGORIES else TRIVIA_CATEGORIES.index("その他"))
                            st.caption(f"ソース確認: {url_status_icon} {url_status_msg}")
                            a_source = st.text_input("ソース", source_url)
                            a_image_url = st.text_input("写真URL / R2キー", item.get('image_url', ''))
                            a_uploaded_image = st.file_uploader(
                                "写真をR2へアップロード",
                                type=["jpg", "jpeg", "png", "webp", "gif"],
                                key=f"ai_image_upload_{i}",
                                disabled=bool(r2_unavailable_reason),
                            )
                            if r2_unavailable_reason:
                                st.caption("R2設定が未完了のため、アップロードは無効です。写真URL / R2キーを入力してください。")
                            a_image_crop_mode = st.selectbox("トリミング", list(IMAGE_CROP_OPTIONS.keys()), key=f"ai_image_crop_{i}")
                            a_image_to_upload = a_uploaded_image
                            if a_uploaded_image:
                                if a_image_crop_mode == "アプリ表示サイズ 16:9 手動調整":
                                    a_cropped_image = render_manual_cropper(a_uploaded_image, f"ai_manual_crop_{i}")
                                    if a_cropped_image is not None:
                                        a_image_to_upload = pil_image_to_upload_file(a_cropped_image)
                                        st.image(a_image_to_upload, caption="アプリ表示サイズ 16:9 プレビュー", use_container_width=True)
                                else:
                                    a_preview_image = get_processed_image_preview(a_uploaded_image, a_image_crop_mode)
                                    st.image(a_preview_image or a_uploaded_image, caption="アップロード予定", use_container_width=True)
                            a_preview_url = normalize_image_url(a_image_url)
                            if a_preview_url:
                                st.image(a_preview_url, caption="写真プレビュー", use_container_width=True)

                        st.divider()
                        item_map_collection = bool(item.get("map_collection"))
                        a_add_to_normal = st.checkbox("通常の雑学に追加する", value=not item_map_collection, key=f"ai_normal_{i}")
                        a_add_to_map = st.checkbox(
                            "雑学MAPに追加する",
                            value=item_map_collection or bool(item.get("map_prefecture") and item.get("map_latitude") and item.get("map_longitude")),
                            key=f"ai_map_{i}",
                        )
                        if a_add_to_map:
                            map_ai1, map_ai2 = st.columns(2)
                            with map_ai1:
                                a_map_prefecture = st.text_input("都道府県", value=item.get("map_prefecture") or "", key=f"ai_map_prefecture_{i}")
                                a_map_latitude = st.number_input(
                                    "緯度",
                                    min_value=-90.0,
                                    max_value=90.0,
                                    value=float(item.get("map_latitude") or 35.6812),
                                    format="%.6f",
                                    key=f"ai_map_latitude_{i}",
                                )
                            with map_ai2:
                                a_map_spot_id = st.text_input("MAP ID（空欄なら自動生成）", key=f"ai_map_spot_id_{i}", placeholder="tokyo_001")
                                a_map_longitude = st.number_input(
                                    "経度",
                                    min_value=-180.0,
                                    max_value=180.0,
                                    value=float(item.get("map_longitude") or 139.7671),
                                    format="%.6f",
                                    key=f"ai_map_longitude_{i}",
                                )
                            a_map_address = st.text_input("住所・施設名", value=item.get("map_address") or "", key=f"ai_map_address_{i}")
                            a_map_radius = st.number_input("解放半径（メートル）", min_value=10, max_value=5000, value=int(item.get("map_radius") or 300), step=10, key=f"ai_map_radius_{i}")
                            a_map_hint = ""
                        else:
                            a_map_prefecture = ""
                            a_map_latitude = 0.0
                            a_map_spot_id = ""
                            a_map_longitude = 0.0
                            a_map_address = ""
                            a_map_radius = 300
                            a_map_hint = ""
                        
                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            approve = st.form_submit_button("✅ 選択した保存先に登録", type="primary")
                        with btn_col2:
                            reject = st.form_submit_button("🗑️ 削除（却下）")

                        if approve:
                            try:
                                if not a_add_to_normal and not a_add_to_map:
                                    raise ValueError("通常の雑学、雑学MAPのどちらかは選択してください。")
                                map_spot = None
                                if a_add_to_map:
                                    map_spot = build_trivia_spot(
                                        title=a_title,
                                        description=a_content,
                                        explanation=a_explanation,
                                        prefecture=a_map_prefecture,
                                        address=a_map_address,
                                        latitude=float(a_map_latitude),
                                        longitude=float(a_map_longitude),
                                        category=a_category,
                                        spot_id=a_map_spot_id,
                                        unlock_radius_meters=int(a_map_radius),
                                        hint=a_map_hint,
                                    )
                                final_image_url = normalize_image_url(a_image_url)
                                if a_image_to_upload:
                                    final_image_url = upload_image_to_r2(a_image_to_upload, crop_mode=None if a_image_to_upload is not a_uploaded_image else a_image_crop_mode)
                                candidate_id = item.get("id")
                                if not candidate_id:
                                    saved = create_candidates(db, [{
                                        "title": a_title,
                                        "content": a_content,
                                        "explanation": a_explanation,
                                        "source": a_source,
                                        "category": a_category,
                                        "image_url": final_image_url,
                                        "map_address": a_map_address,
                                        "map_prefecture": a_map_prefecture,
                                        "map_latitude": a_map_latitude if a_add_to_map else None,
                                        "map_longitude": a_map_longitude if a_add_to_map else None,
                                        "map_radius": a_map_radius if a_add_to_map else None,
                                        "map_hint": a_map_hint,
                                    }])
                                    candidate_id = saved[0].id
                                update_candidate(
                                    db,
                                    candidate_id,
                                    title=a_title,
                                    content=a_content,
                                    explanation=a_explanation,
                                    source=a_source,
                                    category=a_category,
                                    image_url=final_image_url,
                                    map_address=a_map_address,
                                    map_prefecture=a_map_prefecture,
                                    map_latitude=a_map_latitude if a_add_to_map else None,
                                    map_longitude=a_map_longitude if a_add_to_map else None,
                                    map_radius=a_map_radius if a_add_to_map else None,
                                    map_hint=a_map_hint,
                                )
                                messages = []
                                if a_add_to_normal:
                                    approve_candidate(db, candidate_id, "streamlit")
                                    messages.append("通常の雑学")
                                elif candidate_id:
                                    reject_candidate(db, candidate_id, "streamlit:map-only")
                                if map_spot:
                                    spot_id = append_trivia_spot_to_file(map_spot)
                                    messages.append(f"雑学MAP（{spot_id}）")
                                st.session_state.ai_trivia_list.pop(i)
                                st.success(f"登録しました: {' / '.join(messages)}")
                                st.rerun()
                            except Exception as e:
                                st.error(f"保存エラー: {e}")
                        
                        if reject:
                            candidate_id = item.get("id")
                            if candidate_id:
                                reject_candidate(db, candidate_id, "streamlit")
                            st.session_state.ai_trivia_list.pop(i)
                            st.warning("削除しました。")
                            st.rerun()

# --- Tab 3: Manage ---
with tab3:
    st.header("既存の雑学を管理")
    manage_target = st.radio(
        "管理対象",
        ["通常の雑学", "雑学MAP"],
        horizontal=True,
        key="manage_target",
    )
    if manage_target == "雑学MAP":
        render_trivia_map_admin()
        st.stop()
    
    # --- Maintenance Section ---
    with st.expander("🔧 データメンテナンス (ソースURL修正)", expanded=False):
        st.write("ソースがURL(http/https)形式でないデータを検出し、AIで再検索して修正します。")
        
        invalid_source_query = db.query(Trivia).filter(
            or_(
                Trivia.source.is_(None),
                and_(
                    ~Trivia.source.startswith("http://"),
                    ~Trivia.source.startswith("https://"),
                ),
            )
        )
        invalid_source_count = invalid_source_query.count()
        
        st.write(f"修正対象: **{invalid_source_count}** 件")
        
        if invalid_source_count:
            if st.button("♻️ ソース自動修正を開始 (OpenAI)"):
                invalid_source_items = invalid_source_query.order_by(Trivia.id.desc()).limit(100).all()
                progress_bar = st.progress(0)
                status_text = st.empty()
                
                for i, item in enumerate(invalid_source_items):
                    status_text.text(f"処理中 ({i+1}/{len(invalid_source_items)}): {item.title}")
                    try:
                        # Ask OpenAI for a source URL
                        repair_prompt = f"""
                        以下の雑学に対応する、信頼できる情報源のURLを1つ教えてください。
                        
                        タイトル: {item.title}
                        内容: {item.content}
                        
                        出力はJSON形式で、キーは "source_url" とし、値はURL文字列のみにしてください。
                        解説等は不要です。URLが見つからない場合は空文字を返してください。
                        """
                        
                        rep_response = client.chat.completions.create(
                            model="gpt-4o-mini", # Use mini for batch processing to save cost
                            messages=[
                                {"role": "system", "content": "You are a researcher. You provide direct URLs to sources."},
                                {"role": "user", "content": repair_prompt}
                            ],
                            response_format={"type": "json_object"}
                        )
                        
                        rep_content = rep_response.choices[0].message.content.strip()
                        rep_json = json.loads(rep_content)
                        new_url = rep_json.get("source_url", "")
                        
                        if new_url and (new_url.startswith("http://") or new_url.startswith("https://")):
                            item.source = new_url
                            db.commit()
                        else:
                            # Keep original if no valid URL found, or maybe mark it? 
                            # For now, just skip updating if invalid
                            pass
                            
                    except Exception as e:
                        st.error(f"Error processing {item.title}: {e}")
                    
                    progress_bar.progress((i + 1) / len(invalid_source_items))
                
                st.success("修正処理が完了しました！")
                st.rerun()

    st.divider()
    
    search_query = st.text_input("🔍 検索 (タイトルまたは本文)", "")
    page_size = st.selectbox("表示件数", [10, 20, 50], index=1)

    query = db.query(Trivia)
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(Trivia.title.like(search) | Trivia.content.like(search))

    total_count = query.count()
    max_page = max(1, (total_count + page_size - 1) // page_size)
    page = st.number_input("ページ", min_value=1, max_value=max_page, value=1, step=1)
    offset = (page - 1) * page_size
    trivias = query.order_by(Trivia.id.desc()).offset(offset).limit(page_size).all()

    st.write(f"全 {total_count} 件 / {page} / {max_page} ページ")

    if not trivias:
        st.info("データが見つかりません。")
    else:
        item_labels = {
            f"{t.id}: {t.title} ({t.category})": t.id
            for t in trivias
        }
        selected_label = st.selectbox("編集する雑学", list(item_labels.keys()))
        selected_id = item_labels[selected_label]
        trivia = db.query(Trivia).filter(Trivia.id == selected_id).first()

        if trivia:
            st.subheader(f"編集: {trivia.id} / {trivia.title}")
            with st.container():
                e_title = st.text_input("タイトル", trivia.title)
                e_content = st.text_area("本文", trivia.content)
                e_explanation = st.text_area("解説", trivia.explanation)
                col_e1, col_e2 = st.columns(2)
                with col_e1:
                    e_category = st.selectbox("カテゴリ", TRIVIA_CATEGORIES, index=TRIVIA_CATEGORIES.index(trivia.category) if trivia.category in TRIVIA_CATEGORIES else TRIVIA_CATEGORIES.index("その他"))
                with col_e2:
                    e_source = st.text_input("ソースURL", trivia.source)
                    e_image_url = st.text_input("写真URL / R2キー", trivia.image_url or "")
                    e_uploaded_image = st.file_uploader(
                        "写真をR2へアップロード",
                        type=["jpg", "jpeg", "png", "webp", "gif"],
                        key=f"edit_image_upload_{trivia.id}",
                        disabled=bool(r2_unavailable_reason),
                    )
                    if r2_unavailable_reason:
                        st.caption("R2設定が未完了のため、アップロードは無効です。写真URL / R2キーを入力してください。")
                    e_image_crop_mode = st.selectbox("トリミング", list(IMAGE_CROP_OPTIONS.keys()), key=f"edit_image_crop_{trivia.id}")
                    e_image_to_upload = e_uploaded_image
                    e_existing_crop_image = None
                    if e_uploaded_image:
                        if e_image_crop_mode == "アプリ表示サイズ 16:9 手動調整":
                            e_cropped_image = render_manual_cropper(e_uploaded_image, f"edit_manual_crop_{trivia.id}")
                            if e_cropped_image is not None:
                                e_image_to_upload = pil_image_to_upload_file(e_cropped_image)
                                st.image(e_image_to_upload, caption="アプリ表示サイズ 16:9 プレビュー", use_container_width=True)
                        else:
                            e_upload_preview_image = get_processed_image_preview(e_uploaded_image, e_image_crop_mode)
                            st.image(e_upload_preview_image or e_uploaded_image, caption="アップロード予定", use_container_width=True)
                    e_preview_url = normalize_image_url(e_image_url)
                    if e_preview_url:
                        st.image(e_preview_url, caption="写真プレビュー", use_container_width=True)
                        if e_image_crop_mode == "アプリ表示サイズ 16:9 手動調整" and not e_uploaded_image:
                            try:
                                existing_image_file = download_image_for_processing(e_image_url)
                                e_existing_crop_image = render_manual_cropper(existing_image_file, f"existing_manual_crop_{trivia.id}")
                                if e_existing_crop_image is not None:
                                    st.image(e_existing_crop_image, caption="アプリ表示サイズ 16:9 プレビュー", use_container_width=True)
                            except Exception as e:
                                st.error(f"既存写真の読み込みエラー: {e}")

                with st.expander("この雑学を雑学MAPに登録"):
                    map_e1, map_e2 = st.columns(2)
                    with map_e1:
                        e_map_prefecture = st.text_input("都道府県", key=f"edit_map_prefecture_{trivia.id}", placeholder="東京都")
                        e_map_latitude = st.number_input("緯度", min_value=-90.0, max_value=90.0, value=35.6812, format="%.6f", key=f"edit_map_latitude_{trivia.id}")
                    with map_e2:
                        e_map_spot_id = st.text_input("MAP ID（空欄なら自動生成）", key=f"edit_map_spot_id_{trivia.id}", placeholder="tokyo_001")
                        e_map_longitude = st.number_input("経度", min_value=-180.0, max_value=180.0, value=139.7671, format="%.6f", key=f"edit_map_longitude_{trivia.id}")
                    e_map_address = st.text_input("住所・施設名", key=f"edit_map_address_{trivia.id}", placeholder="東京都港区芝公園4-2-8 / 東京タワー")
                    e_map_radius = st.number_input("解放半径（メートル）", min_value=10, max_value=5000, value=300, step=10, key=f"edit_map_radius_{trivia.id}")
                    e_map_hint = ""
                    map_register_submit = st.button("雑学MAPに登録", key=f"map_register_{trivia.id}")

                col_act1, col_act2, col_act3, col_act4 = st.columns([1, 1.7, 1, 3])
                with col_act1:
                    update_submit = st.button("更新", key=f"update_{trivia.id}")
                with col_act2:
                    recrop_submit = st.button("既存写真をトリミング保存", key=f"recrop_{trivia.id}")
                with col_act3:
                    image_delete_submit = st.button("写真削除", key=f"image_delete_{trivia.id}")
                with col_act4:
                    delete_submit = st.button("削除", type="primary", key=f"delete_{trivia.id}")

                if map_register_submit:
                    try:
                        spot_id = append_trivia_to_map(
                            title=e_title,
                            description=e_content,
                            explanation=e_explanation,
                            prefecture=e_map_prefecture,
                            address=e_map_address,
                            latitude=float(e_map_latitude),
                            longitude=float(e_map_longitude),
                            category=e_category,
                            spot_id=e_map_spot_id,
                            unlock_radius_meters=int(e_map_radius),
                            hint=e_map_hint,
                        )
                        st.success(f"雑学MAPに登録しました: {spot_id}")
                    except Exception as e:
                        st.error(f"MAP登録エラー: {e}")

                if update_submit:
                    try:
                        trivia.title = e_title
                        trivia.content = e_content
                        trivia.explanation = e_explanation
                        trivia.category = e_category
                        trivia.source = e_source
                        final_image_url = normalize_image_url(e_image_url)
                        if e_image_to_upload:
                            final_image_url = upload_image_to_r2(e_image_to_upload, trivia.id, crop_mode=None if e_image_to_upload is not e_uploaded_image else e_image_crop_mode)
                        trivia.image_url = final_image_url
                        db.commit()
                        st.success("更新しました！")
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"更新エラー: {e}")

                if recrop_submit:
                    try:
                        current_image_url = e_image_url or trivia.image_url or ""
                        if e_existing_crop_image is not None:
                            existing_image = pil_image_to_upload_file(e_existing_crop_image)
                            final_image_url = upload_image_to_r2(existing_image, trivia.id)
                        else:
                            existing_image = download_image_for_processing(current_image_url)
                            final_image_url = upload_image_to_r2(existing_image, trivia.id, crop_mode=e_image_crop_mode)
                        trivia.image_url = final_image_url
                        db.commit()
                        st.success("既存写真をトリミングして保存しました。")
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"既存写真トリミングエラー: {e}")

                if image_delete_submit:
                    try:
                        deleted_from_r2 = delete_image_from_r2(trivia.image_url or "")
                        trivia.image_url = ""
                        db.commit()
                        if deleted_from_r2:
                            st.success("写真をR2とDBから削除しました。")
                        else:
                            st.success("DBの写真URLを削除しました。R2側は未削除または既に削除済みです。")
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"写真削除エラー: {e}")

                if delete_submit:
                    try:
                        db.query(DailyAssignment).filter(DailyAssignment.trivia_id == trivia.id).delete()
                        db.query(CollectionItem).filter(CollectionItem.trivia_id == trivia.id).delete()
                        db.query(TriviaHee).filter(TriviaHee.trivia_id == trivia.id).delete()
                        db.query(TriviaCandidate).filter(
                            TriviaCandidate.published_trivia_id == trivia.id
                        ).update(
                            {
                                TriviaCandidate.published_trivia_id: None,
                            },
                            synchronize_session=False,
                        )
                        db.delete(trivia)
                        db.commit()
                        st.warning("削除しました。")
                        st.rerun()
                    except Exception as e:
                        db.rollback()
                        st.error(f"削除エラー: {e}")

# Footer
st.divider()
st.caption("Daily Trivia Admin Tool v1.0")
