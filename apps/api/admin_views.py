"""Interactive admin views. Database sessions belong to the dashboard entry point."""
from urllib.parse import urlsplit

import pandas as pd
import streamlit as st
from sqlalchemy import and_, or_

from models import MapTrivia, Trivia, TriviaCandidate
from services.admin_gallery import render_gallery_editor, save_gallery
from services.admin_workflow import (
    create_manual_trivia,
    delete_normal_trivia,
    publish_candidate,
    update_map_trivia,
    update_normal_trivia,
    validate_trivia_values,
)
from services.map_trivia import archive_map_trivia
from services.trivia_images import read_trivia_images
from services.trivia_candidates import reject_candidate, update_candidate
from services.trivia_csv_import import (
    TRIVIA_CATEGORIES,
    TriviaCsvValidationError,
    find_existing_duplicate_keys,
    import_trivia_rows,
    parse_trivia_csv,
)


SECTIONS = ["🆕 新規登録", "📄 CSV一括登録", "🤖 AI収集・承認", "🛠️ 管理・編集"]


def remember_fields(*keys):
    remembered = set(st.session_state.get("admin_draft_fields", ()))
    remembered.update(keys)
    st.session_state["admin_draft_fields"] = tuple(remembered)


def finish_action(message, *reset_prefixes, keep=()):
    st.session_state["admin_notice"] = message
    st.session_state["admin_reset_prefixes"] = reset_prefixes
    st.session_state["admin_preserve_fields"] = {key: st.session_state[key] for key in keep if key in st.session_state}
    st.rerun()


def prepare_view():
    for prefix in st.session_state.pop("admin_reset_prefixes", ()):
        for key in list(st.session_state):
            if key.startswith(prefix) and key != "new_register_target":
                del st.session_state[key]
    for key, value in st.session_state.pop("admin_preserve_fields", {}).items():
        st.session_state[key] = value
    # Detach draft values from widget cleanup when changing screen or target.
    # Button and uploader state is deliberately excluded from this registry.
    for key in st.session_state.get("admin_draft_fields", ()):
        if key in st.session_state:
            st.session_state[key] = st.session_state[key]
    message = st.session_state.pop("admin_notice", None)
    if message:
        st.success(message)


def field_value(item, name, default=""):
    value = item.get(name) if isinstance(item, dict) else getattr(item, name, None)
    return default if value is None else value


def render_location_fields(key, item=None, *, suffix=""):
    item = item or {}
    remember_fields(*(f"{key}_{name}{suffix}" for name in
                      ("prefecture", "address", "latitude", "longitude", "radius", "hint")))
    left, right = st.columns(2)
    with left:
        prefecture = st.text_input("都道府県", value=field_value(item, "map_prefecture"), key=f"{key}_prefecture{suffix}")
        latitude = st.number_input(
            "緯度", min_value=-90.0, max_value=90.0,
            value=field_value(item, "map_latitude", None), format="%.6f",
            placeholder="例: 35.658581", key=f"{key}_latitude{suffix}",
        )
    with right:
        address = st.text_input("住所・施設名", value=field_value(item, "map_address"), key=f"{key}_address{suffix}")
        longitude = st.number_input(
            "経度", min_value=-180.0, max_value=180.0,
            value=field_value(item, "map_longitude", None), format="%.6f",
            placeholder="例: 139.745433", key=f"{key}_longitude{suffix}",
        )
    radius = st.number_input(
        "解放半径（メートル）", min_value=10, max_value=5000,
        value=int(field_value(item, "map_radius", 1200)), step=10,
        key=f"{key}_radius{suffix}",
    )
    hint = st.text_area("現地でのヒント", value=field_value(item, "map_hint"), key=f"{key}_hint{suffix}")
    if latitude is not None and longitude is not None:
        if st.checkbox("地図で位置を確認", key=f"{key}_preview{suffix}"):
            st.map(pd.DataFrame([{"lat": latitude, "lon": longitude}]), zoom=15)
        st.link_button("Google マップで座標を開く", f"https://www.google.com/maps?q={latitude},{longitude}")
    return dict(map_prefecture=prefecture, map_address=address, map_latitude=latitude,
                map_longitude=longitude, map_radius=radius, map_hint=hint)


