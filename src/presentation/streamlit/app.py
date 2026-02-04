"""
Streamlit Chat UI - 流式聊天介面

三欄佈局：側邊選單 + 考題操作區 + 常駐 Chat
"""

import sys
from pathlib import Path

# 確保專案根目錄在 Python path 中
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st
from datetime import datetime
import subprocess
import json
import random
from typing import Generator

# 設定頁面
st.set_page_config(
    page_title="Anesthesia Exam Generator",
    page_icon="🩺",
    layout="wide",
)

# Crush 執行檔路徑
CRUSH_PATH = Path(r"D:\workspace260203\crush\crush.exe")
DATA_DIR = PROJECT_DIR / "data"
QUESTIONS_DIR = DATA_DIR / "questions"
EXAMS_DIR = DATA_DIR / "exams"


def check_crush_connection() -> bool:
    """檢查 Crush 是否可用"""
    if not CRUSH_PATH.exists():
        return False
    try:
        result = subprocess.run(
            [str(CRUSH_PATH), "--version"],
            capture_output=True,
            text=True,
            timeout=5,
            encoding='utf-8',
            errors='replace',
        )
        return result.returncode == 0
    except Exception:
        return False


def stream_crush_response(prompt: str) -> Generator[str, None, None]:
    """
    流式執行 Crush 命令
    """
    cmd = [
        str(CRUSH_PATH),
        "run",
        "--quiet",
        "--cwd", str(PROJECT_DIR),
        prompt
    ]
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
    )
    
    try:
        if process.stdout is None:
            yield "[錯誤] 無法取得輸出"
            return
            
        for line in iter(process.stdout.readline, ''):
            if line:
                yield line
        
        process.wait()
        
        if process.returncode != 0 and process.stderr:
            stderr = process.stderr.read()
            if stderr:
                yield f"\n[警告] {stderr}"
                
    except Exception as e:
        yield f"\n[錯誤] {e}"
    finally:
        process.terminate()


def run_crush_sync(prompt: str) -> str:
    """同步執行 Crush 命令"""
    cmd = [
        str(CRUSH_PATH),
        "run",
        "--quiet",
        "--cwd", str(PROJECT_DIR),
        prompt
    ]
    
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=300,
            encoding='utf-8',
            errors='replace',
        )
        return result.stdout or result.stderr or "無回應"
    except subprocess.TimeoutExpired:
        return "[錯誤] 執行超時"
    except Exception as e:
        return f"[錯誤] {e}"


def get_questions_stats() -> dict:
    """取得題庫統計 (使用 SQLite Repository)"""
    from src.infrastructure.persistence.sqlite_question_repo import get_question_repository
    
    EXAMS_DIR.mkdir(parents=True, exist_ok=True)
    
    repo = get_question_repository()
    stats = repo.get_statistics()
    exams = list(EXAMS_DIR.glob("*.json"))
    
    return {
        "question_count": stats["total"],
        "exam_count": len(exams),
        "difficulty": stats["by_difficulty"],
        "validated": stats["validated"],
        "by_topic": stats["by_topic"],
    }


def load_questions() -> list[dict]:
    """載入所有題目 (使用 SQLite Repository)"""
    from src.infrastructure.persistence.sqlite_question_repo import get_question_repository
    
    repo = get_question_repository()
    questions = repo.list_all(limit=500)
    
    return [q.to_dict() for q in questions]


# ===== 初始化 session state =====
if "messages" not in st.session_state:
    st.session_state.messages = []

if "crush_available" not in st.session_state:
    st.session_state.crush_available = check_crush_connection()

if "current_page" not in st.session_state:
    st.session_state.current_page = "generate"

# 作答練習狀態
if "practice_questions" not in st.session_state:
    st.session_state.practice_questions = []
if "practice_answers" not in st.session_state:
    st.session_state.practice_answers = {}
if "practice_submitted" not in st.session_state:
    st.session_state.practice_submitted = False
if "show_explanations" not in st.session_state:
    st.session_state.show_explanations = {}


