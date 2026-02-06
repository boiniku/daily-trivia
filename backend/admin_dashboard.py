import streamlit as st
import pandas as pd
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Trivia
from datetime import datetime

# Page Config
st.set_page_config(page_title="Trivia Manager", layout="wide", page_icon="📝")

st.title("📝 毎日雑学 管理ツール")

# Database Session
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

db = next(get_db())

# Tabs
tab1, tab2 = st.tabs(["🆕 新規登録", "🛠️ 管理・編集"])

# --- Tab 1: Register ---
with tab1:
    st.header("新しい雑学を登録")
    
    with st.form("register_form", clear_on_submit=True):
        col1, col2 = st.columns([2, 1])
        
        with col1:
            title = st.text_input("タイトル (必須)", max_chars=50, placeholder="例: 富士山の高さ")
            content = st.text_area("本文 (必須)", max_chars=200, height=100, placeholder="雑学のメインコンテンツ。150文字以内で簡潔に。")
            explanation = st.text_area("解説・詳細", height=150, placeholder="詳細な背景や理由など。")
        
        with col2:
            category = st.selectbox("カテゴリ", ["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"])
            source = st.text_input("ソースURL", placeholder="https://...")
            
        submitted = st.form_submit_button("登録する", type="primary")
        
        if submitted:
            if not title or not content:
                st.error("タイトルと本文は必須です。")
            else:
                try:
                    new_trivia = Trivia(
                        title=title,
                        content=content,
                        explanation=explanation,
                        source=source,
                        category=category,
                        # embedding is null for manual entry
                    )
                    db.add(new_trivia)
                    db.commit()
                    st.success(f"登録しました: {title}")
                except Exception as e:
                    st.error(f"エラーが発生しました: {e}")

# --- Tab 2: Manage ---
with tab2:
    st.header("既存の雑学を管理")
    
    # Filter/Search
    search_query = st.text_input("🔍 検索 (タイトルまたは本文)", "")
    
    query = db.query(Trivia)
    if search_query:
        search = f"%{search_query}%"
        query = query.filter(Trivia.title.like(search) | Trivia.content.like(search))
        
    trivias = query.order_by(Trivia.id.desc()).all()
    
    st.write(f"全 {len(trivias)} 件")
    
    if not trivias:
        st.info("データが見つかりません。")
    else:
        for trivia in trivias:
            with st.expander(f"🆔 {trivia.id}: {trivia.title} ({trivia.category})"):
                with st.form(f"edit_form_{trivia.id}"):
                    e_title = st.text_input("タイトル", trivia.title)
                    e_content = st.text_area("本文", trivia.content)
                    e_explanation = st.text_area("解説", trivia.explanation)
                    col_e1, col_e2 = st.columns(2)
                    with col_e1:
                        e_category = st.selectbox("カテゴリ", ["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"], index=["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"].index(trivia.category) if trivia.category in ["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"] else 0)
                    with col_e2:
                        e_source = st.text_input("ソースURL", trivia.source)
                    
                    col_act1, col_act2 = st.columns([1, 5])
                    with col_act1:
                        update_submit = st.form_submit_button("更新")
                    with col_act2:
                        delete_submit = st.form_submit_button("削除", type="primary")
                        
                    if update_submit:
                        trivia.title = e_title
                        trivia.content = e_content
                        trivia.explanation = e_explanation
                        trivia.category = e_category
                        trivia.source = e_source
                        db.commit()
                        st.success("更新しました！")
                        st.rerun()
                        
                    if delete_submit:
                        db.delete(trivia)
                        db.commit()
                        st.warning("削除しました。")
                        st.rerun()

# Footer
st.divider()
st.caption("Daily Trivia Admin Tool v1.0")
