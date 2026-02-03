"""
Streamlit Chat UI - 流式聊天介面

類似 ChatGPT/NotebookLM 的對話體驗
"""

import streamlit as st
from datetime import datetime
import subprocess
import json
from typing import Generator
from pathlib import Path

# 設定頁面
st.set_page_config(
    page_title="Anesthesia Exam Generator",
    page_icon="🩺",
    layout="wide",
)

# Crush 執行檔路徑
CRUSH_PATH = Path(r"D:\workspace260203\crush\crush.exe")
PROJECT_DIR = Path(r"D:\workspace260203\anesthesia-exam")
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
    """取得題庫統計"""
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    EXAMS_DIR.mkdir(parents=True, exist_ok=True)
    
    questions = list(QUESTIONS_DIR.glob("*.json"))
    exams = list(EXAMS_DIR.glob("*.json"))
    
    difficulty_stats = {"easy": 0, "medium": 0, "hard": 0}
    
    for qf in questions:
        try:
            with open(qf, "r", encoding="utf-8") as f:
                q = json.load(f)
            diff = q.get("difficulty", "medium")
            difficulty_stats[diff] = difficulty_stats.get(diff, 0) + 1
        except Exception:
            pass
    
    return {
        "question_count": len(questions),
        "exam_count": len(exams),
        "difficulty": difficulty_stats,
    }


def load_questions() -> list[dict]:
    """載入所有題目"""
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    questions = []
    
    for qf in sorted(QUESTIONS_DIR.glob("*.json"), reverse=True):
        try:
            with open(qf, "r", encoding="utf-8") as f:
                q = json.load(f)
            q["_filepath"] = str(qf)
            questions.append(q)
        except Exception:
            pass
    
    return questions


# 初始化 session state
if "messages" not in st.session_state:
    st.session_state.messages = []

if "crush_available" not in st.session_state:
    st.session_state.crush_available = check_crush_connection()

if "current_page" not in st.session_state:
    st.session_state.current_page = "chat"


# 側邊欄
with st.sidebar:
    st.title("🩺 考卷生成系統")
    st.markdown("---")
    
    # 導航
    st.subheader("📌 導航")
    page = st.radio(
        "選擇頁面",
        ["💬 AI 對話", "📝 生成考題", "📚 題庫管理", "📊 統計"],
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
    col1, col2 = st.columns(2)
    with col1:
        st.metric("題目數", stats["question_count"])
    with col2:
        st.metric("考卷數", stats["exam_count"])


# ===== 頁面內容 =====

if page == "💬 AI 對話":
    # ===== Chat 頁面 =====
    st.title("💬 AI 對話助手")
    st.caption("Powered by Crush + GitHub Copilot")
    
    # 快速操作
    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("🗑️ 清除對話", use_container_width=True):
            st.session_state.messages = []
            st.rerun()
    
    # 顯示對話歷史
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
    
    # 處理用戶輸入
    prompt = st.chat_input("輸入您的問題...")
    
    if prompt:
        st.session_state.messages.append({
            "role": "user",
            "content": prompt,
            "timestamp": datetime.now().isoformat()
        })
        
        with st.chat_message("user"):
            st.markdown(prompt)
        
        with st.chat_message("assistant"):
            if not st.session_state.crush_available:
                st.error("❌ Crush 未連線")
                response = "[錯誤] Crush 服務未連線"
            else:
                message_placeholder = st.empty()
                full_response = ""
                
                with st.spinner("思考中..."):
                    try:
                        for chunk in stream_crush_response(prompt):
                            full_response += chunk
                            message_placeholder.markdown(full_response + "▌")
                        message_placeholder.markdown(full_response)
                        response = full_response
                    except Exception as e:
                        response = run_crush_sync(prompt)
                        message_placeholder.markdown(response)
        
        st.session_state.messages.append({
            "role": "assistant",
            "content": response,
            "timestamp": datetime.now().isoformat()
        })


elif page == "📝 生成考題":
    # ===== 考題生成頁面 =====
    st.title("📝 AI 考題生成")
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
            type_map = {"單選題": "single_choice", "多選題": "multiple_choice", "是非題": "true_false"}
            
            prompt = f"""請生成 {num_questions} 道麻醉學 {question_type}。

要求：
- 難度: {difficulty}
- 題型: {question_type}
"""
            if topics:
                prompt += f"- 知識點範圍: {', '.join(topics)}\n"
            if source_doc:
                prompt += f"- 參考教材: {source_doc}\n"
            if additional_instructions:
                prompt += f"- 額外要求: {additional_instructions}\n"
            
            prompt += """
請使用 exam_save_question 工具儲存每一題。

每題必須包含：
1. 題目文字
2. 4 個選項
3. 正確答案
4. 詳細解析
5. 知識點標籤

請逐題生成並儲存。"""
            
            st.subheader("🔄 生成進度")
            progress_container = st.empty()
            output_container = st.container()
            
            with output_container:
                with st.spinner("AI 正在生成考題..."):
                    full_response = ""
                    for chunk in stream_crush_response(prompt):
                        full_response += chunk
                        progress_container.markdown(full_response + "▌")
                    progress_container.markdown(full_response)
            
            st.success("✅ 生成完成！請前往「題庫管理」查看結果。")
            
            # 刷新統計
            if st.button("🔄 刷新統計"):
                st.rerun()


elif page == "📚 題庫管理":
    # ===== 題庫管理頁面 =====
    st.title("📚 題庫管理")
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
    st.title("📊 題庫統計")
    
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


# 底部資訊
st.markdown("---")
col1, col2, col3 = st.columns(3)
with col1:
    st.caption(f"對話數: {len(st.session_state.messages)}")
with col2:
    st.caption("模型: copilot/gpt-5-mini")
with col3:
    st.caption(f"Crush: {'已連線' if st.session_state.crush_available else '未連線'}")
