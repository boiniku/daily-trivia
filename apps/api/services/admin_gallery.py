"""Ordered photo editing shared by all Streamlit publication screens."""
from hashlib import sha256

from services.admin_images import render_r2_image_browser
from services.trivia_images import MAX_TRIVIA_IMAGES, normalize_trivia_images


def _set_gallery(st, key, urls):
    st.session_state[f"{key}_image_gallery"] = list(dict.fromkeys(urls))
    st.session_state[f"{key}_image_url"] = urls[0] if urls else ""


def _sync_cover(st, key):
    gallery = list(st.session_state.get(f"{key}_image_gallery", []))
    value = st.session_state.get(f"{key}_image_url", "").strip()
    if value:
        _set_gallery(st, key, [value, *(gallery[1:] if gallery else [])])
    else:
        _set_gallery(st, key, gallery[1:])


def _move_image(st, key, index, offset):
    urls = list(st.session_state[f"{key}_image_gallery"])
    target = index + offset
    if 0 <= index < len(urls) and 0 <= target < len(urls):
        urls[index], urls[target] = urls[target], urls[index]
        _set_gallery(st, key, urls)


def _remove_image(st, key, index):
    urls = list(st.session_state[f"{key}_image_gallery"])
    if 0 <= index < len(urls):
        urls.pop(index)
        _set_gallery(st, key, urls)


def _add_urls(st, images, key):
    try:
        new_urls = [images.normalize_image_url(value) for value in
                    st.session_state.get(f"{key}_image_extra_urls", "").splitlines() if value.strip()]
        urls = normalize_trivia_images([*st.session_state[f"{key}_image_gallery"], *new_urls])
        _set_gallery(st, key, urls)
        st.session_state[f"{key}_image_extra_urls"] = ""
        st.session_state.pop(f"{key}_image_add_error", None)
    except ValueError as exc:
        st.session_state[f"{key}_image_add_error"] = str(exc)


