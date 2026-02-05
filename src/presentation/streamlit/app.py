"""
Streamlit Chat UI - 流式聊天介面

三欄佈局：側邊選單 + 考題操作區 + 常駐 Chat
支援：
- Crush 自動啟動與配置載入
- 真正的流式題目生成與即時預覽
- 題庫管理與作答練習
- 完整的 logging 追蹤
"""

import sys
from pathlib import Path
import re
import logging
import time

# 確保專案根目錄在 Python path 中
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import streamlit as st
from datetime import datetime
import subprocess
import json
import random
from typing import Generator, Optional
from dataclasses import dataclass

# 設定 logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 設定頁面
st.set_page_config(
    page_title="Anesthesia Exam Generator",
    page_icon="🩺",
    layout="wide",
)

# 路徑配置
CRUSH_PATH = Path(r"D:\workspace260203\crush\crush.exe")
DATA_DIR = PROJECT_DIR / "data"
QUESTIONS_DIR = DATA_DIR / "questions"
EXAMS_DIR = DATA_DIR / "exams"
CRUSH_CONFIG_PATH = PROJECT_DIR / "crush.json"


@dataclass
class CrushConfig:
    """Crush 配置"""
    executable_path: Path
    working_dir: Path
    model: Optional[str] = None
    mcp_servers: dict = None
    context_paths: list = None
    
    @classmethod
    def load(cls, config_path: Path = CRUSH_CONFIG_PATH) -> "CrushConfig":
        """從 crush.json 載入配置"""
        config = cls(
            executable_path=CRUSH_PATH,
            working_dir=PROJECT_DIR,
            mcp_servers={},
            context_paths=[],
        )
        
        if config_path.exists():
            try:
                with open(config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                
                # 載入 agent 模型
                if "agents" in data and "coder" in data["agents"]:
                    config.model = data["agents"]["coder"].get("model")
                
                # 載入 MCP servers
                config.mcp_servers = data.get("mcp", {})
                
                # 載入 context paths
                if "options" in data:
                    config.context_paths = data["options"].get("context_paths", [])
                    
            except Exception as e:
                logger.warning(f"載入 crush.json 失敗: {e}")
        
        return config


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


def parse_mcp_result(text: str) -> Optional[dict]:
    """
    從 Crush 輸出中解析 MCP 工具調用結果
    """
    # 尋找 JSON 格式的結果
    patterns = [
        r'\{[^{}]*"question_id"\s*:\s*"[^"]+?"[^{}]*\}',
        r'\{[^{}]*"success"\s*:\s*true[^{}]*\}',
    ]
    
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            try:
                result = json.loads(match)
                if result.get("question_id"):
                    return result
            except json.JSONDecodeError:
                continue
    
    # 尋找題目 ID 格式
    id_match = re.search(r'題目\s*ID[：:]\s*[`"]?([a-f0-9-]{36})[`"]?', text)
    if id_match:
        return {"question_id": id_match.group(1), "success": True}
    
    return None


def parse_question_from_output(text: str) -> Optional[dict]:
    """從 AI 輸出中解析題目內容"""
    question = {}
    
    # 解析題目文字
    q_patterns = [
        r'\*\*題目[：:]\*\*\s*(.+?)(?=\*\*選項|\*\*Options|[A-D][.、]|$)',
        r'題目[：:]\s*(.+?)(?=選項|[A-D][.、]|$)',
    ]
    
    for pattern in q_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["question_text"] = match.group(1).strip()
            break
    
    # 解析選項
    options = []
    opt_pattern = r'([A-D])[.、:：]\s*(.+?)(?=[A-D][.、:：]|\*\*答案|\*\*正確|答案[：:]|$)'
    for match in re.finditer(opt_pattern, text, re.DOTALL):
        opt_text = match.group(2).strip()
        if opt_text and len(opt_text) > 1:
            options.append(opt_text)
    if options:
        question["options"] = options
    
    # 解析答案
    ans_patterns = [
        r'\*\*(?:答案|正確答案)[：:]\*\*\s*([A-D])',
        r'(?:答案|正確答案)[：:]\s*([A-D])',
    ]
    
    for pattern in ans_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            question["correct_answer"] = match.group(1).upper()
            break
    
    # 解析難度
    diff_match = re.search(r'難度[：:]\s*(easy|medium|hard|簡單|中等|困難)', text, re.IGNORECASE)
    if diff_match:
        diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
        question["difficulty"] = diff_map.get(diff_match.group(1), diff_match.group(1).lower())
    
    # 解析詳解
    exp_patterns = [
        r'\*\*(?:解析|詳解)[：:]\*\*\s*(.+?)(?=\*\*|題目 ID|$)',
        r'(?:解析|詳解)[：:]\s*(.+?)(?=題目|$)',
    ]
    
    for pattern in exp_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["explanation"] = match.group(1).strip()
            break
    
    if question.get("question_text") and question.get("options"):
        return question
    
    return None


def stream_crush_generate(
    prompt: str,
    config: CrushConfig,
    output_placeholder,
    questions_container,
    progress_placeholder,
) -> tuple[str, list[dict]]:
    """
    真正的流式生成 - 不使用 st.spinner，持續更新 UI
    
    Returns:
        (full_output, saved_questions)
    """
    cmd = [
        str(config.executable_path),
        "run",
        "--cwd", str(config.working_dir),
        prompt
    ]
    
    logger.info(f"Starting Crush generation...")
    
    process = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        encoding='utf-8',
        errors='replace',
    )
    
    full_response = ""
    current_question_buffer = ""
    saved_questions = []
    last_update_time = time.time()
    
    try:
        for line in iter(process.stdout.readline, ''):
            if not line:
                continue
            
            full_response += line
            current_question_buffer += line
            
            # 每 100ms 更新一次 UI，避免過於頻繁
            current_time = time.time()
            if current_time - last_update_time > 0.1:
                # 更新 AI 輸出顯示
                display_text = full_response[-3000:] if len(full_response) > 3000 else full_response
                output_placeholder.markdown(f"```\n{display_text}\n```")
                
                # 更新進度
                progress_placeholder.markdown(f"⏳ 已接收 {len(full_response)} 字元，已儲存 {len(saved_questions)} 題")
                
                last_update_time = current_time
            
            # 檢查是否有新題目被儲存
            mcp_result = parse_mcp_result(current_question_buffer)
            if mcp_result and mcp_result.get("question_id"):
                logger.info(f"MCP result detected: {mcp_result.get('question_id')}")
                
                # 解析題目內容
                parsed_q = parse_question_from_output(current_question_buffer)
                if parsed_q:
                    parsed_q["id"] = mcp_result.get("question_id")
                    saved_questions.append(parsed_q)
                    
                    logger.info(f"Question {len(saved_questions)} saved: {parsed_q.get('question_text', '')[:50]}...")
                    
                    # 即時顯示題目卡片
                    with questions_container:
                        render_question_card_inline(parsed_q, len(saved_questions))
                
                # 重置緩衝區
                current_question_buffer = ""
        
        process.wait()
        
        # 最終更新
        output_placeholder.markdown(f"```\n{full_response[-3000:]}\n```")
        
        if process.returncode != 0:
            logger.error(f"Crush exited with code {process.returncode}")
        
    except Exception as e:
        logger.error(f"Generation error: {e}")
        output_placeholder.error(f"生成錯誤: {e}")
    finally:
        process.terminate()
    
    return full_response, saved_questions


