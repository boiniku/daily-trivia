"""Streamlit entry point for the trivia administration dashboard."""
import os
import socket
import sys
from io import BytesIO

from dotenv import load_dotenv
import requests
import streamlit as st
from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError

try:
    import boto3
    from botocore.config import Config as BotoConfig
except ImportError:
    boto3 = None
    BotoConfig = None

from database import SessionLocal
from services.admin_images import (
    MAX_UPLOAD_BYTES,
    build_unique_image_key,
    image_url_for_key,
    normalize_image_reference,
    optimize_image_upload,
    r2_object_key,
)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "").strip()
ADMIN_DASHBOARD_PASSWORD = os.getenv("ADMIN_DASHBOARD_PASSWORD", "")
TRIVIA_IMAGE_R2_BASE_URL = os.getenv("TRIVIA_IMAGE_R2_BASE_URL", "").strip().rstrip("/")
R2_ENDPOINT_URL = os.getenv("R2_ENDPOINT_URL", "").strip()
R2_ACCESS_KEY_ID = os.getenv("R2_ACCESS_KEY_ID", "").strip()
R2_SECRET_ACCESS_KEY = os.getenv("R2_SECRET_ACCESS_KEY", "").strip()
R2_BUCKET_NAME = os.getenv("R2_BUCKET_NAME", "").strip()
R2_PREFIX = os.getenv("R2_TRIVIA_IMAGE_PREFIX", "trivia").strip().strip("/")
TRIVIA_IMAGE_MAX_DIMENSION = int(os.getenv("TRIVIA_IMAGE_MAX_DIMENSION", "1600"))
TRIVIA_IMAGE_WEBP_QUALITY = int(os.getenv("TRIVIA_IMAGE_WEBP_QUALITY", "78"))
IMAGE_CROP_OPTIONS = {
    "トリミングなし": None,
    "正方形": 1,
    "横長 4:3": 4 / 3,
    "横長 16:9": 16 / 9,
    "アプリ表示サイズ 16:9 手動調整": "manual_16_9",
}


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

def prepare_image_for_r2(img):
    img.thumbnail(
        (TRIVIA_IMAGE_MAX_DIMENSION, TRIVIA_IMAGE_MAX_DIMENSION),
        Image.Resampling.LANCZOS,
    )

    if img.mode not in ("RGB", "RGBA"):
        img = img.convert("RGBA" if "A" in img.getbands() or "transparency" in img.info else "RGB")

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
    data = uploaded_file.read(MAX_UPLOAD_BYTES + 1)
    uploaded_file.seek(0)
    if not data or len(data) > MAX_UPLOAD_BYTES:
        raise ValueError("画像は空でない12MB以下のファイルを選択してください。")
    with Image.open(BytesIO(data)) as img:
        return ImageOps.exif_transpose(img).copy()

def pil_image_to_upload_file(img):
    image_stream = prepare_image_for_r2(img.copy())
    image_stream.seek(0)
    return image_stream

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


def optimize_image_for_r2(uploaded_file, crop_mode=None):
    ratio = IMAGE_CROP_OPTIONS.get(crop_mode)
    return optimize_image_upload(
        uploaded_file, aspect_ratio=ratio if isinstance(ratio, (int, float)) else None,
        max_dimension=TRIVIA_IMAGE_MAX_DIMENSION, quality=TRIVIA_IMAGE_WEBP_QUALITY,
    )


def upload_image_to_r2(uploaded_file, trivia_id=None, crop_mode=None):
    client = get_r2_client()
    if client is None:
        raise RuntimeError(f"R2を利用できません: {get_r2_unavailable_reason()}")
    stream, extension, content_type = optimize_image_for_r2(uploaded_file, crop_mode)
    object_key = build_unique_image_key(R2_PREFIX, trivia_id, extension)
    client.put_object(
        Bucket=R2_BUCKET_NAME, Key=object_key, Body=stream.getvalue(), ContentType=content_type,
        CacheControl="public, max-age=31536000, immutable",
    )
    return image_url_for_key(object_key, TRIVIA_IMAGE_R2_BASE_URL)


def get_r2_object_key(value):
    return r2_object_key(value, TRIVIA_IMAGE_R2_BASE_URL)


def normalize_image_url(value):
    return normalize_image_reference(value, TRIVIA_IMAGE_R2_BASE_URL)


@st.cache_resource(show_spinner=False)
def ensure_admin_schema(schema_revision: str):
    # Schema initialization is independent of widget reruns.
    from scripts.migrations.migrate_trivia_candidates import migrate
    migrate()
    return True


def main():
    st.set_page_config(page_title="毎日雑学 管理ツール", layout="wide", page_icon="📝")
    require_admin_password()
    st.title("📝 毎日雑学 管理ツール")
    with st.sidebar.expander("接続・画像の設定"):
        st.caption("同じWi-Fiの端末から接続する場合は --server.address 0.0.0.0 で起動してください。")
        st.code(f"http://{get_lan_ip()}:8501")
        if TRIVIA_IMAGE_R2_BASE_URL:
            st.caption(f"画像の公開URL: {TRIVIA_IMAGE_R2_BASE_URL}")
        reason = get_r2_unavailable_reason()
        if reason:
            st.warning(f"R2アップロード・画像候補を利用できません: {reason}")
    if ADMIN_DASHBOARD_PASSWORD and st.sidebar.button("ログアウト"):
        st.session_state.clear()
        st.rerun()
    try:
        ensure_admin_schema("ordered-images-with-credits-v4")
        with SessionLocal() as db:
            db.execute(text("SELECT 1"))
            from admin_views import render_dashboard
            render_dashboard(db, sys.modules[__name__])
    except SQLAlchemyError:
        st.error("データベースに接続できないか、読み込みに失敗しました。接続設定を確認して再読み込みしてください。")
        st.info("DATABASE_URLとデータベースの稼働状態を確認してください。入力内容はそのまま保持されます。")
    st.divider()
    st.caption("Daily Trivia Admin Tool")


main()
