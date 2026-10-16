"""Image preparation and an explicitly loaded, read-only R2 image picker.

Streamlit is injected into the picker so importing the pure helpers does not run
the dashboard or initialize credentials, a database connection, or an R2 client.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from io import BytesIO
import math
from pathlib import PurePosixPath
from urllib.parse import quote, unquote, urlsplit
from uuid import uuid4

from PIL import Image, ImageOps, UnidentifiedImageError


MAX_UPLOAD_BYTES = 12 * 1024 * 1024
IMAGE_EXTENSIONS = frozenset({".jpg", ".jpeg", ".png", ".webp", ".gif", ".avif"})


@dataclass(frozen=True)
class R2Image:
    key: str
    size: int
    last_modified: object = None


@dataclass(frozen=True)
class R2ImagePage:
    images: tuple[R2Image, ...]
    next_token: str | None
    scanned_count: int


def _clean_object_key(value: str) -> str:
    key = value.lstrip("/")
    if not key or any(ord(character) < 32 for character in key):
        raise ValueError("R2キーを正しく入力してください。")
    if any(part in {".", ".."} for part in key.split("/")) or "\\" in key:
        raise ValueError("R2キーに相対パスやバックスラッシュは使用できません。")
    return key


def image_url_for_key(object_key: str, base_url: str = "") -> str:
    """Build a durable image reference; a signed URL must never be saved."""
    key = _clean_object_key(object_key)
    base = (base_url or "").strip().rstrip("/")
    return f"{base}/{quote(key, safe='/')}" if base else key


def r2_object_key(value: str, base_url: str = "") -> str:
    """Extract a key only from a bare key or this bucket's public base URL."""
    value = (value or "").strip()
    if not value or value.startswith("//"):
        return ""
    try:
        parsed = urlsplit(value)
    except ValueError:
        return ""
    if parsed.scheme:
        if parsed.scheme.lower() not in {"http", "https"} or not base_url:
            return ""
        try:
            base = urlsplit(base_url.strip().rstrip("/"))
        except ValueError:
            return ""
        if (
            parsed.scheme.lower() != base.scheme.lower()
            or parsed.netloc.lower() != base.netloc.lower()
            or parsed.username
            or parsed.password
        ):
            return ""
        base_path = base.path.rstrip("/") + "/"
        if not parsed.path.startswith(base_path):
            return ""
        value = unquote(parsed.path[len(base_path):])
    try:
        return _clean_object_key(value)
    except ValueError:
        return ""


def normalize_image_reference(value: str, base_url: str = "") -> str:
    value = (value or "").strip()
    if not value:
        return ""
    if any(ord(character) < 32 for character in value):
        raise ValueError("写真URLやR2キーに改行・制御文字は使用できません。")
    try:
        parsed = urlsplit(value)
        # Accessing port also validates malformed and out-of-range port values.
        parsed.port
    except ValueError as exc:
        raise ValueError("写真URLの形式が不正です。") from exc
    if parsed.scheme:
        if (
            parsed.scheme.lower() not in {"http", "https"}
            or not parsed.netloc
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or any(character.isspace() for character in parsed.netloc)
        ):
            raise ValueError("写真は有効なhttp/https URLまたはR2キーを指定してください。")
        return value
    if value.startswith("//"):
        raise ValueError("写真URLはhttp://またはhttps://から入力してください。")
    return image_url_for_key(value, base_url)


def build_unique_image_key(prefix: str, trivia_id: int | None, extension: str) -> str:
    extension = (extension or "").lower()
    if extension not in IMAGE_EXTENSIONS:
        raise ValueError("対応していない画像形式です。")
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S%f")
    object_name = f"{trivia_id if trivia_id is not None else 'new'}-{timestamp}-{uuid4().hex[:12]}{extension}"
    prefix = (prefix or "").strip().strip("/")
    return _clean_object_key(f"{prefix}/{object_name}" if prefix else object_name)


def _image_stream(data: bytes, extension: str, content_type: str) -> BytesIO:
    result = BytesIO(data)
    result.name = f"image{extension}"
    result.type = content_type
    return result