def render_image_editor(images, key, current_url="", current_urls=None, *, current_sources=None, allow_recrop=False):
    remember_fields(f"{key}_image_url", f"{key}_image_crop", f"{key}_image_extra_urls")
    editor = render_gallery_editor(st, images, key, current_url, current_urls,
                                   current_sources=current_sources, allow_recrop=allow_recrop)
    remember_fields(*(name for name in st.session_state if name.startswith(
        (f"{key}_image_source_", f"{key}_image_upload_source_"))))
    return editor


def save_images(images, editor, trivia_id=None):
    return save_gallery(images, st, editor, trivia_id)


def render_text_fields(key, item=None, *, new=False):
    item = item or {}
    remember_fields(*(f"{key}_{name}" for name in
                      ("title", "content", "explanation", "category", "source")))
    title = st.text_input("タイトル (必須)" if new else "タイトル", value=field_value(item, "title"),
                          max_chars=50 if new else None, key=f"{key}_title")
    content = st.text_area("本文 (必須)" if new else "本文", value=field_value(item, "content"),
                           max_chars=100 if new else None, height=100, key=f"{key}_content")
    explanation = st.text_area("解説・詳細" if new else "解説", value=field_value(item, "explanation"), key=f"{key}_explanation")
    category = field_value(item, "category", "その他")
    options = list(TRIVIA_CATEGORIES)
    if category not in options:
        options.append(category)
    category = st.selectbox("カテゴリ", options, index=options.index(category), key=f"{key}_category")
    source = st.text_input("ソースURL", value=field_value(item, "source"), key=f"{key}_source", placeholder="https://...")
    return dict(title=title, content=content, explanation=explanation, category=category, source=source)


def publication_message(result):
    targets = []
    if result.trivia:
        targets.append(f"通常の雑学（#{result.trivia.id}）")
    if result.map_trivia:
        targets.append(f"雑学MAP（#{result.map_trivia.id}）")
    return " / ".join(targets)


def render_register(db, images):
    st.header("新しい雑学を登録")
    remember_fields("new_register_target")
    target = st.radio("登録先", ["通常の雑学", "新規作成（地図用）", "通常 + 地図"],
                      horizontal=True, key="new_register_target")
    add_normal = target in {"通常の雑学", "通常 + 地図"}
    add_map = target in {"新規作成（地図用）", "通常 + 地図"}
    left, right = st.columns([2, 1])
    with left:
        values = render_text_fields("new", new=True)
        if add_map:
            st.subheader("雑学MAPの場所")
            st.caption("場所と座標を入力してください。MAP IDは登録時に自動発行されます。")
            values.update(render_location_fields("new_map"))
    with right:
        st.subheader("写真")
        editor = render_image_editor(images, "new")
    if st.button("登録する", type="primary", key="new_submit"):
        try:
            validate_trivia_values(**values, add_to_map=add_map)
            values.update(save_images(images, editor))
            result = create_manual_trivia(db, add_to_normal=add_normal, add_to_map=add_map, **values)
            finish_action(f"登録しました: {values['title']} → {publication_message(result)}", "new_")
        except Exception as exc:
            db.rollback()
            st.error(f"登録できませんでした: {exc}")