# ===== 側邊欄 (左側導航) =====
with st.sidebar:
    st.title("🩺 考卷生成系統")
    st.markdown("---")
    
    # 導航
    st.subheader("📌 導航")
    page = st.radio(
        "選擇頁面",
        ["📝 生成考題", "✍️ 作答練習", "📚 題庫管理", "📊 統計"],
        label_visibility="collapsed",
    )
    
    st.markdown("---")
    
    # 連線狀態
    status = "🟢 已連線" if st.session_state.crush_available else "🔴 未連線"
    st.markdown(f"**Crush 狀態:** {status}")
    
    if st.button("🔄 重新檢查"):
        st.session_state.crush_available = check_crush_connection()
        st.rerun()
    
    st.markdown("---")
    
    # 題庫概況
    stats = get_questions_stats()
    st.subheader("📈 題庫概況")
    sb_col1, sb_col2 = st.columns(2)
    with sb_col1:
        st.metric("題目數", stats["question_count"])
    with sb_col2:
        st.metric("考卷數", stats["exam_count"])


# ===== 主區域：三欄佈局 (操作區 2/3 + 常駐 Chat 1/3) =====
main_col, chat_col = st.columns([2, 1], gap="medium")


# ===== 左欄：操作區內容 =====
with main_col:
    
    if page == "📝 生成考題":
        # ===== 考題生成頁面 =====
        st.header("📝 AI 考題生成")
        st.caption("智能生成麻醉學專科考題")
        
        with st.form("exam_generation_form"):
            st.subheader("📋 生成配置")
            
            col1, col2 = st.columns(2)
            
            with col1:
                question_type = st.selectbox(
                    "題型",
                    ["單選題", "多選題", "是非題"],
                    index=0,
                )
                
                difficulty = st.select_slider(
                    "難度",
                    options=["簡單", "中等", "困難"],
                    value="中等",
                )
            
            with col2:
                num_questions = st.number_input(
                    "題數",
                    min_value=1,
                    max_value=20,
                    value=5,
                )
                
                topics = st.multiselect(
                    "知識點範圍（可選）",
                    ["全身麻醉", "局部麻醉", "藥理學", "生理學", "監測", "疼痛醫學", "重症加護"],
                    default=[],
                )
            
            st.markdown("---")
            
            source_doc = st.text_input(
                "參考教材（可選）",
                placeholder="如：Miller's Anesthesia 第9版",
            )
            
            additional_instructions = st.text_area(
                "額外指示（可選）",
                placeholder="如：請包含臨床案例分析...",
                height=100,
            )
            
            submitted = st.form_submit_button("🚀 開始生成", use_container_width=True, type="primary")
        
        if submitted:
            if not st.session_state.crush_available:
                st.error("❌ Crush 未連線，無法生成")
            else:
                # 構建 prompt
                diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                type_map = {"單選題": "MCQ 選擇題", "多選題": "多選題", "是非題": "是非題"}
                skill_trigger = type_map.get(question_type, "選擇題")
                
                prompt = f"""請生成 {num_questions} 道{skill_trigger}。

## 考題配置
- 題型: {question_type}
- 難度: {difficulty}
- 題數: {num_questions}
"""
                if topics:
                    prompt += f"- 知識點範圍: {', '.join(topics)}\n"
                if source_doc:
                    prompt += f"- 參考教材: {source_doc}\n"
                if additional_instructions:
                    prompt += f"- 額外要求: {additional_instructions}\n"
                
                prompt += """
## 輸出要求
請使用 exam_save_question MCP 工具儲存每一題到題庫。

每題必須包含：
1. question_text: 題目文字
2. options: 4 個選項 (A, B, C, D)
3. correct_answer: 正確答案代號
4. explanation: 詳細解析
5. difficulty: 難度 (easy/medium/hard)
6. topics: 知識點標籤陣列
7. source: 來源資訊 (document, page)

請逐題生成並使用 exam_save_question 工具儲存。"""
                
                st.subheader("🔄 生成進度")
                progress_container = st.empty()
                
                with st.spinner("AI 正在生成考題..."):
                    full_response = ""
                    for chunk in stream_crush_response(prompt):
                        full_response += chunk
                        progress_container.markdown(full_response + "▌")
                    progress_container.markdown(full_response)
                
                st.success("✅ 生成完成！請前往「題庫管理」查看結果。")
    
    
    elif page == "✍️ 作答練習":
        # ===== 作答練習頁面 =====
        st.header("✍️ 作答練習")
        st.caption("從題庫選題進行練習")
        
        # 設定區
        with st.expander("📋 練習設定", expanded=not st.session_state.practice_questions):
            col1, col2 = st.columns(2)
            
            with col1:
                practice_count = st.number_input(
                    "題數",
                    min_value=1,
                    max_value=50,
                    value=10,
                )
                
                practice_difficulty = st.selectbox(
                    "難度篩選",
                    ["全部", "簡單", "中等", "困難"],
                    index=0,
                )
            
            with col2:
                practice_random = st.checkbox("隨機順序", value=True)
            
            if st.button("🎯 開始練習", use_container_width=True, type="primary"):
                # 載入並篩選題目
                all_questions = load_questions()
                
                # 難度篩選
                diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                if practice_difficulty != "全部":
                    diff_filter = diff_map.get(practice_difficulty)
                    all_questions = [q for q in all_questions if q.get("difficulty") == diff_filter]
                
                # 隨機/選取
                if practice_random:
                    random.shuffle(all_questions)
                
                st.session_state.practice_questions = all_questions[:practice_count]
                st.session_state.practice_answers = {}
                st.session_state.practice_submitted = False
                st.session_state.show_explanations = {}
                st.rerun()
        
        # 作答區
        if st.session_state.practice_questions:
            questions = st.session_state.practice_questions
            
            # 進度顯示
            answered = len([a for a in st.session_state.practice_answers.values() if a])
            st.progress(answered / len(questions), text=f"已作答 {answered}/{len(questions)} 題")
            
            st.markdown("---")
            
            # 題目列表
            for i, q in enumerate(questions):
                q_id = q.get("id", str(i))
                
                with st.container():
                    st.markdown(f"### 第 {i+1} 題")
                    st.markdown(q.get("question_text", ""))
                    
                    # 選項
                    options = q.get("options", [])
                    option_labels = [f"{chr(65+j)}. {opt}" if not opt.startswith(chr(65+j)) else opt 
                                     for j, opt in enumerate(options)]
                    
                    # 作答
                    current_answer = st.session_state.practice_answers.get(q_id, "")
                    try:
                        current_index = option_labels.index(current_answer) if current_answer in option_labels else None
                    except ValueError:
                        current_index = None
                    
                    selected = st.radio(
                        f"選擇答案 (題目 {i+1})",
                        options=option_labels,
                        index=current_index,
                        key=f"q_{q_id}",
                        label_visibility="collapsed",
                        disabled=st.session_state.practice_submitted,
                    )
                    
                    if selected:
                        st.session_state.practice_answers[q_id] = selected
                    
                    # 已提交時顯示結果
                    if st.session_state.practice_submitted:
                        correct = q.get("correct_answer", "")
                        user_answer = st.session_state.practice_answers.get(q_id, "")
                        user_letter = user_answer[0] if user_answer else ""
                        
                        if user_letter == correct:
                            st.success(f"✅ 正確！答案：{correct}")
                        else:
                            st.error(f"❌ 錯誤！您的答案：{user_letter}，正確答案：{correct}")
                        
                        # 詳解按鈕
                        if st.button(f"📖 查看詳解", key=f"exp_{q_id}"):
                            st.session_state.show_explanations[q_id] = not st.session_state.show_explanations.get(q_id, False)
                        
                        if st.session_state.show_explanations.get(q_id, False):
                            st.info(q.get("explanation", "暫無詳解"))
                            
                            # 來源資訊
                            source = q.get("source", {})
                            if source.get("document"):
                                st.caption(f"📚 來源: {source.get('document')} (P.{source.get('page', '?')})")
                    
                    st.markdown("---")
            
            # 提交按鈕
            if not st.session_state.practice_submitted:
                col1, col2, col3 = st.columns([1, 1, 1])
                with col2:
                    if st.button("📤 提交答案", use_container_width=True, type="primary"):
                        st.session_state.practice_submitted = True
                        st.rerun()
            else:
                # 成績統計
                correct_count = 0
                for q in questions:
                    q_id = q.get("id", "")
                    user_answer = st.session_state.practice_answers.get(q_id, "")
                    user_letter = user_answer[0] if user_answer else ""
                    if user_letter == q.get("correct_answer", ""):
                        correct_count += 1
                
                score = (correct_count / len(questions)) * 100
                st.success(f"🎉 本次成績：{correct_count}/{len(questions)} 題 ({score:.1f}%)")
                
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("🔄 重新練習", use_container_width=True):
                        st.session_state.practice_questions = []
                        st.session_state.practice_answers = {}
                        st.session_state.practice_submitted = False
                        st.session_state.show_explanations = {}
                        st.rerun()
                with col2:
                    if st.button("📝 新的練習", use_container_width=True):
                        st.session_state.practice_questions = []
                        st.rerun()
        else:
            st.info("👆 請先設定練習參數並開始練習")
    
    
    elif page == "📚 題庫管理":
        # ===== 題庫管理頁面 =====
        st.header("📚 題庫管理")
        st.caption("瀏覽和管理已生成的考題")
        
        # 刷新按鈕
        col1, col2, col3 = st.columns([1, 1, 2])
        with col1:
            if st.button("🔄 刷新題庫", use_container_width=True):
                st.rerun()
        
        questions = load_questions()
        
        if not questions:
            st.info("📭 題庫空空如也，請先生成考題！")
        else:
            st.markdown(f"**共 {len(questions)} 題**")
            st.markdown("---")
            
            for i, q in enumerate(questions):
                with st.expander(f"#{i+1} {q.get('question_text', '無題目')[:50]}..."):
                    st.markdown(f"**題目:** {q.get('question_text', '')}")
                    
                    st.markdown("**選項:**")
                    for j, opt in enumerate(q.get("options", [])):
                        prefix = chr(65 + j)
                        st.markdown(f"- {prefix}. {opt}")
                    
                    col1, col2, col3 = st.columns(3)
                    with col1:
                        st.markdown(f"**答案:** {q.get('correct_answer', 'N/A')}")
                    with col2:
                        st.markdown(f"**難度:** {q.get('difficulty', 'medium')}")
                    with col3:
                        st.markdown(f"**知識點:** {', '.join(q.get('topics', []))}")
                    
                    if q.get("explanation"):
                        st.markdown(f"**解析:** {q.get('explanation', '')}")
                    
                    # 來源資訊
                    source = q.get("source", {})
                    if source.get("document"):
                        st.caption(f"來源: {source.get('document')} (P.{source.get('page', '?')})")
    
    
    elif page == "📊 統計":
        # ===== 統計頁面 =====
        st.header("📊 題庫統計")
        
        stats = get_questions_stats()
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.metric("📝 總題數", stats["question_count"])
            st.metric("📄 考卷數", stats["exam_count"])
        
        with col2:
            st.subheader("難度分布")
            diff = stats["difficulty"]
            total = sum(diff.values()) or 1
            
            st.progress(diff["easy"] / total, text=f"簡單: {diff['easy']} 題")
            st.progress(diff["medium"] / total, text=f"中等: {diff['medium']} 題")
            st.progress(diff["hard"] / total, text=f"困難: {diff['hard']} 題")
        
        st.markdown("---")
        
        # 最近生成
        st.subheader("📅 最近生成")
        questions = load_questions()[:5]
        
        if questions:
            for q in questions:
                st.markdown(f"- {q.get('question_text', '')[:60]}...")
        else:
            st.info("尚無題目")


