import os
import json
from dotenv import load_dotenv
from openai import OpenAI
import streamlit as st
import pandas as pd
import difflib
import requests
from sqlalchemy.orm import Session
from database import SessionLocal
from models import Trivia
from datetime import datetime

# Load env vars
load_dotenv()

# Configure OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    st.warning("⚠️ OPENAI_API_KEY not found in .env file.")
client = OpenAI(api_key=OPENAI_API_KEY) if OPENAI_API_KEY else None

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
tab1, tab2, tab3 = st.tabs(["🆕 新規登録", "🤖 AI収集", "🛠️ 管理・編集"])

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

# --- Tab 2: AI Collection ---
with tab2:
    st.header("🤖 AIで雑学を収集")

    if not client:
        st.error("APIキーが設定されていません。.envファイルに OPENAI_API_KEY を設定してください。")
    else:
        # Initialize session state for AI trivia
        if 'ai_trivia_list' not in st.session_state:
            st.session_state.ai_trivia_list = []

        with st.form("ai_gen_form"):
            col_ai1, col_ai2 = st.columns([3, 1])
            with col_ai1:
                topic = st.text_input("トピック (例: 宇宙, 猫, 歴史)", placeholder="何についての雑学を集めますか？")
            with col_ai2:
                count = st.number_input("生成件数", min_value=1, max_value=10, value=3)
            
            generate_submitted = st.form_submit_button("生成開始", type="primary")

        if generate_submitted:
            target_topic = topic if topic else "ランダムで幅広いジャンル"
            with st.spinner(f"「{target_topic}」に関する雑学・豆知識を {count} 件生成中..."):
                try:
                    # 1. Fetch existing trivia related to the topic to prevent duplicates
                    search = f"%{target_topic}%"
                    existing_entries = db.query(Trivia.title).filter(Trivia.title.like(search) | Trivia.content.like(search)).limit(50).all()
                    existing_titles = [e[0] for e in existing_entries]
                    
                    exclusion_text = ""
                    if existing_titles:
                        exclusion_text = f"\n\n【除外リスト】以下の雑学は既にデータベースに存在します。これらと重複する内容（タイトルやネタ被り）は絶対に避けてください：\n" + "\n".join([f"- {t}" for t in existing_titles])

                    prompt = f"""
                    「{target_topic}」に関する面白い雑学・豆知識を{count}件生成してください。
                    以下のJSONフォーマットのオブジェクト形式で出力してください。
                    キーは "trivia" とし、値はそのリストにしてください。
                    
                    keys = "trivia"
                    
                    【重要】ソース（出典）は**必ず「http://」または「https://」で始まる有効なURL**にしてください。
                    書籍名だけや、「不明」などの単語はNGです。
                    URLが存在しない場合は、その雑学自体を生成しないでください。
                    {exclusion_text}

                    {{
                        "trivia": [
                            {{
                                "title": "タイトル（30文字以内）",
                                "content": "本文（です・ます調。100〜150文字程度。改行は含めないでください）",
                                "explanation": "詳細な解説や背景（200文字程度）",
                                "category": "カテゴリ（一般, 歴史, 科学, 生物, 生活, 芸術, スポーツ, IT, その他 から選択）",
                                "source": "https://example.com/article... (必須。http/httpsから始まるURL)"
                            }}
                        ]
                    }}
                    """
                    
                    response = client.chat.completions.create(
                        model="gpt-5-mini",
                        messages=[
                            {"role": "system", "content": "You are a helpful assistant that generates JSON. You always provide reliable sources."},
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
                    all_existing_data = db.query(Trivia.title, Trivia.content).all()
                    
                    unique_items = []
                    duplicates_count = 0
                    
                    for item in new_items:
                        if not isinstance(item, dict):
                            continue
                            
                        is_duplicate = False
                        new_title = item.get("title", "")
                        new_content = item.get("content", "")
                        
                        # Check against DB
                        for db_title, db_content in all_existing_data:
                            # Check Title Similarity
                            title_ratio = difflib.SequenceMatcher(None, new_title, db_title).ratio()
                            # Check Content Similarity (if titles are different but content is same)
                            content_ratio = difflib.SequenceMatcher(None, new_content, db_content).ratio()
                            
                            # Threshold: 0.8 (80% similar)
                            if title_ratio > 0.8 or content_ratio > 0.8:
                                is_duplicate = True
                                break
                        
                        if not is_duplicate:
                             unique_items.append(item)
                        else:
                            duplicates_count += 1
                    
                    st.session_state.ai_trivia_list.extend(unique_items)
                    
                    msg = f"{len(unique_items)} 件生成しました！下のリストから確認・承認してください。"
                    if duplicates_count > 0:
                        msg += f" (※重複・類似 {duplicates_count} 件を除外しました)"
                    st.success(msg)
                except Exception as e:
                    st.error(f"生成エラー: {e}")

        st.divider()
        st.subheader("承認待ちリスト")
        
        if st.button("リストをクリア"):
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
                            a_category = st.selectbox("カテゴリ", ["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"], index=["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"].index(item.get('category', '一般')) if item.get('category') in ["一般", "歴史", "科学", "生物", "生活", "芸術", "スポーツ", "IT", "その他"] else 0)
                            st.caption(f"ソース確認: {url_status_icon} {url_status_msg}")
                            a_source = st.text_input("ソース", source_url)
                        
                        btn_col1, btn_col2 = st.columns(2)
                        with btn_col1:
                            approve = st.form_submit_button("✅ 承認してDBに追加", type="primary")
                        with btn_col2:
                            reject = st.form_submit_button("🗑️ 削除（却下）")

                        if approve:
                            try:
                                new_trivia = Trivia(
                                    title=a_title,
                                    content=a_content,
                                    explanation=a_explanation,
                                    source=a_source,
                                    category=a_category
                                )
                                db.add(new_trivia)
                                db.commit()
                                st.session_state.ai_trivia_list.pop(i)
                                st.success("承認・保存しました！")
                                st.rerun()
                            except Exception as e:
                                st.error(f"保存エラー: {e}")
                        
                        if reject:
                            st.session_state.ai_trivia_list.pop(i)
                            st.warning("削除しました。")
                            st.rerun()

# --- Tab 3: Manage ---
with tab3:
    st.header("既存の雑学を管理")
    
    # --- Maintenance Section ---
    with st.expander("🔧 データメンテナンス (ソースURL修正)", expanded=False):
        st.write("ソースがURL(http/https)形式でないデータを検出し、AIで再検索して修正します。")
        
        # Find invalid sources
        all_trivias = db.query(Trivia).all()
        invalid_source_items = [
            t for t in all_trivias 
            if not t.source or not (t.source.startswith("http://") or t.source.startswith("https://"))
        ]
        
        st.write(f"修正対象: **{len(invalid_source_items)}** 件")
        
        if invalid_source_items:
            if st.button("♻️ ソース自動修正を開始 (OpenAI)"):
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