def render_csv(db):
    st.header("CSVから雑学をまとめて登録")
    st.write("1行目を見出しにし、2行目から雑学を入力したCSVを選択してください。")
    template = "\ufeffタイトル,本文,詳細,カテゴリ\r\nタコの心臓,タコには心臓が3つある,役割の異なる心臓を持ちます,生物\r\n"
    st.code(template.lstrip("\ufeff"), language="csv")
    st.caption("詳細は空欄でも登録できます。タイトルは50文字、本文は100文字まで。一度に最大1,000件です。")
    st.download_button("CSVテンプレートをダウンロード", data=template.encode("utf-8"),
                       file_name="trivia_import_template.csv", mime="text/csv")
    st.caption("使用できるカテゴリ: " + " / ".join(TRIVIA_CATEGORIES))
    csv_file = st.file_uploader("CSVファイル", type=["csv"], key="trivia_csv_upload")
    if csv_file is None:
        return
    if csv_file.size > 5 * 1024 * 1024:
        st.error("CSVファイルは5MB以下にしてください。")
        return
    try:
        parsed = parse_trivia_csv(csv_file.getvalue())
        for warning in parsed.warnings:
            st.warning(warning)
        duplicates = find_existing_duplicate_keys(db, parsed.rows)
        count = len(parsed.rows) - len(duplicates)
        if duplicates:
            st.warning(f"既存の雑学と完全一致する {len(duplicates)} 件はスキップされます。")
        st.subheader(f"登録前プレビュー（登録対象 {count} 件）")
        st.dataframe(pd.DataFrame([{
            "CSV行": row.line_number, "タイトル": row.title, "本文": row.content,
            "詳細": row.explanation, "カテゴリ": row.category,
            "登録状態": "重複のためスキップ" if row.duplicate_key in duplicates else "登録対象",
        } for row in parsed.rows]), width="stretch", hide_index=True)
        if st.button(f"{count} 件をまとめて登録", type="primary", disabled=count == 0, key="trivia_csv_import_submit"):
            result = import_trivia_rows(db, parsed.rows)
            finish_action(f"{result.created_count} 件の雑学を登録しました（重複スキップ {result.skipped_duplicate_count} 件）。")
    except TriviaCsvValidationError as exc:
        st.error("CSVの内容を修正してください。")
        for error in exc.errors:
            st.write(f"- {error}")
    except Exception as exc:
        db.rollback()
        st.error(f"CSV登録中にエラーが発生しました: {exc}")