def render_gallery_editor(st, images, key, current_url="", current_urls=None, *, current_sources=None, allow_recrop=False):
    saved_sources = {}
    for image, source in (current_sources or {}).items():
        try:
            saved_sources[images.normalize_image_url(image)] = source
        except ValueError:
            continue
    gallery_key = f"{key}_image_gallery"
    if gallery_key not in st.session_state:
        try:
            st.session_state[gallery_key] = normalize_trivia_images([
                images.normalize_image_url(url) for url in normalize_trivia_images(current_urls, current_url)
            ])
        except ValueError:
            # A broken legacy reference must not discard valid neighboring photos.
            previous = current_urls if isinstance(current_urls, list) else ([current_url] if current_url else [])
            st.session_state[gallery_key] = [str(url).strip() for url in previous]
    # Treat a key and its public URL as the same photo before limit checks.
    # Invalid historical references remain visible until the user fixes them.
    previous = list(st.session_state[gallery_key])
    canonical = []
    for url in previous:
        try:
            url = images.normalize_image_url(url)
        except ValueError:
            pass
        if url not in canonical:
            canonical.append(url)
    st.session_state[gallery_key] = canonical
    reason = images.get_r2_unavailable_reason()
    st.markdown(f"**写真を追加（最大{MAX_TRIVIA_IMAGES}枚）**")
    uploads = st.file_uploader(
        "端末から写真を追加（複数選択可）", type=["jpg", "jpeg", "png", "webp", "gif"],
        accept_multiple_files=True, key=f"{key}_image_upload", disabled=bool(reason),
        help="複数の写真をまとめて選択できます。PCではCtrl / Shiftキーでも複数選択できます。1枚12MBまで。登録・更新で保存します。",
    ) or []
    if reason:
        st.caption("R2アップロードは設定後に利用できます。写真URLは直接入力できます。")
    render_r2_image_browser(
        st, key=f"{key}_r2", client_factory=images.get_r2_client,
        bucket=images.R2_BUCKET_NAME, base_url=images.TRIVIA_IMAGE_R2_BASE_URL,
        default_prefix=images.R2_PREFIX, unavailable_reason=reason,
        target_key=f"{key}_image_url", target_list_key=gallery_key, max_images=MAX_TRIVIA_IMAGES,
    )
    gallery = list(st.session_state[gallery_key])
    st.caption(f"登録する写真: {len(gallery) + len(uploads)} / {MAX_TRIVIA_IMAGES}枚（一覧{len(gallery)}枚・アップロード待ち{len(uploads)}枚）")
    st.caption("先頭の写真が表紙になります。追加・並べ替え・削除は登録・更新で保存されます。")
    with st.expander("URL / R2キーから写真をまとめて追加", expanded=not gallery and not uploads):
        st.text_area("追加する写真（1行に1枚）", key=f"{key}_image_extra_urls")
        st.button("URLの写真を追加", key=f"{key}_image_add_urls", on_click=_add_urls, args=(st, images, key))
        if st.session_state.get(f"{key}_image_add_error"):
            st.error(st.session_state[f"{key}_image_add_error"])
    with st.expander("表紙のURL / R2キーを変更"):
        st.text_input(
            "写真URL / R2キー", value=gallery[0] if gallery else "", key=f"{key}_image_url",
            placeholder="先頭の写真URL または R2キー", on_change=_sync_cover, args=(st, key),
        )

    error = None
    urls = []
    try:
        urls = normalize_trivia_images([images.normalize_image_url(value) for value in gallery])
    except ValueError as exc:
        error = str(exc)
        st.error(error)
    sources = {}
    if gallery:
        columns = st.columns(2)
        for index, url in enumerate(gallery):
            with columns[index % 2]:
                st.caption(f"{index + 1}枚目" + ("（表紙）" if index == 0 else ""))
                try:
                    preview = images.normalize_image_url(url)
                    if preview.startswith(("https://", "http://", "data:")):
                        st.image(preview, width="stretch")
                    else:
                        st.caption(preview)
                except ValueError:
                    st.caption(url)
                source_key = sha256(url.encode()).hexdigest()[:16]
                source = st.text_input(
                    "写真の出典", value=saved_sources.get(url, ""),
                    key=f"{key}_image_source_{source_key}",
                    placeholder="出典URL または 撮影者・提供元",
                ).strip()
                if source:
                    sources[url] = source
                before, after, remove = st.columns(3)
                before.button("←", key=f"{key}_image_before_{index}", disabled=index == 0,
                              help="1つ前へ", on_click=_move_image, args=(st, key, index, -1))
                after.button("→", key=f"{key}_image_after_{index}", disabled=index == len(gallery) - 1,
                             help="1つ後ろへ", on_click=_move_image, args=(st, key, index, 1))
                remove.button("外す", key=f"{key}_image_remove_{index}", on_click=_remove_image, args=(st, key, index))
    else:
        st.caption("写真はまだ選択されていません。")

    if uploads:
        st.caption("アップロードした写真は現在の写真の後ろに追加されます。")
    if len(gallery) + len(uploads) > MAX_TRIVIA_IMAGES:
        error = f"写真は合計{MAX_TRIVIA_IMAGES}枚まで登録できます。"
        st.error(error)
    crop_mode = st.selectbox("トリミング", list(images.IMAGE_CROP_OPTIONS), key=f"{key}_image_crop")
    prepared = []
    upload_sources = []
    if uploads:
        st.caption("トリミングは選択したアップロード写真すべてに適用されます。手動調整は1枚ずつ行えます。")
    for index, uploaded in enumerate(uploads[:MAX_TRIVIA_IMAGES]):
        try:
            with st.expander(f"アップロード {index + 1}: {uploaded.name}", expanded=len(uploads) == 1):
                upload = uploaded
                if crop_mode == "アプリ表示サイズ 16:9 手動調整":
                    cropped = images.render_manual_cropper(uploaded, f"{key}_manual_crop_{index}")
                    if cropped is None:
                        raise ValueError("画像を読み込めませんでした。別の画像を選択してください。")
                    upload = images.pil_image_to_upload_file(cropped)
                    preview = upload
                else:
                    preview = images.get_processed_image_preview(uploaded, crop_mode)
                st.image(preview, caption="保存する写真のプレビュー", width="stretch")
                prepared.append((upload, crop_mode if upload is uploaded else None))
                upload_key = sha256(uploaded.getvalue()).hexdigest()[:16]
                upload_sources.append(st.text_input(
                    "この写真の出典", key=f"{key}_image_upload_source_{upload_key}_{index}",
                    placeholder="出典URL または 撮影者・提供元",
                ).strip())
        except Exception as exc:
            error = str(exc)
            st.error(error)

    selected_index = 0
    existing_crop = None
    selected_url = urls[0] if urls else ""
    if allow_recrop and urls:
        index_key = f"{key}_image_selected"
        if st.session_state.get(index_key, 0) >= len(urls):
            st.session_state[index_key] = 0
        selected_index = st.selectbox("トリミングする写真", list(range(len(urls))),
                                      format_func=lambda value: f"{value + 1}枚目", key=index_key)
        selected_url = urls[selected_index]
        if crop_mode == "アプリ表示サイズ 16:9 手動調整" and not uploads:
            if st.button("既存写真を読み込んで調整", key=f"{key}_load_crop", disabled=bool(reason)):
                try:
                    st.session_state[f"{key}_crop_source"] = (selected_url, images.download_image_for_processing(selected_url))
                except Exception as exc:
                    st.error(f"写真の読み込みに失敗しました: {exc}")
            loaded = st.session_state.get(f"{key}_crop_source")
            if loaded and loaded[0] == selected_url:
                try:
                    existing_crop = images.render_manual_cropper(loaded[1], f"{key}_existing_crop")
                    if existing_crop is not None:
                        st.image(existing_crop, caption="トリミング後のプレビュー", width="stretch")
                except Exception as exc:
                    st.error(f"写真の読み込みに失敗しました: {exc}")
    return dict(key=key, urls=urls, url=selected_url, selected_index=selected_index,
                uploaded=uploads, prepared=prepared, sources=sources, upload_sources=upload_sources,
                crop_mode=crop_mode, existing_crop=existing_crop, error=error)


def save_gallery(images, st, editor, trivia_id=None):
    if editor["error"]:
        raise ValueError(editor["error"])
    if len(editor["urls"]) + len(editor["prepared"]) > MAX_TRIVIA_IMAGES:
        raise ValueError(f"写真は{MAX_TRIVIA_IMAGES}枚まで登録できます。")
    urls = list(editor["urls"])
    sources = dict(editor.get("sources", {}))
    cache_key = f"{editor['key']}_image_upload_results"
    cached = st.session_state.get(cache_key, {})
    for index, (upload, crop) in enumerate(editor["prepared"]):
        signature = (sha256(upload.getvalue()).hexdigest(), crop)
        if signature not in cached:
            cached[signature] = images.upload_image_to_r2(upload, trivia_id, crop_mode=crop)
            st.session_state[cache_key] = cached
        urls.append(cached[signature])
        upload_sources = editor.get("upload_sources", [])
        if index < len(upload_sources) and upload_sources[index]:
            sources[cached[signature]] = upload_sources[index]
    urls = normalize_trivia_images(urls)
    return {"image_urls": urls, "image_url": urls[0] if urls else None, "image_sources": sources}
