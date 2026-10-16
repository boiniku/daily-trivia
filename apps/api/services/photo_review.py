"""毎日雑学の管理画面から写真ハーネスを呼ぶ薄い接続部分。"""
from pathlib import Path
import os
import sys


def render_photo_review():
    import streamlit as st

    # Prefer the version shipped with this repository on new machines.
    bundled = Path(__file__).resolve().parents[3] / "tools" / "trivia_photo"
    sibling = Path(__file__).resolve().parents[4] / "trivia_photo"
    roots = [Path(os.environ["TRIVIA_PHOTO_ROOT"])] if os.environ.get("TRIVIA_PHOTO_ROOT") else [bundled, sibling]
    for root in roots:
        if (root / "trivia_photo" / "admin_ui.py").is_file():
            sys.path.insert(0, str(root.resolve()))
            break
    try:
        from trivia_photo.admin_ui import create_workflow, render_photo_review as render
    except ModuleNotFoundError as exc:
        if exc.name != "trivia_photo":
            st.error("写真確認の依存ライブラリが不足しています。trivia_photoのrequirements.txtを管理画面のPython環境へインストールしてください。")
            return
        st.error("写真ハーネスが見つかりません。tools/trivia_photoを含めてリポジトリを取得してください。")
        return
    # Use exactly the database configured for this administration dashboard.
    # A photo-only environment override must not send approval writes elsewhere.
    from database import DATABASE_URL
    selected = st.radio("写真の管理対象", ["通常の雑学", "雑学MAP"], horizontal=True, key="photo_review_target")
    target = "map" if selected == "雑学MAP" else "normal"
    if st.session_state.get("photo_review_previous_target") != target:
        for key in list(st.session_state):
            if key.startswith("photo_") and key not in {"photo_review_target", "photo_review_previous_target"}:
                del st.session_state[key]
        st.session_state.photo_review_previous_target = target
    try:
        workflow = create_workflow(database_url=DATABASE_URL, target=target)
    except Exception:
        st.error("写真確認の接続設定を読み込めませんでした。管理画面のDB・R2設定を確認してください。")
        return
    render(workflow=workflow, publish_on_approval=True, credits_ready=True)
