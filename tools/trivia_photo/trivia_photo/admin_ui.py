"""既存のStreamlit雑学管理画面へ埋め込む写真確認。独立サイトは作らない。"""
from __future__ import annotations

import tempfile
from dataclasses import replace
from pathlib import Path

from .approval import PhotoReview, photo_identity, review_token
from .cloud_state import CloudState
from .config import Settings
from .storage import R2
from .workflow import Workflow, safe_error


STATUSES = {"staged": "確認待ち", "rejected": "選び直し待ち", "reselection_requested": "選び直し待ち",
            "held": "保留", "approved": "採用済み（未反映）", "published": "反映済み",
            "queued": "収集待ち", "planned": "収集待ち", "candidates": "選定待ち",
            "needs_review": "要確認", "error": "要確認", "selected": "保存待ち"}
REASONS = ["対象が違う", "構図が合わない", "画質が足りない", "利用条件が気になる", "別の写真がよい", "その他"]


def create_workflow(database_url: str | None = None, target: str = "normal") -> Workflow:
    settings = Settings.load().for_target(target)
    if database_url is not None:
        settings = replace(settings, database_url=database_url)
    # インストール先のsite-packagesへ作業ファイルを作らない。画像は保存しない。
    settings.data_dir = Path(tempfile.gettempdir()) / "trivia-photo-admin" / target
    settings.require("endpoint", "access_key", "secret_key", "bucket", "review_bucket")
    storage = R2(settings)
    return Workflow(settings, CloudState(storage, settings.data_dir), storage=storage)


def publish_approved(workflow, batch, trivia_id, credits_ready):
    results = workflow.publish(batch, ids=[trivia_id], apply=True, credits_ready=credits_ready)
    if len(results) != 1 or results[0]["status"] not in {"published", "already_published"}:
        detail = results[0].get("error", "出典表示の準備または接続状態を確認してください") if results else "反映結果がありません"
        raise ValueError("採用は保存済みですが、DBへの反映に失敗しました。反映を再試行してください：" + detail)