def render_candidates(db, images):
    st.header("AI収集・承認待ちの雑学")
    if not images.OPENAI_API_KEY:
        st.info("AI収集はOPENAI_API_KEYの設定後に利用できます。登録済み候補の確認・承認はこのまま行えます。")
    with st.form("ai_gen_form"):
        target = st.radio("収集タイプ", ["収集（通常）", "収集（地図用）"], horizontal=True, key="ai_collection_target")
        topic = st.text_input("トピック (例: 宇宙, 猫, 歴史)", placeholder="空欄なら幅広いジャンルから収集")
        count = st.number_input("生成件数", min_value=1, max_value=10, value=3)
        collect = st.form_submit_button("生成開始", type="primary", disabled=not images.OPENAI_API_KEY)
    if collect:
        from services.trivia_collection import collect_trivia_candidates
        with st.spinner("Webの出典と重複を確認しながら収集中です…"):
            try:
                candidates = collect_trivia_candidates(db, topic, count, map_mode=target == "収集（地図用）")
                if candidates:
                    st.success(f"{len(candidates)} 件を承認待ちに追加しました。")
                else:
                    st.warning("重複・位置情報・品質の条件を満たす候補がありませんでした。トピックを変えて再実行してください。")
            except Exception as exc:
                db.rollback()
                st.error(f"収集エラー: {exc}")
    st.divider()
    pending = db.query(TriviaCandidate).filter(TriviaCandidate.status == "pending").order_by(TriviaCandidate.id.desc()).all()
    st.subheader(f"承認待ちリスト（{len(pending)}件）")
    if not pending:
        st.info("承認待ちの雑学はありません。")
        return
    kind = st.radio("候補の絞り込み", ["すべて", "通常", "地図用"], horizontal=True, key="candidate_kind")
    if kind != "すべて":
        pending = [item for item in pending if bool(item.map_address or item.map_prefecture) == (kind == "地図用")]
    if not pending:
        st.info("条件に一致する候補はありません。")
        return
    ids = [item.id for item in pending]
    by_id = {item.id: item for item in pending}
    labels = {item.id: f"#{item.id}: {item.title}" for item in pending}
    selected = st.selectbox("確認する候補", ids, format_func=lambda value: labels[value], key="candidate_select")
    item = by_id[selected]
    key = f"candidate_{item.id}"
    remember_fields(f"{key}_normal", f"{key}_map")
    is_map = bool(item.map_address or item.map_prefecture)
    add_normal = st.checkbox("通常の雑学に追加する", value=not is_map, key=f"{key}_normal")
    add_map = st.checkbox("雑学MAPに追加する", value=is_map, key=f"{key}_map")
    left, right = st.columns([2, 1])
    with left:
        values = render_text_fields(key, item)
        if values["source"].startswith(("https://", "http://")):
            st.link_button("出典を開いて確認", values["source"])
        if add_map:
            st.subheader("雑学MAPの場所")
            values.update(render_location_fields(f"{key}_location", item))
    with right:
        editor = render_image_editor(images, key, item.image_url, item.image_urls, current_sources=item.image_sources)
    approve_col, save_col, reject_col = st.columns(3)
    approve = approve_col.button("✅ 選択した保存先に登録", type="primary", key=f"{key}_approve")
    save = save_col.button("候補の変更を保存", key=f"{key}_save")
    reject_confirm = st.checkbox("この候補を却下する", key=f"{key}_reject_confirm")
    reject = reject_col.button("🗑️ 却下", disabled=not reject_confirm, key=f"{key}_reject")
    if approve or save:
        try:
            if approve and not (add_normal or add_map):
                raise ValueError("登録先を1つ以上選択してください。")
            validate_trivia_values(**values, add_to_map=add_map)
            values.update(save_images(images, editor))
            if approve:
                result = publish_candidate(db, item.id, add_to_normal=add_normal, add_to_map=add_map, **values)
                finish_action(f"登録しました: {publication_message(result)}", f"{key}_")
            # Keep collected location data when publishing only to normal trivia.
            location = {name: field_value(item, name, None) for name in
                        ("map_address", "map_prefecture", "map_latitude", "map_longitude", "map_radius", "map_hint")}
            location.update({name: value for name, value in values.items() if name.startswith("map_")})
            update_candidate(db, item.id, **{name: value for name, value in values.items() if not name.startswith("map_")}, **location)
            finish_action("候補の変更を保存しました。", f"{key}_", keep=(f"{key}_normal", f"{key}_map"))
        except Exception as exc:
            db.rollback()
            st.error(f"保存エラー: {exc}")
    if reject:
        try:
            reject_candidate(db, item.id, "streamlit")
            finish_action("候補を却下しました。", f"{key}_")
        except Exception as exc:
            db.rollback()
            st.error(f"却下エラー: {exc}")