def render_question_card_inline(question: dict, index: int):
    """在容器內渲染題目卡片（用於流式生成時）"""
    st.markdown(f"---")
    st.markdown(f"### ✅ 第 {index} 題 (已儲存)")
    st.markdown(f"**{question.get('question_text', '')}**")
    
    options = question.get("options", [])
    for j, opt in enumerate(options):
        prefix = chr(65 + j)
        if prefix == question.get("correct_answer"):
            st.markdown(f"✅ **{prefix}. {opt}**")
        else:
            st.markdown(f"　{prefix}. {opt}")
    
    col1, col2 = st.columns(2)
    with col1:
        st.caption(f"📝 答案: {question.get('correct_answer', 'N/A')}")
    with col2:
        diff = question.get("difficulty", "medium")
        diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "⚪")
        st.caption(f"{diff_emoji} 難度: {diff}")
    
    if question.get("explanation"):
        with st.expander("📖 查看詳解"):
            st.write(question.get("explanation"))
    
    st.caption(f"🆔 {question.get('id', 'N/A')}")


def render_question_card(question: dict, index: int, show_answer: bool = False):
    """渲染題目卡片"""
    with st.container():
        st.markdown(f"### 📝 第 {index} 題")
        st.markdown(question.get("question_text", ""))
        
        options = question.get("options", [])
        for j, opt in enumerate(options):
            prefix = chr(65 + j)
            if show_answer and prefix == question.get("correct_answer"):
                st.markdown(f"✅ **{prefix}. {opt}**")
            else:
                st.markdown(f"- {prefix}. {opt}")
        
        if show_answer:
            st.info(f"**答案:** {question.get('correct_answer', 'N/A')}")
            if question.get("explanation"):
                st.caption(f"📖 {question.get('explanation')}")
        
        # 顯示元資料
        col1, col2 = st.columns(2)
        with col1:
            diff = question.get("difficulty", "medium")
            diff_emoji = {"easy": "🟢", "medium": "🟡", "hard": "🔴"}.get(diff, "⚪")
            st.caption(f"{diff_emoji} 難度: {diff}")
        with col2:
            topics = question.get("topics", [])
            if topics:
                st.caption(f"🏷️ {', '.join(topics)}")
        
        st.markdown("---")


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