def optimize_image_upload(
    uploaded_file,
    aspect_ratio: float | None = None,
    *,
    max_dimension: int = 1600,
    quality: int = 78,
    max_upload_bytes: int = MAX_UPLOAD_BYTES,
) -> tuple[BytesIO, str, str]:
    """Validate bytes, apply the requested crop, and prepare a safe image upload.

    A requested crop, orientation correction, or resize is retained even when
    WebP encoding makes a very small source file larger.
    """
    if max_dimension < 1 or not 1 <= quality <= 100:
        raise ValueError("画像サイズ・画質の設定が不正です。")
    if aspect_ratio is not None and (not math.isfinite(aspect_ratio) or aspect_ratio <= 0):
        raise ValueError("トリミングの縦横比が不正です。")
    uploaded_file.seek(0)
    original = uploaded_file.read(max_upload_bytes + 1)
    uploaded_file.seek(0)
    if not original:
        raise ValueError("画像が空です。")
    if len(original) > max_upload_bytes:
        raise ValueError(f"画像は{max_upload_bytes // (1024 * 1024)}MB以下にしてください。")
    try:
        with Image.open(BytesIO(original)) as source:
            source_format = source.format
            orientation = source.getexif().get(274, 1)
            image = ImageOps.exif_transpose(source)
            must_process = aspect_ratio is not None or orientation != 1 or max(image.size) > max_dimension
            # Preserve animation when no edit was requested. Cropping explicitly
            # produces a still WebP, just as other dashboard crop operations do.
            if source_format == "GIF" and aspect_ratio is None:
                return _image_stream(original, ".gif", "image/gif"), ".gif", "image/gif"
            if aspect_ratio is not None:
                width, height = image.size
                if width / height > aspect_ratio:
                    cropped_width = max(1, int(height * aspect_ratio))
                    left = (width - cropped_width) // 2
                    image = image.crop((left, 0, left + cropped_width, height))
                else:
                    cropped_height = max(1, int(width / aspect_ratio))
                    top = (height - cropped_height) // 2
                    image = image.crop((0, top, width, top + cropped_height))
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            if image.mode not in {"RGB", "RGBA"}:
                has_transparency = "A" in image.getbands() or "transparency" in image.info
                image = image.convert("RGBA" if has_transparency else "RGB")
            output = BytesIO()
            image.save(output, format="WEBP", quality=quality, method=6)
            optimized = output.getvalue()
            source_metadata = {
                "JPEG": (".jpg", "image/jpeg"),
                "PNG": (".png", "image/png"),
                "WEBP": (".webp", "image/webp"),
            }.get(source_format)
            if not must_process and source_metadata and len(optimized) >= len(original):
                extension, content_type = source_metadata
                return _image_stream(original, extension, content_type), extension, content_type
            return _image_stream(optimized, ".webp", "image/webp"), ".webp", "image/webp"
    except (OSError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise ValueError("画像を読み込めませんでした。有効な画像ファイルを選択してください。") from exc


def list_r2_images(
    client,
    bucket: str,
    *,
    prefix: str = "",
    search: str = "",
    continuation_token: str | None = None,
    page_size: int = 12,
    max_scan_pages: int = 5,
) -> R2ImagePage:
    """Read a bounded page of image candidates without downloading objects.

    Filtering may scan several R2 pages. The continuation token always follows
    the last fully consumed response, so matching images are never skipped.
    """
    if not bucket:
        raise ValueError("R2バケットが設定されていません。")
    if not 1 <= page_size <= 100 or not 1 <= max_scan_pages <= 20:
        raise ValueError("画像一覧のページ設定が不正です。")
    images = []
    scanned_count = 0
    token = continuation_token
    query = (search or "").strip().casefold()
    prefix = (prefix or "").strip().lstrip("/")
    for _ in range(max_scan_pages):
        request = {"Bucket": bucket, "Prefix": prefix, "MaxKeys": page_size - len(images)}
        if token:
            request["ContinuationToken"] = token
        response = client.list_objects_v2(**request)
        objects = response.get("Contents") or []
        scanned_count += len(objects)
        for item in objects:
            key = item.get("Key", "")
            if PurePosixPath(key).suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                if _clean_object_key(key) != key:
                    continue
            except ValueError:
                continue
            if query and query not in key.casefold():
                continue
            images.append(R2Image(key=key, size=int(item.get("Size", 0)), last_modified=item.get("LastModified")))
        previous_token = token
        token = response.get("NextContinuationToken") if response.get("IsTruncated") else None
        if token and token == previous_token:
            raise RuntimeError("R2から同じページが返されました。再読み込みしてください。")
        if len(images) >= page_size or not token:
            break
    return R2ImagePage(images=tuple(images), next_token=token, scanned_count=scanned_count)


def image_preview_url(client, bucket: str, object_key: str, base_url: str = "") -> str:
    if base_url:
        return image_url_for_key(object_key, base_url)
    return client.generate_presigned_url(
        "get_object", Params={"Bucket": bucket, "Key": object_key}, ExpiresIn=3600
    )


def render_r2_image_browser(
    st,
    *,
    key: str,
    client_factory,
    bucket: str,
    base_url: str = "",
    default_prefix: str = "",
    unavailable_reason: str = "",
    target_key: str | None = None,
    target_list_key: str | None = None,
    max_images: int = 10,
) -> str | None:
    """Render outside a form, before the target URL input is instantiated.

    Selecting or clearing an image updates ``target_key`` in session state. No
    R2 call occurs until the user explicitly loads or advances the image list.
    Signed preview URLs are never copied to the target input.
    """
    state = st.session_state
    storage_key = f"{key}:r2_browser"
    selected_key = f"{storage_key}:selected"
    pending_key = f"{storage_key}:pending"
    selection_prefix = f"{storage_key}:select:"
    selection_error_key = f"{storage_key}:selection_error"

    def toggle_selection(checkbox_key, candidate_url):
        pending = list(state.get(pending_key, []))
        if state.get(checkbox_key) and candidate_url not in pending:
            pending.append(candidate_url)
        elif not state.get(checkbox_key):
            pending = [url for url in pending if url != candidate_url]
        state[pending_key] = pending
        state.pop(selection_error_key, None)

    def add_selection():
        gallery = list(state.get(target_list_key, []))
        combined = list(dict.fromkeys([*gallery, *state.get(pending_key, [])]))
        if len(combined) > max_images:
            state[selection_error_key] = f"写真は合計{max_images}枚まで登録できます。選択枚数を減らしてください。"
            return
        state[target_list_key] = combined
        if target_key:
            state[target_key] = combined[0] if combined else ""
        state[pending_key] = []
        state.pop(selection_error_key, None)
        for checkbox_key in list(state):
            if checkbox_key.startswith(selection_prefix):
                state[checkbox_key] = False

    def clear_selection():
        state[pending_key] = []
        state.pop(selection_error_key, None)
        for checkbox_key in list(state):
            if checkbox_key.startswith(selection_prefix):
                state[checkbox_key] = False

    def add_one(candidate_url):
        gallery = list(state.get(target_list_key, []))
        if candidate_url not in gallery:
            if len(gallery) >= max_images:
                state[selection_error_key] = f"写真は合計{max_images}枚まで登録できます。"
                return
            gallery.append(candidate_url)
        state[target_list_key] = gallery
        if target_key:
            state[target_key] = gallery[0]
        state[pending_key] = [url for url in state.get(pending_key, []) if url != candidate_url]
        checkbox_key = selection_prefix + sha256(candidate_url.encode()).hexdigest()[:16]
        if checkbox_key in state:
            state[checkbox_key] = False
        state.pop(selection_error_key, None)

    selected = state.get(selected_key)
    with st.expander("R2の画像候補から選ぶ", expanded=False):
        st.caption("指定したフォルダから写真を選べます。" + ("選んだ写真は一覧の最後に追加されます。" if target_list_key else ""))
        prefix = st.text_input(
            "R2のフォルダ / キーの先頭", value=default_prefix,
            help="空欄にするとバケット全体が対象です。候補用フォルダがある場合はそのパスを入力してください。",
            key=f"{storage_key}:prefix",
        )
        search = st.text_input("ファイル名・キーを検索", key=f"{storage_key}:search")
        query = (prefix.strip().lstrip("/"), search.strip())
        if unavailable_reason:
            st.info(f"R2の画像候補を利用できません: {unavailable_reason}")

        def fetch_page(token=None):
            client = client_factory()
            if client is None:
                raise RuntimeError("R2に接続できません。設定を確認してください。")
            with st.spinner("R2の画像候補を読み込んでいます…"):
                page = list_r2_images(client, bucket, prefix=query[0], search=query[1], continuation_token=token)
            previews = {}
            for candidate in page.images:
                try:
                    previews[candidate.key] = image_preview_url(client, bucket, candidate.key, base_url)
                except Exception:
                    # Keys remain selectable even if only the preview fails.
                    previews[candidate.key] = None
            return {"page": page, "previews": previews}

        if st.button("画像候補を読み込む / 更新", key=f"{storage_key}:load", disabled=bool(unavailable_reason)):
            try:
                state[storage_key] = {"query": query, "pages": [fetch_page()], "index": 0}
            except Exception:
                st.error("R2の画像候補を読み込めませんでした。接続設定とバケットの読み取り権限を確認してください。")
        browser = state.get(storage_key)
        if browser and browser["query"] != query:
            st.caption("検索条件を変更しました。「画像候補を読み込む / 更新」で一覧を更新してください。")
            browser = None
        if target_list_key:
            st.info("① 写真の下の「この写真を選択」にチェック → ② 下の追加ボタン → ③ 登録・更新で保存")
            pending_count = len(state.get(pending_key, []))
            gallery_count = len(state.get(target_list_key, []))
            st.caption(f"チェック中: {pending_count}枚 ／ この雑学に追加済み: {gallery_count} / {max_images}枚")
            add, clear = st.columns(2)
            add.button(
                f"選択した写真をまとめて追加（{pending_count}枚）", key=f"{storage_key}:add_selected",
                disabled=pending_count == 0, on_click=add_selection, type="primary",
            )
            clear.button("まとめて選んだ写真を解除", key=f"{storage_key}:clear_selected",
                         disabled=pending_count == 0, on_click=clear_selection)
            st.caption("1枚ずつ「この写真を追加」を押しても、前の写真を残して追加できます。")
            if state.get(selection_error_key):
                st.error(state[selection_error_key])
        if browser:
            navigation = st.columns(3)
            with navigation[0]:
                previous = st.button("前のページ", key=f"{storage_key}:previous", disabled=browser["index"] == 0)
                if previous and browser["index"] > 0:
                    browser["index"] -= 1
                    st.rerun()
            with navigation[1]:
                page = browser["pages"][browser["index"]]["page"]
                has_cached_next = browser["index"] + 1 < len(browser["pages"])
                next_page = st.button("次のページ", key=f"{storage_key}:next", disabled=not (has_cached_next or page.next_token))
                if next_page and (has_cached_next or page.next_token):
                    try:
                        if not has_cached_next:
                            browser["pages"].append(fetch_page(page.next_token))
                        browser["index"] += 1
                        st.rerun()
                    except Exception:
                        st.error("次の画像候補を読み込めませんでした。もう一度お試しください。")
            current = browser["pages"][browser["index"]]
            page = current["page"]
            st.caption(f"{browser['index'] + 1}ページ目 · 画像{len(page.images)}件 / キー{page.scanned_count}件を確認")
            if not page.images:
                st.info("このページには条件に合う画像がありません。フォルダ・検索条件を変更するか、次のページへ進んでください。")
            columns = st.columns(2 if target_list_key else 3)
            for index, candidate in enumerate(page.images):
                with columns[index % len(columns)]:
                    preview = current["previews"].get(candidate.key)
                    if preview:
                        st.image(preview, width="stretch")
                    else:
                        st.caption("プレビューを取得できませんでした。")
                    st.caption(f"{candidate.key} · {candidate.size / 1024:.1f} KB")
                    candidate_url = image_url_for_key(candidate.key, base_url)
                    if target_list_key:
                        checkbox_key = selection_prefix + sha256(candidate_url.encode()).hexdigest()[:16]
                        st.checkbox(
                            "この写真を選択", key=checkbox_key,
                            value=candidate_url in state.get(pending_key, []),
                            on_change=toggle_selection, args=(checkbox_key, candidate_url),
                        )
                        if candidate_url in state.get(target_list_key, []):
                            st.caption("追加済み ✓")
                        st.button("この写真を追加", key=f"{storage_key}:choose:{index}",
                                  on_click=add_one, args=(candidate_url,))
                    elif st.button("この画像を使う", key=f"{storage_key}:choose:{index}"):
                        selected = candidate_url
                        state[selected_key] = selected
                        if target_key:
                            state[target_key] = selected
        if selected and not target_list_key:
            st.caption(f"選択中: {selected}")
            if st.button("画像候補の選択を解除", key=f"{storage_key}:clear"):
                selected = None
                state.pop(selected_key, None)
                if target_key and not target_list_key:
                    state[target_key] = ""
        if not base_url:
            st.caption("公開ベースURL未設定のため、プレビューには一時URLを使い、保存時にはR2キーを使います。")
    return selected