def render_map_admin(db, images):
    st.subheader("雑学MAPを管理")
    search = st.text_input("🔍 MAP検索 (タイトル・本文・住所)", key="map_search").strip()
    state = st.radio("公開状態", ["公開中", "非公開", "すべて"], horizontal=True, key="map_status")
    query = db.query(MapTrivia)
    if state != "すべて":
        query = query.filter(MapTrivia.is_active.is_(state == "公開中"))
    if search:
        query = query.filter(or_(*[column.contains(search, autoescape=True) for column in
                                  (MapTrivia.title, MapTrivia.content, MapTrivia.map_address, MapTrivia.map_prefecture)]))
    items = query.order_by(MapTrivia.id.desc()).all()
    with_photos = sum(bool(read_trivia_images(item.image_urls, item.image_url)) for item in items)
    st.caption(f"写真登録済み {with_photos} 件 / 未登録 {len(items) - with_photos} 件")
    photos = st.radio("写真の登録状況", ["すべて", "写真なし", "写真あり"], horizontal=True, key="map_photo_status")
    if photos != "すべて":
        items = [item for item in items if bool(read_trivia_images(item.image_urls, item.image_url)) == (photos == "写真あり")]
    st.write(f"全 {len(items)} 件")
    if not items:
        st.info("条件に一致するMAP雑学はありません。")
        return
    by_id = {item.id: item for item in items}
    labels = {item.id: f"map_{item.id}: {item.title} ({item.map_prefecture})" for item in items}
    selected = st.selectbox("編集するMAP雑学", list(by_id), key="map_edit_select",
                            format_func=lambda value: labels[value])
    item = by_id[selected]
    key = f"map_{item.id}"
    remember_fields(*(f"map_{name}_{key}" for name in
                      ("title", "description", "explanation", "category", "source")))
    st.subheader(f"MAP編集: {key}")
    st.caption(f"MAP ID: {key} / {'公開中' if item.is_active else '非公開'}")
    left, right = st.columns([2, 1])
    with left:
        values = dict(
            title=st.text_input("タイトル", item.title or "", key=f"map_title_{key}"),
            content=st.text_area("本文", item.content or "", key=f"map_description_{key}"),
            explanation=st.text_area("解説", item.explanation or "", key=f"map_explanation_{key}"),
        )
        options = list(TRIVIA_CATEGORIES)
        category = item.category or "その他"
        if category not in options:
            options.append(category)
        values["category"] = st.selectbox("カテゴリ", options, index=options.index(category), key=f"map_category_{key}")
        values["source"] = st.text_input("ソースURL", item.source or "", key=f"map_source_{key}")
        values.update(render_location_fields("map", item, suffix=f"_{key}"))
    with right:
        st.caption("このMAPの写真を登録します。複数枚・R2候補・出典の編集に対応しています。MAP更新でアプリへ反映します。")
        editor = render_image_editor(images, key, item.image_url, item.image_urls,
                                     current_sources=item.image_sources, allow_recrop=True)
    update_col, archive_col = st.columns(2)
    update = update_col.button("MAP更新", type="primary", key=f"map_update_{key}")
    confirm = st.checkbox("このMAP雑学を非公開にする", key=f"map_archive_confirm_{key}") if item.is_active else True
    archive = archive_col.button("MAPを非公開にする" if item.is_active else "MAPを再公開する",
                                disabled=not confirm, key=f"map_delete_{key}")
    if update:
        try:
            validate_trivia_values(**values, add_to_map=True)
            values.update(save_images(images, editor))
            update_map_trivia(db, item.id, **values)
            finish_action("雑学MAPを更新しました。", f"map_title_{key}", f"map_description_{key}", f"map_explanation_{key}", f"{key}_")
        except Exception as exc:
            db.rollback()
            st.error(f"MAP更新エラー: {exc}")
    if archive:
        try:
            if item.is_active:
                archive_map_trivia(db, item.id)
                message = "雑学MAPを非公開にしました。解放済みの記録は保持されます。"
            else:
                validate_trivia_values(**{name: getattr(item, name) for name in
                    ("title", "content", "explanation", "source", "category", "image_url", "image_urls", "image_sources", "map_address", "map_prefecture", "map_latitude", "map_longitude", "map_radius", "map_hint")}, add_to_map=True)
                item.is_active = True
                db.commit()
                message = "雑学MAPを再公開しました。"
            finish_action(message)
        except Exception as exc:
            db.rollback()
            st.error(f"公開状態の更新エラー: {exc}")
    render_image_actions(db, images, item, editor, key)