if "crush_config" not in st.session_state:
    st.session_state.crush_config = CrushConfig.load()

if "crush_available" not in st.session_state:
    st.session_state.crush_available = check_crush_connection()

if "current_page" not in st.session_state:
    st.session_state.current_page = "generate"

# 生成狀態
if "generated_questions" not in st.session_state:
    st.session_state.generated_questions = []
if "is_generating" not in st.session_state:
    st.session_state.is_generating = False

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
    
    # Crush 配置資訊
    config = st.session_state.crush_config
    status = "🟢 已連線" if st.session_state.crush_available else "🔴 未連線"
    st.markdown(f"**Crush 狀態:** {status}")
    
    if config.model:
        st.caption(f"模型: {config.model}")
    
    if config.mcp_servers:
        with st.expander("MCP Servers"):
            for name in config.mcp_servers.keys():
                st.caption(f"• {name}")
    
    if st.button("🔄 重新連線"):
        st.session_state.crush_config = CrushConfig.load()
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
        st.caption("智能生成麻醉學專科考題，即時預覽生成結果")
        
        # 分成上下兩區：配置區 + 預覽區
        config_section, preview_section = st.container(), st.container()
        
        with config_section:
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
        
        # 預覽區
        with preview_section:
            if submitted:
                if not st.session_state.crush_available:
                    st.error("❌ Crush 未連線，無法生成")
                else:
                    # 清空之前的生成結果
                    st.session_state.generated_questions = []
                    st.session_state.is_generating = True
                    
                    # 構建 prompt
                    diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                    type_map = {"單選題": "MCQ 選擇題", "多選題": "多選題", "是非題": "是非題"}
                    skill_trigger = type_map.get(question_type, "選擇題")
                    diff_en = diff_map.get(difficulty, "medium")
                    
                    prompt = f"""請生成 {num_questions} 道{skill_trigger}。

## 考題配置
- 題型: {question_type}
- 難度: {difficulty} ({diff_en})
- 題數: {num_questions}
"""
                    if topics:
                        prompt += f"- 知識點範圍: {', '.join(topics)}\n"
                    if source_doc:
                        prompt += f"- 參考教材: {source_doc}\n"
                    if additional_instructions:
                        prompt += f"- 額外要求: {additional_instructions}\n"
                    
                    prompt += """
## 重要指示
1. 每生成一題，**立即**使用 `exam_save_question` MCP 工具儲存
2. 儲存後繼續生成下一題
3. 每題必須包含完整資訊

## 每題格式
**題目:** [題目文字]
**選項:**
A. [選項A]
B. [選項B]
C. [選項C]
D. [選項D]
**答案:** [A/B/C/D]
**難度:** [easy/medium/hard]
**解析:** [詳細解說]

## MCP 工具參數
exam_save_question 需要：
- question_text: 題目文字
- options: ["選項A", "選項B", "選項C", "選項D"]
- correct_answer: "A" (或 B/C/D)
- explanation: 詳解
- difficulty: "{diff_en}"
- topics: {json.dumps(topics if topics else ["麻醉學"], ensure_ascii=False)}

請開始生成第 1 題。"""
                    
                    logger.info(f"Starting generation: {num_questions} questions")
                    
                    # 建立 UI 元素
                    st.markdown("---")
                    st.subheader("🚀 生成中...")
                    
                    # 進度顯示（在最上方）
                    progress_placeholder = st.empty()
                    progress_placeholder.info("⏳ 正在初始化 Crush AI...")
                    
                    # 建立兩欄：左邊 AI 輸出，右邊題目預覽
                    output_col, preview_col = st.columns([1, 1])
                    
                    with output_col:
                        st.markdown("#### 🤖 AI 輸出")
                        output_placeholder = st.empty()
                        output_placeholder.code("等待 AI 回應...", language="text")
                    
                    with preview_col:
                        st.markdown("#### 📋 已儲存的題目")
                        questions_container = st.container()
                        with questions_container:
                            st.caption("題目將在儲存後顯示於此...")
                    
                    # 執行流式生成（不使用 st.spinner）
                    config = st.session_state.crush_config
                    full_response, saved_questions = stream_crush_generate(
                        prompt=prompt,
                        config=config,
                        output_placeholder=output_placeholder,
                        questions_container=questions_container,
                        progress_placeholder=progress_placeholder,
                    )
                    
                    # 更新 session state
                    st.session_state.generated_questions = saved_questions
                    st.session_state.is_generating = False
                    
                    logger.info(f"Generation completed: {len(saved_questions)} questions saved")
                    
                    # 完成訊息
                    if len(saved_questions) > 0:
                        progress_placeholder.success(f"✅ 生成完成！共儲存 {len(saved_questions)} 題到題庫。")
                        
                        # 顯示操作按鈕
                        st.markdown("---")
                        col1, col2, col3 = st.columns(3)
                        with col1:
                            if st.button("🔄 再生成一批", use_container_width=True):
                                st.session_state.generated_questions = []
                                st.rerun()
                        with col2:
                            if st.button("✍️ 立即練習", use_container_width=True):
                                st.session_state.practice_questions = saved_questions.copy()
                                st.session_state.practice_answers = {}
                                st.session_state.practice_submitted = False
                                st.rerun()
                        with col3:
                            if st.button("📚 查看題庫", use_container_width=True):
                                st.rerun()
                    else:
                        progress_placeholder.warning("⚠️ 生成完成，但未偵測到儲存的題目。請檢查 AI 輸出。")
                        
                        # 顯示可能原因
                        with st.expander("🔍 除錯資訊"):
                            st.markdown("**可能原因：**")
                            st.markdown("1. AI 沒有正確呼叫 `exam_save_question` MCP 工具")
                            st.markdown("2. MCP Server 沒有正常啟動")
                            st.markdown("3. 題目格式解析失敗")
                            st.markdown("---")
                            st.markdown("**完整輸出：**")
                            st.code(full_response, language="text")
            
            # 如果有之前生成的題目，也顯示出來
            elif st.session_state.generated_questions:
                st.subheader("📋 最近生成的題目")
                for i, q in enumerate(st.session_state.generated_questions):
                    render_question_card(q, i + 1, show_answer=True)
    
    
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
                    source = q.get("source") or {}
                    if source and source.get("document"):
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