# ===== 右欄：常駐 Chat =====
with chat_col:
    st.subheader("💬 AI 助手")
    
    # Chat 容器 (使用 container 限制高度)
    chat_container = st.container(height=500)
    
    with chat_container:
        # 顯示對話歷史
        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])
    
    # 輸入區
    if not st.session_state.crush_available:
        st.warning("⚠️ Crush 未連線")
    
    prompt = st.chat_input("輸入問題...", key="chat_input")
    
    if prompt:
        # 添加用戶訊息
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now().isoformat()
        })
        
        # 生成回應
        if st.session_state.crush_available:
            with st.spinner("思考中..."):
                try:
                    full_response = ""
                    for chunk in stream_crush_response(prompt):
                        full_response += chunk
                    response = full_response if full_response else "無回應"
                except Exception:
                    response = run_crush_sync(prompt)
        else:
            response = "[錯誤] Crush 未連線"
        
        # 添加助手訊息
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat()
        })
        
        st.rerun()
    
    # 清除對話按鈕
    if st.session_state.messages:
        if st.button("🗑️ 清除對話", use_container_width=True):
            st.session_state.messages = []
            st.rerun()


# ===== 底部資訊 =====
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"對話數: {len(st.session_state.messages)}")
with col2:
    st.caption("模型: copilot/gpt-5-mini")
with col3:
    st.caption(f"Crush: {'已連線' if st.session_state.crush_available else '未連線'}")