def render_image_actions(db, images, item, editor, key):
    reset = (f"{key}_image_", f"{key}_r2", f"{key}_crop_source", f"{key}_existing_crop",
             f"{key}_manual_crop", f"{key}_uploaded_result")
    left, right = st.columns(2)
    recrop = left.button("既存写真をトリミング保存", key=f"recrop_{key}",
                         disabled=not editor["url"] or bool(images.get_r2_unavailable_reason()) or editor["crop_mode"] == "トリミングなし" or bool(editor["uploaded"]))
    unlink = right.button("写真の関連付けを解除", key=f"image_delete_{key}", disabled=not (item.image_url or item.image_urls))
    if recrop:
        try:
            if editor["crop_mode"] == "アプリ表示サイズ 16:9 手動調整":
                if editor["existing_crop"] is None:
                    raise ValueError("「既存写真を読み込んで調整」で写真を読み込んでください。")
                image = images.pil_image_to_upload_file(editor["existing_crop"])
                url = images.upload_image_to_r2(image, item.id)
            else:
                image = images.download_image_for_processing(editor["url"])
                url = images.upload_image_to_r2(image, item.id, crop_mode=editor["crop_mode"])
            urls = list(editor["urls"])
            urls[editor["selected_index"]] = url
            sources = dict(editor["sources"])
            source = sources.pop(editor["url"], "")
            if source:
                sources[url] = source
            update = update_map_trivia if isinstance(item, MapTrivia) else update_normal_trivia
            update(db, item.id, image_urls=urls, image_sources=sources)
            finish_action("写真をトリミングして保存しました。", *reset)
        except Exception as exc:
            db.rollback()
            st.error(f"トリミング保存エラー: {exc}")
    if unlink:
        try:
            update = update_map_trivia if isinstance(item, MapTrivia) else update_normal_trivia
            update(db, item.id, image_urls=[])
            finish_action("写真の関連付けを解除しました。R2の画像は引き続き利用できます。", *reset)
        except Exception as exc:
            db.rollback()
            st.error(f"写真の更新エラー: {exc}")


def render_source_maintenance(db, images):
    with st.expander("🔧 データメンテナンス (ソースURL修正)"):
        invalid = db.query(Trivia).filter(or_(Trivia.source.is_(None), and_(
            ~Trivia.source.startswith("http://"), ~Trivia.source.startswith("https://"))))
        count = invalid.count()
        st.write(f"URL形式でない出典: {count} 件")
        st.caption("最大100件ずつAIで出典を検索します。処理後は出典の内容をご確認ください。")
        if st.button("♻️ ソース自動修正を開始 (OpenAI)", disabled=not count or not images.OPENAI_API_KEY):
            import json
            from openai import OpenAI
            client = OpenAI(api_key=images.OPENAI_API_KEY)
            items = invalid.order_by(Trivia.id.desc()).limit(100).all()
            progress = st.progress(0)
            updated = 0
            failed = 0
            for i, item in enumerate(items):
                try:
                    response = client.chat.completions.create(
                        model="gpt-4o-mini", messages=[{"role": "user", "content":
                        f"次の雑学の信頼できる出典URLを1つ。見つからなければ空文字。JSON {{\"source_url\":\"\"}}で回答。\n{item.title}\n{item.content}"}],
                        response_format={"type": "json_object"},
                    )
                    url = json.loads(response.choices[0].message.content).get("source_url", "").strip()
                    parts = urlsplit(url)
                    if parts.scheme in ("http", "https") and parts.netloc:
                        item.source = url
                        db.commit()
                        updated += 1
                except Exception:
                    db.rollback()
                    failed += 1
                progress.progress((i + 1) / len(items))
            st.success(f"修正 {updated} 件 / エラー {failed} 件 / 対象 {len(items)} 件")