def render_photo_review(workflow=None, *, publish_on_approval=False, credits_ready=False) -> None:
    import streamlit as st

    st.subheader("写真の確認")
    st.caption("採用すると写真と出典を本番DBへ反映します。旧版アプリは先頭の1枚、新版は全写真を表示します。"
               if publish_on_approval else "採用・保留・選び直しはR2に保存します。採用だけではアプリに反映されません。")
    if "photo_notice" in st.session_state:
        st.success(st.session_state.pop("photo_notice"))
    if "photo_error_notice" in st.session_state:
        st.error(st.session_state.pop("photo_error_notice"))
    try:
        workflow = workflow or create_workflow()
        review = PhotoReview(workflow)
        # 一覧の再取得もユーザー操作に限定し、毎回全バッチを読まない。
        if "photo_batches" not in st.session_state:
            st.session_state.photo_batches = workflow.state.batch_ids()[::-1]
        if st.button("最新の状態を読み直す", key="photo_refresh"):
            st.session_state.photo_batches = workflow.state.batch_ids()[::-1]
            st.session_state.pop("photo_document", None)
        batches = st.session_state.photo_batches
        if not batches:
            subject = "Mapの" if workflow.settings.target_table == "map_trivia" else ""
            st.info(f"この対象の写真はまだ収集されていません。Codexに「{subject}次の5件の写真を集めて」と依頼してください。")
            return
        batch = st.selectbox("収集回", batches, key="photo_batch")
        snapshot = st.session_state.get("photo_document")
        if not snapshot or snapshot["batch"] != batch:
            snapshot = {"batch": batch, "items": workflow.state.items(batch)}
            st.session_state.photo_document = snapshot
        items = snapshot["items"]
    except Exception as exc:
        st.error("写真の確認を読み込めませんでした：" + safe_error(exc))
        return

    counts = {}
    for item in items:
        label = STATUSES.get(item["status"], item["status"])
        counts[label] = counts.get(label, 0) + 1
    st.write(" / ".join(f"{label} {count}件" for label, count in counts.items()))
    left, right = st.columns([1, 2])
    with left:
        status = st.selectbox("状態", ["すべて", "確認待ち", "選び直し待ち", "保留", "採用済み（未反映）", "反映済み", "要確認"], key="photo_status")
    with right:
        query = st.text_input("雑学ID・タイトルで絞り込み", key="photo_query").strip()
    filtered = [item for item in items if (status == "すべて" or STATUSES.get(item["status"]) == status)
                and (not query or query in str(item["trivia_id"]) or query.lower() in item["trivia"]["title"].lower())]
    if not filtered:
        st.info("条件に合う写真はありません。")
        return
    pages = max(1, (len(filtered) + 4) // 5)
    page = st.selectbox("ページ（5件ずつ）", range(1, pages + 1), key=f"photo_page_{batch}_{status}_{query}")
    for item in filtered[(page - 1) * 5:page * 5]:
        _render_item(st, workflow, review, item, publish_on_approval, credits_ready)
    st.caption("選び直しはCodexに「管理画面で選び直し待ちにした写真を集め直して」と依頼すると進められます。")
    if not publish_on_approval:
        st.caption("アプリへの反映は引き続きCodexへ依頼してください。クレジット必須の写真は、表示対応完了まで反映待ちになります。")


def _render_item(st, workflow, review, item, publish_on_approval=False, credits_ready=False):
    batch, trivia_id = item["batch_id"], item["trivia_id"]
    token = review_token(item)
    key = f"photo_{batch}_{trivia_id}_{token[:12]}"
    with st.container(border=True):
        st.markdown(f"#### #{trivia_id}　{item['trivia']['title']}")
        st.caption(STATUSES.get(item["status"], item["status"]))
        st.write(item["trivia"].get("content") or item["trivia"].get("explanation") or "")
        choices = review.options(item)
        if not choices:
            st.info(item.get("error") or "Codexによる写真の収集・選定を待っています。")
            return
        labels = ["おすすめ" if c["recommended"] else f"別候補 {i}" for i, c in enumerate(choices)]
        approved = item.get("approved_photos", [])
        initial_selection = {index for index, candidate in enumerate(choices)
                             if any(photo_identity(candidate) == photo_identity(photo["selected"], photo["asset"])
                                    for photo in approved)} if approved else {0}
        selected_options = []
        if item["status"] != "published":
            st.info("採用したい写真にチェックを付けてください。複数枚を選べます。先頭の写真がアプリの表紙になります。")
        for index, (column, candidate) in enumerate(zip(st.columns(len(choices)), choices)):
            with column:
                st.markdown(f"**{labels[index]}**")
                try:
                    st.image(workflow.asset_bytes(candidate["asset"]), width="stretch")
                except Exception as exc:
                    st.warning("写真を表示できません：" + safe_error(exc))
                metadata = item.get("metadata", candidate["metadata"]) if candidate["recommended"] else candidate["metadata"]
                reference = metadata.get("is_reference") or not candidate["recommended"]
                if reference:
                    st.caption("参考画像")
                st.caption(f"{metadata.get('author') or '作者表記なし'} / {metadata.get('license', '')}")
                with st.expander("出典・利用条件"):
                    st.write(metadata.get("title", ""))
                    if metadata.get("source_url"):
                        st.link_button("出典ページ", metadata["source_url"])
                    if metadata.get("license_url"):
                        st.link_button("ライセンス", metadata["license_url"])
                    for field in ("attribution", "copyright_notice", "credit_line", "restrictions", "selection_reason"):
                        if metadata.get(field):
                            st.write(metadata[field])
                    st.write("加工：" + "・".join(metadata.get("changes", [])))
                    if candidate["asset"].get("source", {}).get("r2"):
                        st.link_button("トリミング前の全体版", workflow.r2().image_url(candidate["asset"]["source"]))
                if item["status"] != "published" and st.checkbox(
                    "この写真を採用する", value=index in initial_selection, key=key + f"_adopt_{index}",
                ):
                    selected_options.append(index)
        request = item.get("reselection_request", {})
        if request:
            st.warning("選び直しの指定：" + request.get("reason", "理由なし"))
        if item.get("review_history"):
            with st.expander("判断の履歴"):
                for record in reversed(item["review_history"]):
                    st.write(f"{record.get('checked_at', '日時記録なし')}　{STATUSES.get(record['decision'], record['decision'])}　{record.get('reason', '')}")
        if item["status"] == "published":
            return
        if publish_on_approval and item["status"] == "approved":
            if item.get("error"):
                st.warning("採用済みですが、DBへの反映が完了していません：" + item["error"])
            if st.button("採用済みの写真を本番へ反映", key=key + "_publish_retry"):
                try:
                    publish_approved(workflow, batch, trivia_id, credits_ready)
                except Exception as exc:
                    st.session_state.photo_error_notice = safe_error(exc)
                else:
                    st.session_state.photo_notice = f"#{trivia_id} の採用済み写真を本番DBへ反映しました。"
                st.session_state.pop("photo_document", None)
                st.rerun()
        st.caption(f"採用する写真: {len(selected_options)}枚 ／ {len(choices)}枚")
        with st.form(key + "_form"):
            selected = st.radio("選び直し・保留の対象写真", range(len(choices)), format_func=lambda i: labels[i], horizontal=True, key=key + "_option")
            chosen = choices[selected]
            needs_rights = any(not choices[index]["recommended"] or choices[index]["metadata"].get("restrictions")
                               for index in selected_options) or bool(item.get("metadata", {}).get("rights_review_required"))
            if needs_rights:
                st.info("別候補や追加条件のある写真は、写っている対象の利用条件も確認してから採用してください。")
            rights = st.checkbox("写真と写っている対象の利用条件を確認した", key=key + "_rights")
            reason = st.selectbox("選び直しの理由", REASONS, key=key + "_reason")
            note = st.text_input("補足（探してほしい写真・保留理由など）", max_chars=1000, key=key + "_note")
            adopt_col, redo_col, hold_col = st.columns(3)
            adopt = adopt_col.form_submit_button("選択した写真を採用して本番へ反映" if publish_on_approval else "選択した写真を採用", disabled=not selected_options or bool(item.get("published_url")) or item["status"] not in {"staged", "held", "approved", "rejected", "reselection_requested"})
            redo = redo_col.form_submit_button("理由を付けて選び直し")
            hold = hold_col.form_submit_button("保留")
        if adopt or redo or hold:
            action = "approved" if adopt else "reselection_requested" if redo else "held"
            explanation = (reason + ("：" + note if note else "")) if redo else note
            try:
                review.decide(batch, trivia_id, action, token, selected, explanation, rights,
                              options=selected_options if adopt else None)
                if adopt and publish_on_approval:
                    publish_approved(workflow, batch, trivia_id, credits_ready)
            except Exception as exc:
                st.session_state.photo_error_notice = safe_error(exc)
                st.session_state.pop("photo_document", None)
                st.rerun()
            else:
                count = f"（{len(selected_options)}枚）" if adopt else ""
                st.session_state.photo_notice = (f"#{trivia_id} の写真{count}と出典を本番DBへ反映しました。"
                    if adopt and publish_on_approval else f"#{trivia_id} を{STATUSES[action]}{count}にしました。")
                st.session_state.pop("photo_document", None)
                st.rerun()