def render_manage(db, images):
    st.header("既存の雑学を管理")
    operation = st.radio("操作", ["本文・写真の編集", "写真の確認"], horizontal=True, key="manage_operation")
    if operation == "写真の確認":
        from services.photo_review import render_photo_review
        render_photo_review()
        return
    target = st.radio("管理対象", ["通常の雑学", "雑学MAP"], horizontal=True, key="manage_target")
    if target == "雑学MAP":
        render_map_admin(db, images)
        return
    render_source_maintenance(db, images)
    search = st.text_input("🔍 検索 (タイトルまたは本文)", key="manage_search").strip()
    category = st.selectbox("カテゴリで絞り込み", ["すべて", *TRIVIA_CATEGORIES], key="manage_category")
    size = st.selectbox("表示件数", [10, 20, 50], index=1, key="manage_page_size")
    query = db.query(Trivia)
    if search:
        query = query.filter(or_(Trivia.title.contains(search, autoescape=True), Trivia.content.contains(search, autoescape=True)))
    if category != "すべて":
        query = query.filter(Trivia.category == category)
    total = query.count()
    max_page = max(1, (total + size - 1) // size)
    signature = (search, category, size)
    if st.session_state.get("manage_page_filter") != signature:
        st.session_state["manage_page_filter"] = signature
        st.session_state["manage_page"] = 1
    st.session_state["manage_page"] = min(max_page, max(1, st.session_state.get("manage_page", 1)))
    page = st.number_input("ページ", min_value=1, max_value=max_page, step=1, key="manage_page")
    items = query.order_by(Trivia.id.desc()).offset((page - 1) * size).limit(size).all()
    st.write(f"全 {total} 件 / {page} / {max_page} ページ")
    if not items:
        st.info("データが見つかりません。")
        return
    by_id = {item.id: item for item in items}
    labels = {item.id: f"{item.id}: {item.title} ({item.category})" for item in items}
    selected = st.selectbox("編集する雑学", list(by_id), key="manage_select",
                            format_func=lambda value: labels[value])
    item = by_id[selected]
    key = f"edit_{item.id}"
    st.subheader(f"編集: {item.id} / {item.title}")
    left, right = st.columns([2, 1])
    with left:
        values = render_text_fields(key, item)
    with right:
        editor = render_image_editor(images, key, item.image_url, item.image_urls,
                                     current_sources=item.image_sources, allow_recrop=True)
    if st.button("更新", type="primary", key=f"update_{item.id}"):
        try:
            validate_trivia_values(**values)
            values.update(save_images(images, editor, item.id))
            update_normal_trivia(db, item.id, **values)
            finish_action("雑学を更新しました。", f"{key}_")
        except Exception as exc:
            db.rollback()
            st.error(f"更新エラー: {exc}")
    render_image_actions(db, images, item, editor, key)
    with st.expander("この雑学を雑学MAPに登録"):
        location = render_location_fields(f"edit_map_{item.id}")
        if st.button("雑学MAPに登録", key=f"map_register_{item.id}"):
            try:
                map_values = dict(values, **location)
                validate_trivia_values(**map_values, add_to_map=True)
                map_values.update(save_images(images, editor, item.id))
                result = create_manual_trivia(db, add_to_normal=False, add_to_map=True, **map_values)
                finish_action(f"雑学MAPに登録しました: {publication_message(result)}", f"edit_map_{item.id}_")
            except Exception as exc:
                db.rollback()
                st.error(f"MAP登録エラー: {exc}")
    with st.expander("雑学を削除"):
        st.caption("この雑学と、日次配信・コレクション・へぇの関連記録を削除します。")
        confirm = st.checkbox("この雑学を削除する", key=f"delete_confirm_{item.id}")
        if st.button("削除", disabled=not confirm, key=f"delete_{item.id}"):
            try:
                delete_normal_trivia(db, item.id)
                finish_action("雑学を削除しました。", f"{key}_")
            except Exception as exc:
                db.rollback()
                st.error(f"削除エラー: {exc}")


def render_dashboard(db, images):
    prepare_view()
    section = st.radio("画面", SECTIONS, horizontal=True, key="admin_section", label_visibility="collapsed")
    {SECTIONS[0]: render_register, SECTIONS[1]: lambda db, images: render_csv(db),
     SECTIONS[2]: render_candidates, SECTIONS[3]: render_manage}[section](db, images)
