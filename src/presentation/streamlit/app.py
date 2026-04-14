"""
Streamlit Chat UI - 流式聊天介面

三欄佈局：側邊選單 + 考題操作區 + 常駐 Chat
支援：
- Crush 自動啟動與配置載入
- 真正的流式題目生成與即時預覽
- 題庫管理與作答練習
- 完整的 logging 追蹤
"""

import html
import re
import sys
import time
from pathlib import Path

# 確保專案根目錄在 Python path 中
PROJECT_DIR = Path(__file__).parent.parent.parent.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

import json
import random
import subprocess
import uuid
from datetime import datetime
from typing import Optional

import streamlit as st

from src.infrastructure.agent import AgentProviderConfig, create_agent_provider
from src.infrastructure.logging import configure_logging, get_logger

# 初始化結構化 logging（JSON 寫入 logs/）
LOG_DIR = PROJECT_DIR / "logs"
configure_logging(log_dir=LOG_DIR, level="INFO")
logger = get_logger(__name__)

# 設定頁面
st.set_page_config(
    page_title="Anesthesia Exam Generator",
    page_icon="🩺",
    layout="wide",
)

# 路徑配置
DATA_DIR = PROJECT_DIR / "data"
QUESTIONS_DIR = DATA_DIR / "questions"
EXAMS_DIR = DATA_DIR / "exams"
UPLOADS_DIR = DATA_DIR / "sources" / "uploads"
ASSET_AWARE_DIR = PROJECT_DIR / "libs" / "asset-aware-mcp"
CRUSH_CONFIG_PATH = PROJECT_DIR / "crush.json"
OPENCODE_CONFIG_PATH = PROJECT_DIR / "opencode.json"
SOURCES_MANIFEST = DATA_DIR / "sources" / "manifest.json"

PROMPT_PRESETS = {
    "標準臨床題": "請優先出臨床情境導向題，干擾選項要合理且常見。",
    "高難鑑別題": "請提高鑑別難度，加入相似機轉藥物或監測陷阱，詳解需指出為何其他選項錯。",
    "教學詳解題": "每題請提供教學式詳解：核心觀念、臨床應用、常見誤解。",
}

PAGE_OPTIONS = ["📝 生成考題", "✍️ 作答練習", "📚 題庫管理", "� 出題需求", "�📊 統計"]

CHAT_QUICK_PROMPTS = [
    "幫我說明這個頁面的最佳操作順序。",
    "幫我檢查目前選題的詳解品質。",
    "請提供一個題目審閱 checklist。",
]


def inject_app_styles() -> None:
    """注入全域樣式，讓介面具有一致的視覺語言。"""
    st.markdown(
        """
        <style>
            :root {
                --bg: #f6f2e8;
                --bg-soft: rgba(255, 252, 246, 0.82);
                --surface: rgba(255, 255, 255, 0.78);
                --surface-strong: rgba(255, 255, 255, 0.92);
                --line: rgba(18, 82, 76, 0.12);
                --text: #163532;
                --muted: #5f7b76;
                --accent: #0f766e;
                --accent-soft: rgba(15, 118, 110, 0.12);
                --warm: #d97706;
                --shadow: 0 18px 42px rgba(22, 53, 50, 0.10);
                --radius: 22px;
            }

            .stApp {
                background:
                    radial-gradient(circle at top left, rgba(15, 118, 110, 0.10), transparent 28%),
                    radial-gradient(circle at top right, rgba(217, 119, 6, 0.10), transparent 22%),
                    linear-gradient(180deg, #fcfaf5 0%, var(--bg) 100%);
                color: var(--text);
            }

            [data-testid="stHeader"], [data-testid="stToolbar"], [data-testid="stDecoration"] {
                background: transparent !important;
            }

            [data-testid="stToolbar"] {
                display: none;
            }

            .block-container {
                padding-top: 1.4rem;
                padding-bottom: 2rem;
            }

            [data-testid="stSidebar"] {
                background: linear-gradient(180deg, rgba(241, 245, 249, 0.95) 0%, rgba(249, 250, 251, 0.92) 100%);
                border-right: 1px solid rgba(15, 118, 110, 0.10);
            }

            [data-testid="stSidebar"] .block-container {
                padding-top: 1.8rem;
            }

            div[data-testid="stVerticalBlockBorderWrapper"] {
                border: 1px solid var(--line);
                border-radius: var(--radius);
                background: var(--surface);
                box-shadow: var(--shadow);
            }

            h1, h2, h3 {
                color: var(--text);
                letter-spacing: -0.02em;
            }

            .app-hero {
                position: relative;
                overflow: hidden;
                padding: 1.5rem 1.6rem;
                border: 1px solid var(--line);
                border-radius: 28px;
                background:
                    linear-gradient(135deg, rgba(255,255,255,0.90) 0%, rgba(244, 251, 250, 0.92) 58%, rgba(255, 248, 238, 0.88) 100%);
                box-shadow: var(--shadow);
                margin-bottom: 1rem;
            }

            .app-hero::after {
                content: "";
                position: absolute;
                right: -20px;
                top: -30px;
                width: 180px;
                height: 180px;
                border-radius: 999px;
                background: radial-gradient(circle, rgba(15,118,110,0.15), transparent 68%);
            }

            .eyebrow {
                font-size: 0.78rem;
                font-weight: 700;
                letter-spacing: 0.12em;
                text-transform: uppercase;
                color: var(--accent);
                margin-bottom: 0.55rem;
            }

            .app-hero h2 {
                margin: 0;
                font-size: 2.15rem;
                line-height: 1.05;
            }

            .app-hero p {
                margin: 0.65rem 0 0;
                max-width: 46rem;
                font-size: 1rem;
                color: var(--muted);
                line-height: 1.6;
            }

            .hero-pills {
                display: flex;
                flex-wrap: wrap;
                gap: 0.55rem;
                margin-top: 1rem;
            }

            .hero-pill {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.42rem 0.78rem;
                border-radius: 999px;
                background: var(--surface-strong);
                border: 1px solid rgba(15, 118, 110, 0.14);
                font-size: 0.82rem;
                color: var(--text);
            }

            .section-note {
                padding: 0.9rem 1rem;
                border-radius: 16px;
                background: rgba(15, 118, 110, 0.08);
                border: 1px solid rgba(15, 118, 110, 0.10);
                color: var(--text);
                margin: 0.25rem 0 0.75rem;
            }

            .empty-state {
                padding: 1.1rem 1.2rem;
                border-radius: 18px;
                border: 1px dashed rgba(15, 118, 110, 0.24);
                background: rgba(255, 255, 255, 0.55);
                color: var(--muted);
            }

            .empty-state strong {
                display: block;
                color: var(--text);
                margin-bottom: 0.35rem;
            }

            .status-chip-good,
            .status-chip-warn {
                display: inline-flex;
                align-items: center;
                gap: 0.35rem;
                padding: 0.28rem 0.62rem;
                border-radius: 999px;
                font-size: 0.76rem;
                font-weight: 700;
            }

            .status-chip-good {
                background: rgba(22, 163, 74, 0.12);
                color: #166534;
            }

            .status-chip-warn {
                background: rgba(217, 119, 6, 0.12);
                color: #92400e;
            }

            .stChatMessage {
                background: rgba(255, 255, 255, 0.78);
                border: 1px solid rgba(15, 118, 110, 0.08);
                border-radius: 18px;
            }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_page_hero(title: str, subtitle: str, pills: list[str] | None = None) -> None:
    """渲染頁面 Hero 區塊。"""
    pills_markup = ""
    if pills:
        pill_nodes = "".join(f'<span class="hero-pill">{html.escape(pill)}</span>' for pill in pills if pill)
        pills_markup = f'<div class="hero-pills">{pill_nodes}</div>'

    st.markdown(
        f"""
        <section class="app-hero">
            <div class="eyebrow">Anesthesia Exam Workspace</div>
            <h2>{html.escape(title)}</h2>
            <p>{html.escape(subtitle)}</p>
            {pills_markup}
        </section>
        """,
        unsafe_allow_html=True,
    )


def render_empty_state(title: str, body: str) -> None:
    """渲染簡潔空狀態。"""
    st.markdown(
        f"""
        <div class="empty-state">
            <strong>{html.escape(title)}</strong>
            <span>{html.escape(body)}</span>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _resolve_doc_root(manifest: dict) -> Path | None:
    """從 manifest 推回對應的 doc_* 目錄。"""
    explicit_paths = [manifest.get("manifest_path"), manifest.get("markdown_path")]
    for path_str in explicit_paths:
        if not path_str:
            continue
        path = Path(path_str)
        if path.exists():
            return path.parent

    doc_id = manifest.get("doc_id")
    if doc_id:
        candidate = DATA_DIR / doc_id
        if candidate.exists():
            return candidate

    return None


def enrich_doc_manifest(manifest: dict) -> dict:
    """補齊 UI 需要的文件狀態欄位。"""
    enriched = dict(manifest)
    doc_root = _resolve_doc_root(enriched)
    page_count = enriched.get("page_count") or enriched.get("pages") or enriched.get("page_total") or 0
    has_precise_sources = bool(doc_root and (doc_root / "blocks.json").exists())
    has_markdown = bool(doc_root and (doc_root / "content.md").exists()) or bool(
        doc_root and list(doc_root.glob("*_full.md"))
    )

    enriched["doc_root"] = str(doc_root) if doc_root else ""
    enriched["page_count"] = page_count or "?"
    enriched["has_precise_sources"] = has_precise_sources
    enriched["has_markdown"] = has_markdown
    enriched["source_mode_label"] = "精確來源" if has_precise_sources else "全文模式"
    return enriched


def source_page_number(source: dict | None) -> str:
    """從 source 結構取出最合理的頁碼顯示。"""
    if not source:
        return "?"
    stem_source = source.get("stem_source") if isinstance(source, dict) else None
    if isinstance(stem_source, dict) and stem_source.get("page"):
        return str(stem_source["page"])
    if source.get("page"):
        return str(source["page"])
    return "?"


def question_has_precise_source(question: dict) -> bool:
    """判斷題目是否帶有可追溯的精確來源。"""
    source = question.get("source") or {}
    stem_source = source.get("stem_source") or {}
    return bool(source.get("document") and stem_source.get("page") and stem_source.get("original_text"))


def render_selected_docs_summary(selected_docs_info: list[dict]) -> tuple[int, int]:
    """顯示已選教材摘要與 source readiness 狀態。"""
    if not selected_docs_info:
        return 0, 0

    st.markdown("##### 已選教材摘要")
    columns = st.columns(min(3, len(selected_docs_info)))
    precise_ready = 0

    for idx, doc_info in enumerate(selected_docs_info[:3]):
        if doc_info.get("has_precise_sources"):
            precise_ready += 1
        with columns[idx]:
            with st.container(border=True):
                status_class = "status-chip-good" if doc_info.get("has_precise_sources") else "status-chip-warn"
                status_text = "可精確追來源" if doc_info.get("has_precise_sources") else "僅全文模式"
                st.markdown(f'<span class="{status_class}">{status_text}</span>', unsafe_allow_html=True)
                st.markdown(f"**{doc_info.get('title', '未知教材')}**")
                st.caption(f"{doc_info.get('page_count', '?')} 頁 · {doc_info.get('doc_id', '')[:12]}")

    if len(selected_docs_info) > 3:
        st.caption(f"另有 {len(selected_docs_info) - 3} 份教材已選取。")

    missing_precise = len(selected_docs_info) - precise_ready
    return precise_ready, missing_precise


inject_app_styles()


def load_indexed_documents() -> list[dict]:
    """載入已索引的文件列表（掃描 data/doc_* manifest + 全域 manifest.json）"""
    docs: list[dict] = []
    seen_ids: set[str] = set()

    # 1) 掃描 data/ 下的 doc_* 目錄 manifest
    if DATA_DIR.exists():
        for doc_dir in sorted(DATA_DIR.iterdir()):
            if not doc_dir.is_dir() or not doc_dir.name.startswith("doc_"):
                continue
            manifest_files = list(doc_dir.glob("*_manifest.json"))
            if not manifest_files:
                continue
            try:
                with open(manifest_files[0], "r", encoding="utf-8") as f:
                    m = json.load(f)
                doc_id = m.get("doc_id", doc_dir.name)
                if doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    docs.append(enrich_doc_manifest(m))
            except Exception as e:
                logger.warning("doc_manifest_load_error", path=str(manifest_files[0]), error=str(e))

    # 2) 補充全域 manifest.json（向後相容）
    if SOURCES_MANIFEST.exists():
        try:
            with open(SOURCES_MANIFEST, "r", encoding="utf-8") as f:
                global_manifest = json.load(f)
            for src in global_manifest.get("sources", []):
                doc_id = src.get("doc_id", "")
                if doc_id and doc_id not in seen_ids:
                    seen_ids.add(doc_id)
                    docs.append(enrich_doc_manifest(src))
        except Exception as e:
            logger.warning("manifest_load_error", error=str(e))

    return docs


def load_agent_metadata(provider_name: str = "crush") -> dict:
    """根據 provider 載入對應的模型/MCP/context 設定（供 UI 顯示）"""
    meta = {
        "model": None,
        "mcp_servers": {},
        "context_paths": [],
        "available_models": [],
    }

    if provider_name == "opencode" and OPENCODE_CONFIG_PATH.exists():
        try:
            with open(OPENCODE_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            meta["model"] = data.get("model")
            meta["mcp_servers"] = data.get("mcp", {})
            # 收集 opencode.json 中定義的自訂模型
            for prov_cfg in data.get("provider", {}).values():
                for model_key in prov_cfg.get("models", {}):
                    prov_id = list(data.get("provider", {}).keys())[0]
                    meta["available_models"].append(f"{prov_id}/{model_key}")
            # 嘗試從 opencode CLI 取得完整模型清單
            try:
                result = subprocess.run(
                    ["opencode", "models"],
                    capture_output=True,
                    text=True,
                    timeout=10,
                    encoding="utf-8",
                    errors="replace",
                )
                if result.returncode == 0:
                    cli_models = [
                        line.strip()
                        for line in result.stdout.strip().splitlines()
                        if "/" in line.strip() and not line.strip().startswith("Error")
                    ]
                    # 合併去重，CLI 結果為主
                    if cli_models:
                        meta["available_models"] = cli_models
            except Exception:
                pass
        except Exception as e:
            logger.warning("opencode_config_load_error", error=str(e))
    elif CRUSH_CONFIG_PATH.exists():
        try:
            with open(CRUSH_CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            if "agents" in data and "coder" in data["agents"]:
                meta["model"] = data["agents"]["coder"].get("model")
            meta["mcp_servers"] = data.get("mcp", {})
            if "options" in data:
                meta["context_paths"] = data["options"].get("context_paths", [])
        except Exception as e:
            logger.warning("crush_config_load_error", error=str(e))

    return meta


def get_agent_status(provider_name: str, model_override: Optional[str] = None) -> tuple[bool, str, object]:
    """取得 provider 可用狀態"""
    config = AgentProviderConfig.load(
        project_dir=PROJECT_DIR,
        crush_config_path=CRUSH_CONFIG_PATH,
        provider_override=provider_name,
        model_override=model_override,
    )
    provider = create_agent_provider(config)
    available, reason = provider.is_available()
    return available, reason, provider


def check_asset_aware_ready() -> tuple[bool, str]:
    """檢查 asset-aware MCP 實體是否存在"""
    if not ASSET_AWARE_DIR.exists():
        return False, f"缺少目錄：{ASSET_AWARE_DIR}"

    if not any(ASSET_AWARE_DIR.iterdir()):
        return False, "libs/asset-aware-mcp 為空，無法啟動 ingest_documents"

    return True, "asset-aware 目錄存在"


def save_uploaded_pdf(uploaded_file, title_hint: str) -> Path:
    """儲存上傳 PDF 到 data/sources/uploads"""
    UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    stem = (title_hint.strip() or Path(uploaded_file.name).stem).replace(" ", "_")
    target_path = UPLOADS_DIR / f"{timestamp}_{stem}.pdf"

    with open(target_path, "wb") as f:
        f.write(uploaded_file.getbuffer())

    return target_path


def ingest_pdf_via_agent(provider, pdf_path: Path, title: str, use_marker: bool) -> str:
    """透過 agent 觸發 asset-aware 的 ingest_documents"""
    prompt = f"""請使用 MCP 工具 `ingest_documents` 索引 PDF。

參數：
- file_paths: [\"{pdf_path}\"]
- async_mode: false
- use_marker: {str(use_marker).lower()}
- ocr_enabled: false

需求：
- 若 use_marker=true，請保留 blocks.json 以支援精確頁碼/行號來源。
- 完成後回報是否建立了可正式出題的精確來源能力。

完成後請只輸出結果重點（盡量 JSON 或條列）：
1) success（true/false）
2) doc_id
3) use_marker（true/false）
4) source_ready（true/false）
5) message
"""
    return provider.run(prompt)


def build_question_context_options() -> tuple[list[str], dict[str, dict]]:
    """建立聊天可選題目上下文"""
    mapping: dict[str, dict] = {}
    options = ["不指定題目"]

    generated = st.session_state.get("generated_questions", [])
    for i, q in enumerate(generated, 1):
        label = f"[最近生成 #{i}] {q.get('question_text', '')[:45]}"
        mapping[label] = q
        options.append(label)

    repo_questions = load_questions()[:30]
    for i, q in enumerate(repo_questions, 1):
        qid = q.get("id", "N/A")[:8]
        label = f"[題庫 {qid}] {q.get('question_text', '')[:45]}"
        mapping[label] = q
        options.append(label)

    return options, mapping


def build_discussion_prompt(user_prompt: str, selected_question: dict | None) -> str:
    """將題目上下文包進聊天 prompt"""
    if not selected_question:
        return user_prompt

    context = {
        "question_text": selected_question.get("question_text"),
        "options": selected_question.get("options"),
        "correct_answer": selected_question.get("correct_answer"),
        "explanation": selected_question.get("explanation"),
        "source": selected_question.get("source"),
    }

    return (
        "你正在和使用者討論以下考題，請以這題為主要上下文回答。\n"
        f"題目上下文(JSON): {json.dumps(context, ensure_ascii=False)}\n\n"
        f"使用者問題: {user_prompt}"
    )


def extract_questions_from_response(text: str) -> list[dict]:
    """
    從 AI 混合文字輸出中提取所有 JSON 題目物件。

    AI 回應通常包含敘述文字 + JSON code blocks，需要找出所有
    包含 question_text & options 的 JSON 物件。
    """
    questions: list[dict] = []
    seen_texts: set[str] = set()  # 去重

    # 策略 1：提取 ```json ... ``` 或 ``` ... ``` code blocks
    code_blocks = re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL)

    # 策略 2：找獨立的 JSON 物件（以 { 開頭且包含 question_text）
    # 使用平衡括號匹配
    brace_objects: list[str] = []
    i = 0
    while i < len(text):
        if text[i] == "{":
            depth = 0
            start = i
            for j in range(i, len(text)):
                if text[j] == "{":
                    depth += 1
                elif text[j] == "}":
                    depth -= 1
                    if depth == 0:
                        candidate = text[start : j + 1]
                        if "question_text" in candidate and "options" in candidate:
                            brace_objects.append(candidate)
                        i = j + 1
                        break
            else:
                i += 1
        else:
            i += 1

    # 合併兩種策略的結果
    for raw_json in code_blocks + brace_objects:
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError:
            # 嘗試修復常見問題（trailing comma）
            cleaned = re.sub(r",\s*}", "}", raw_json)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                obj = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        if not isinstance(obj, dict):
            continue
        if not obj.get("question_text") or not obj.get("options"):
            continue

        # 去重（同一題可能在 code block 和 brace 都被找到）
        fingerprint = obj["question_text"][:80]
        if fingerprint in seen_texts:
            continue
        seen_texts.add(fingerprint)

        questions.append(normalize_ai_question(obj))

    return questions


def normalize_ai_question(raw: dict) -> dict:
    """
    將 AI 輸出的 JSON 格式正規化為我們的 Question schema。

    AI 可能輸出：
      source_doc, source_chapter, stem_source, ...
    我們需要：
      source: { document, chapter, stem_source: {...}, ... }
    """
    q: dict = {
        "id": raw.get("id", str(uuid.uuid4())),
        "question_text": raw.get("question_text", ""),
        "options": raw.get("options", []),
        "correct_answer": raw.get("correct_answer", ""),
        "explanation": raw.get("explanation", ""),
        "difficulty": raw.get("difficulty", "medium"),
        "topics": raw.get("topics", []),
    }

    # 清理選項（移除 "A. " 前綴，因為 UI 會自動加）
    cleaned_options = []
    for opt in q["options"]:
        cleaned = re.sub(r"^[A-Da-d][.、:：]\s*", "", str(opt))
        cleaned_options.append(cleaned)
    q["options"] = cleaned_options

    # 組裝 source
    source: dict = {}
    if raw.get("source_doc"):
        source["document"] = raw["source_doc"]
    elif raw.get("source") and isinstance(raw["source"], dict):
        source = raw["source"]
    if raw.get("source_chapter"):
        source["chapter"] = raw["source_chapter"]
    if raw.get("stem_source") and isinstance(raw["stem_source"], dict):
        source["stem_source"] = raw["stem_source"]
    if raw.get("answer_source") and isinstance(raw["answer_source"], dict):
        source["answer_source"] = raw["answer_source"]

    if source:
        q["source"] = source

    return q


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
        r"\*\*題目[：:]\*\*\s*(.+?)(?=\*\*選項|\*\*Options|[A-D][.、]|$)",
        r"題目[：:]\s*(.+?)(?=選項|[A-D][.、]|$)",
    ]

    for pattern in q_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["question_text"] = match.group(1).strip()
            break

    # 解析選項
    options = []
    opt_pattern = r"([A-D])[.、:：]\s*(.+?)(?=[A-D][.、:：]|\*\*答案|\*\*正確|答案[：:]|$)"
    for match in re.finditer(opt_pattern, text, re.DOTALL):
        opt_text = match.group(2).strip()
        if opt_text and len(opt_text) > 1:
            options.append(opt_text)
    if options:
        question["options"] = options

    # 解析答案
    ans_patterns = [
        r"\*\*(?:答案|正確答案)[：:]\*\*\s*([A-D])",
        r"(?:答案|正確答案)[：:]\s*([A-D])",
    ]

    for pattern in ans_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            question["correct_answer"] = match.group(1).upper()
            break

    # 解析難度
    diff_match = re.search(r"難度[：:]\s*(easy|medium|hard|簡單|中等|困難)", text, re.IGNORECASE)
    if diff_match:
        diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
        question["difficulty"] = diff_map.get(diff_match.group(1), diff_match.group(1).lower())

    # 解析詳解
    exp_patterns = [
        r"\*\*(?:解析|詳解)[：:]\*\*\s*(.+?)(?=\*\*|題目 ID|$)",
        r"(?:解析|詳解)[：:]\s*(.+?)(?=題目|$)",
    ]

    for pattern in exp_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["explanation"] = match.group(1).strip()
            break

    if question.get("question_text") and question.get("options"):
        return question

    return None


def stream_agent_generate(
    prompt: str,
    provider,
    output_placeholder,
    questions_container,
    progress_placeholder,
) -> tuple[str, list[dict]]:
    """
    真正的流式生成 - 不使用 st.spinner，持續更新 UI

    Returns:
        (full_output, saved_questions)
    """
    logger.info("generation_start", provider=getattr(provider, "name", "unknown"), prompt_len=len(prompt))
    t0 = time.monotonic()

    full_response = ""
    current_question_buffer = ""
    saved_questions = []
    last_update_time = time.time()

    try:
        for line in provider.stream(prompt):
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
                qid = mcp_result.get("question_id")
                logger.info("mcp_result_detected", question_id=qid)

                # 解析題目內容
                parsed_q = parse_question_from_output(current_question_buffer)
                if parsed_q:
                    parsed_q["id"] = qid
                    saved_questions.append(parsed_q)

                    logger.info(
                        "question_saved",
                        index=len(saved_questions),
                        question_id=qid,
                        question_text=parsed_q.get("question_text", "")[:80],
                    )

                    # 即時顯示題目卡片
                    with questions_container:
                        render_question_card_inline(parsed_q, len(saved_questions))

                # 重置緩衝區
                current_question_buffer = ""

        # 最終更新
        output_placeholder.markdown(f"```\n{full_response[-3000:]}\n```")

    except Exception as e:
        logger.exception("generation_error", error=str(e))
        output_placeholder.error(f"生成錯誤: {e}")

    elapsed_ms = int((time.monotonic() - t0) * 1000)
    logger.info(
        "generation_done",
        duration_ms=elapsed_ms,
        total_questions=len(saved_questions),
        total_chars=len(full_response),
    )

    return full_response, saved_questions


def stream_agent_response(prompt: str, provider):
    """聊天用流式回應"""
    for chunk in provider.stream(prompt):
        yield chunk


def run_agent_sync(prompt: str, provider) -> str:
    """聊天用同步回應"""
    return provider.run(prompt)


def render_source_info(source: dict | None, expanded: bool = False):
    """渲染來源資訊（可展開式）"""
    if not source:
        return

    # 檢查是否有任何來源資訊
    has_info = source.get("document") or source.get("stem_source") or source.get("page")
    if not has_info:
        return

    with st.expander("📚 來源資訊", expanded=expanded):
        # 基本資訊
        doc = source.get("document", "未知文件")
        st.markdown(f"**📖 教材:** {doc}")

        if source.get("chapter"):
            chapter_str = str(source.get("chapter") or "")
            if source.get("section"):
                chapter_str += f" - {source.get('section')}"
            st.markdown(f"**📑 章節:** {chapter_str}")

        # 精確來源（新格式）
        if source.get("stem_source"):
            st.markdown("---")
            _render_source_location("📍 題幹來源", source["stem_source"])

        if source.get("answer_source"):
            _render_source_location("📍 答案依據", source["answer_source"])

        if source.get("explanation_sources"):
            for i, src in enumerate(source["explanation_sources"]):
                _render_source_location(f"📍 詳解來源 {i + 1}", src)

        # 向後相容（舊格式）
        elif source.get("page") and not source.get("stem_source"):
            st.markdown("---")
            page_info = f"**P.{source['page']}**"
            if source.get("lines"):
                page_info += f", 第 {source['lines']} 行"
            st.markdown(page_info)

            if source.get("original_text"):
                text = source["original_text"]
                if len(text) > 200:
                    text = text[:200] + "..."
                st.markdown(f"> _{text}_")

        # 驗證狀態
        if source.get("is_verified"):
            st.success("✅ 來源已驗證")


def _render_source_location(label: str, loc: dict):
    """渲染單一來源位置"""
    if not loc:
        return

    page = loc.get("page", 0)
    line_start = loc.get("line_start", 0)
    line_end = loc.get("line_end", 0)
    original_text = loc.get("original_text", "")

    # 位置資訊
    loc_str = f"**{label}:** P.{page}"
    if line_start and line_end:
        loc_str += f", 第 {line_start}-{line_end} 行"
    st.markdown(loc_str)

    # 原文引用
    if original_text:
        text = original_text
        if len(text) > 200:
            text = text[:200] + "..."
        st.markdown(f"> _{text}_")


def render_question_card_inline(question: dict, index: int):
    """在容器內渲染題目卡片（用於流式生成時）"""
    st.markdown("---")
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

    # 顯示來源資訊
    source = question.get("source")
    if source:
        render_source_info(source)

    st.caption(f"🆔 {question.get('id', 'N/A')}")


def render_question_review_form(questions: list[dict]) -> None:
    """
    渲染題目審閱/編輯表單。

    顯示從 AI 回應中提取的題目，讓使用者可以：
    1. 預覽完整題目卡片
    2. 編輯題目文字、選項、答案、難度
    3. 查看來源資訊
    4. 逐題或批次儲存到 SQLite 題庫
    """
    from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

    if not questions:
        return

    st.markdown(f"### 📝 AI 生成結果：共 {len(questions)} 題")
    st.caption("您可以編輯後再儲存到題庫，或直接全部儲存")

    # 全部儲存按鈕
    col_save_all, col_clear = st.columns([1, 1])
    with col_save_all:
        if st.button("💾 全部儲存到題庫", use_container_width=True, type="primary", key="save_all_reviewed"):
            repo = get_question_repository()
            saved_count = 0
            for q in questions:
                try:
                    question_entity = _dict_to_question_entity(q)
                    repo.save(question_entity)
                    saved_count += 1
                except Exception as e:
                    logger.warning("save_question_failed", error=str(e), question_text=q.get("question_text", "")[:50])
            if saved_count > 0:
                st.success(f"✅ 已儲存 {saved_count}/{len(questions)} 題到題庫！")
                logger.info("batch_save_completed", saved=saved_count, total=len(questions))
            else:
                st.error("❌ 儲存失敗，請檢查題目格式")
    with col_clear:
        if st.button("🗑️ 清除結果", use_container_width=True, key="clear_reviewed"):
            st.session_state.generated_questions = []
            st.rerun()

    st.markdown("---")

    # 逐題顯示
    for idx, q in enumerate(questions):
        q_num = idx + 1
        with st.expander(f"第 {q_num} 題：{q.get('question_text', '')[:60]}...", expanded=(idx < 3)):
            # ---- 題目文字（可編輯）----
            edited_text = st.text_area(
                "題目",
                value=q.get("question_text", ""),
                height=100,
                key=f"review_q_text_{idx}",
            )
            q["question_text"] = edited_text

            # ---- 選項（可編輯）----
            options = q.get("options", [])
            for opt_idx in range(4):
                prefix = chr(65 + opt_idx)
                default_val = options[opt_idx] if opt_idx < len(options) else ""
                edited_opt = st.text_input(
                    f"選項 {prefix}",
                    value=default_val,
                    key=f"review_opt_{idx}_{opt_idx}",
                )
                if opt_idx < len(options):
                    options[opt_idx] = edited_opt
                elif edited_opt:
                    options.append(edited_opt)
            q["options"] = options

            # ---- 答案 + 難度 ----
            r_col1, r_col2 = st.columns(2)
            with r_col1:
                answer_opts = ["A", "B", "C", "D"]
                current_ans = q.get("correct_answer", "A").upper()
                ans_idx = answer_opts.index(current_ans) if current_ans in answer_opts else 0
                q["correct_answer"] = st.selectbox(
                    "正確答案",
                    answer_opts,
                    index=ans_idx,
                    key=f"review_ans_{idx}",
                )
            with r_col2:
                diff_opts = ["easy", "medium", "hard"]
                diff_labels = ["🟢 簡單", "🟡 中等", "🔴 困難"]
                current_diff = q.get("difficulty", "medium")
                diff_idx = diff_opts.index(current_diff) if current_diff in diff_opts else 1
                selected_diff = st.selectbox(
                    "難度",
                    diff_labels,
                    index=diff_idx,
                    key=f"review_diff_{idx}",
                )
                q["difficulty"] = diff_opts[diff_labels.index(selected_diff)]

            # ---- 詳解（可編輯）----
            edited_exp = st.text_area(
                "詳解",
                value=q.get("explanation", ""),
                height=80,
                key=f"review_exp_{idx}",
            )
            q["explanation"] = edited_exp

            # ---- 主題標籤 ----
            topics_str = ", ".join(q.get("topics", []))
            edited_topics = st.text_input(
                "主題標籤（逗號分隔）",
                value=topics_str,
                key=f"review_topics_{idx}",
            )
            q["topics"] = [t.strip() for t in edited_topics.split(",") if t.strip()]

            # ---- 來源資訊（唯讀顯示）----
            source = q.get("source")
            if source:
                render_source_info(source, expanded=False)

            # ---- 單題儲存按鈕 ----
            if st.button(f"💾 儲存第 {q_num} 題", key=f"save_single_{idx}"):
                try:
                    repo = get_question_repository()
                    question_entity = _dict_to_question_entity(q)
                    qid = repo.save(question_entity)
                    st.success(f"✅ 已儲存！ID: {qid[:8]}...")
                    logger.info("single_question_saved", question_id=qid)
                except Exception as e:
                    st.error(f"❌ 儲存失敗: {e}")


def _dict_to_question_entity(q: dict):
    """將審閱表單的 dict 轉為 Question entity"""
    from src.domain.entities.question import (
        Difficulty,
        Question,
        QuestionType,
        Source,
        SourceLocation,
    )

    source = None
    src_data = q.get("source")
    if src_data and isinstance(src_data, dict):
        stem_loc = None
        if src_data.get("stem_source"):
            sl = src_data["stem_source"]
            stem_loc = SourceLocation(
                page=sl.get("page", 0),
                line_start=sl.get("line_start", 0),
                line_end=sl.get("line_end", 0),
                original_text=sl.get("original_text", ""),
            )
        answer_loc = None
        if src_data.get("answer_source"):
            al = src_data["answer_source"]
            answer_loc = SourceLocation(
                page=al.get("page", 0),
                line_start=al.get("line_start", 0),
                line_end=al.get("line_end", 0),
                original_text=al.get("original_text", ""),
            )
        source = Source(
            document=src_data.get("document", ""),
            chapter=src_data.get("chapter"),
            section=src_data.get("section"),
            stem_source=stem_loc,
            answer_source=answer_loc,
        )

    return Question(
        id=q.get("id", str(uuid.uuid4())),
        question_text=q.get("question_text", ""),
        options=q.get("options", []),
        correct_answer=q.get("correct_answer", ""),
        explanation=q.get("explanation", ""),
        source=source,
        question_type=QuestionType.SINGLE_CHOICE,
        difficulty=Difficulty(q.get("difficulty", "medium")),
        topics=q.get("topics", []),
    )


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

        # 顯示來源資訊（可展開）
        source = question.get("source")
        if source:
            render_source_info(source)

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


def load_questions(validated_only: bool = False, exam_track: str | None = None) -> list[dict]:
    """載入所有題目 (使用 SQLite Repository)"""
    from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

    repo = get_question_repository()

    kwargs: dict = {"limit": 500, "validated_only": validated_only}
    if exam_track:
        from src.domain.entities.question import ExamTrack

        kwargs["exam_track"] = ExamTrack(exam_track)

    questions = repo.list_all(**kwargs)

    return [q.to_dict() for q in questions]


def load_scope_requests(status: str | None = None) -> list[dict]:
    """載入出題需求 backlog"""
    from src.domain.entities.scope_request import ScopeRequestStatus
    from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

    repo = get_scope_request_repository()
    status_filter = ScopeRequestStatus(status) if status else None
    requests = repo.list_all(status=status_filter, limit=200)
    return [req.to_dict() for req in requests]


def get_heartbeat_summary() -> dict:
    """取得 heartbeat / backlog 摘要"""
    from src.application.services.heartbeat_service import HeartbeatService

    return HeartbeatService().get_status_summary()


# ===== 初始化 session state =====
if "messages" not in st.session_state:
    st.session_state.messages = []

if "agent_provider_name" not in st.session_state:
    st.session_state.agent_provider_name = "opencode"

if "agent_meta" not in st.session_state:
    st.session_state.agent_meta = load_agent_metadata(st.session_state.agent_provider_name)

if "agent_model" not in st.session_state:
    st.session_state.agent_model = st.session_state.agent_meta.get("model") or ""

if (
    "agent_available" not in st.session_state
    or "agent_status_reason" not in st.session_state
    or "agent_provider" not in st.session_state
):
    available, reason, provider = get_agent_status(
        st.session_state.agent_provider_name, st.session_state.agent_model or None
    )
    st.session_state.agent_available = available
    st.session_state.agent_status_reason = reason
    st.session_state.agent_provider = provider

if "current_page" not in st.session_state:
    st.session_state.current_page = PAGE_OPTIONS[0]

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
if "etl_last_result" not in st.session_state:
    st.session_state.etl_last_result = ""
if "last_generation_response" not in st.session_state:
    st.session_state.last_generation_response = ""
if "chat_question_context" not in st.session_state:
    st.session_state.chat_question_context = "不指定題目"


# ===== 側邊欄 (左側導航) =====
with st.sidebar:
    st.title("🩺 考卷生成系統")
    st.caption("教材索引、題目生成、題庫管理與互動練習整合工作台")
    st.markdown("---")

    # 導航
    st.subheader("📌 導航")
    page = st.radio(
        "選擇頁面",
        PAGE_OPTIONS,
        index=PAGE_OPTIONS.index(st.session_state.current_page),
        label_visibility="collapsed",
    )
    st.session_state.current_page = page

    st.markdown("---")

    with st.container(border=True):
        st.subheader("🤖 Agent 控制台")
        provider_name = st.selectbox(
            "🤖 Agent Provider",
            options=["crush", "opencode", "copilot-sdk"],
            index=["crush", "opencode", "copilot-sdk"].index(st.session_state.agent_provider_name),
            help="切換底層 agent provider（UI 只作為包裝層）",
        )

        if provider_name != st.session_state.agent_provider_name:
            st.session_state.agent_provider_name = provider_name
            st.session_state.agent_meta = load_agent_metadata(provider_name)
            st.session_state.agent_model = st.session_state.agent_meta.get("model") or ""
            available, reason, provider = get_agent_status(provider_name, st.session_state.agent_model or None)
            st.session_state.agent_available = available
            st.session_state.agent_status_reason = reason
            st.session_state.agent_provider = provider
            st.rerun()

        if st.session_state.agent_provider_name == "opencode":
            available_models = st.session_state.agent_meta.get("available_models", [])
            if available_models:
                current_model = st.session_state.agent_model or ""
                if current_model and current_model not in available_models:
                    available_models = [current_model] + available_models
                model_index = available_models.index(current_model) if current_model in available_models else 0

                selected_model = st.selectbox(
                    "🧠 模型",
                    options=available_models,
                    index=model_index,
                    help="切換 OpenCode 使用的 LLM 模型",
                )

                if selected_model != st.session_state.agent_model:
                    st.session_state.agent_model = selected_model
                    st.session_state.agent_meta["model"] = selected_model
                    available, reason, provider = get_agent_status(st.session_state.agent_provider_name, selected_model)
                    st.session_state.agent_available = available
                    st.session_state.agent_status_reason = reason
                    st.session_state.agent_provider = provider
                    st.rerun()

        status = "🟢 已連線" if st.session_state.agent_available else "🔴 未連線"
        st.markdown(f"**Agent 狀態:** {status}")
        st.caption(f"Provider: {st.session_state.agent_provider_name}")
        st.caption(f"狀態訊息: {st.session_state.agent_status_reason}")

        if st.session_state.agent_model:
            st.caption(f"模型: {st.session_state.agent_model}")

        if st.session_state.agent_meta.get("mcp_servers"):
            with st.expander("MCP Servers"):
                for name in st.session_state.agent_meta["mcp_servers"].keys():
                    st.caption(f"• {name}")

        mcp_ok, mcp_msg = check_asset_aware_ready()
        st.caption(f"asset-aware: {'✅' if mcp_ok else '⚠️'} {mcp_msg}")

        if st.button("🔄 重新連線", use_container_width=True):
            st.session_state.agent_meta = load_agent_metadata(st.session_state.agent_provider_name)
            available, reason, provider = get_agent_status(
                st.session_state.agent_provider_name, st.session_state.agent_model or None
            )
            st.session_state.agent_available = available
            st.session_state.agent_status_reason = reason
            st.session_state.agent_provider = provider
            st.rerun()

    stats = get_questions_stats()
    with st.container(border=True):
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
        indexed_docs_snapshot = load_indexed_documents()
        precise_doc_count = sum(1 for doc in indexed_docs_snapshot if doc.get("has_precise_sources"))
        render_page_hero(
            "AI 考題生成",
            "把教材索引、來源追蹤、題目草擬與審閱收進同一個工作台，正式出題與 preview 草稿會在頁面上明確分流。",
            [
                f"已索引教材 {len(indexed_docs_snapshot)} 份",
                f"精確來源可用 {precise_doc_count} 份",
                f"Agent：{st.session_state.agent_provider_name}",
            ],
        )

        # 分成上下兩區：配置區 + 預覽區
        config_section, preview_section = st.container(), st.container()
        selected_docs_info: list[dict] = []
        selected_doc_ids: list[str] = []
        selected_section_details: list[dict] = []
        source_doc = ""
        strict_source_tracking = False
        preview_only_mode = False
        missing_precise_docs: list[dict] = []

        with config_section:
            with st.container(border=True):
                st.subheader("📥 PDF ETL 索引")
                st.markdown(
                    '<div class="section-note">正式來源追蹤建議開啟 Marker 模式。它比較慢，但會保留 blocks.json，之後才能做 page / line / bbox 級的題目來源驗證。</div>',
                    unsafe_allow_html=True,
                )

                etl_col1, etl_col2 = st.columns([1.4, 1])
                with etl_col1:
                    uploaded_pdf = st.file_uploader("上傳教材 PDF", type=["pdf"], key="etl_pdf")
                    etl_title = st.text_input("教材標題", placeholder="如：Miller's Anesthesia 9th", key="etl_title")
                with etl_col2:
                    etl_use_marker = st.toggle(
                        "精確來源模式（Marker）",
                        value=True,
                        help="開啟後會以 Marker 解析 PDF，保留 blocks.json，供正式出題時做精確來源追蹤。",
                    )
                    if etl_use_marker:
                        st.caption("適合正式出題與詳解引用，速度較慢。")
                    else:
                        st.caption("適合快速預覽，通常只保留全文 markdown。")

                if st.button("⚙️ 執行 ETL（ingest_documents）", use_container_width=True):
                    if st.session_state.agent_provider_name not in ("crush", "opencode"):
                        st.error("ETL 需要支援 MCP 的 agent（crush 或 opencode）。")
                    elif not st.session_state.agent_available:
                        st.error("Agent 未連線，無法執行 ETL。")
                    elif uploaded_pdf is None:
                        st.error("請先上傳 PDF 檔案。")
                    elif not etl_title.strip():
                        st.error("請輸入教材標題。")
                    else:
                        mcp_ok, mcp_msg = check_asset_aware_ready()
                        if not mcp_ok:
                            st.error(f"asset-aware MCP 不可用：{mcp_msg}")
                        else:
                            with st.spinner("正在上傳並觸發 ingest_documents..."):
                                try:
                                    saved_path = save_uploaded_pdf(uploaded_pdf, etl_title)
                                    result_text = ingest_pdf_via_agent(
                                        st.session_state.agent_provider,
                                        saved_path,
                                        etl_title.strip(),
                                        etl_use_marker,
                                    )
                                    st.session_state.etl_last_result = result_text
                                    st.success("ETL 已觸發，請確認下方結果與已索引教材清單。")
                                    st.code(result_text)
                                except Exception as e:
                                    st.error(f"ETL 失敗：{e}")

            if st.session_state.etl_last_result:
                with st.expander("最近一次 ETL 回傳", expanded=False):
                    st.code(st.session_state.etl_last_result)

            with st.container(border=True):
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

                    prompt_preset = st.selectbox(
                        "Prompt Preset",
                        ["無"] + list(PROMPT_PRESETS.keys()),
                        index=0,
                        help="快速套用出題/詳解風格",
                    )

                st.markdown("---")

                indexed_docs = load_indexed_documents()

                if indexed_docs:
                    doc_label_map: dict[str, dict] = {}
                    doc_labels: list[str] = []
                    for d in indexed_docs:
                        title = d.get("title", d.get("doc_id", "未知"))
                        doc_id = d.get("doc_id", "")
                        pages = d.get("page_count", "?")
                        mode = "精確" if d.get("has_precise_sources") else "全文"
                        label = f"{title} ({pages}p / {mode}) [{doc_id[:12]}]"
                        doc_labels.append(label)
                        doc_label_map[label] = d

                    selected_doc_labels = st.multiselect(
                        "📚 參考教材（已索引，可多選）",
                        options=doc_labels,
                        default=doc_labels[:1] if len(doc_labels) == 1 else [],
                        help="選擇已索引的教材，系統會先檢查是否具備精確來源能力。",
                    )

                    for label in selected_doc_labels:
                        m = doc_label_map[label]
                        selected_docs_info.append(
                            {
                                "doc_id": m.get("doc_id", ""),
                                "title": m.get("title", ""),
                                "sections": m.get("assets", {}).get("sections", []),
                                "toc": m.get("toc", []),
                                "page_count": m.get("page_count", "?"),
                                "has_precise_sources": m.get("has_precise_sources", False),
                            }
                        )

                    all_section_options: list[str] = []
                    section_label_map: dict[str, dict] = {}
                    for doc_info in selected_docs_info:
                        doc_title_short = doc_info["title"][:30]
                        for sec in doc_info["sections"]:
                            indent = "  " * (sec.get("level", 1) - 1)
                            sec_label = f"{indent}{sec['title']} (P.{sec.get('page', '?')})"
                            if len(selected_docs_info) > 1:
                                sec_label = f"[{doc_title_short}] {sec_label}"
                            all_section_options.append(sec_label)
                            section_label_map[sec_label] = {
                                **sec,
                                "doc_id": doc_info["doc_id"],
                                "doc_title": doc_info["title"],
                            }

                    selected_sections: list[str] = []
                    if all_section_options:
                        selected_sections = st.multiselect(
                            "📑 指定章節範圍（可多選，空 = 全文）",
                            options=all_section_options,
                            default=[],
                            help="選擇特定章節讓 AI 聚焦出題，留空則使用全文",
                        )

                    if selected_docs_info:
                        source_doc = ", ".join(d["title"] for d in selected_docs_info)
                        selected_doc_ids = [d["doc_id"] for d in selected_docs_info]
                        selected_section_details = [section_label_map[s] for s in selected_sections]

                        strict_source_tracking = st.toggle(
                            "嚴格來源追蹤（正式題庫模式）",
                            value=True,
                            help="開啟後，若教材缺少 Marker blocks，就不允許正式生成；關閉後可改為 preview 草稿模式。",
                        )

                        precise_ready_count, _missing_precise_count = render_selected_docs_summary(selected_docs_info)
                        missing_precise_docs = [doc for doc in selected_docs_info if not doc.get("has_precise_sources")]
                        preview_only_mode = bool(missing_precise_docs) and not strict_source_tracking

                        if missing_precise_docs:
                            missing_titles = ", ".join(doc["title"] for doc in missing_precise_docs)
                            if strict_source_tracking:
                                st.error(
                                    f"正式模式無法使用目前教材：{missing_titles}。請先用 Marker 重新 ingest，或切換為 preview 草稿模式。"
                                )
                            else:
                                st.warning(
                                    f"目前為 preview 草稿模式：{missing_titles} 缺少精確來源，系統只會生成可審閱草稿，不應直接視為正式入庫題。"
                                )
                        elif precise_ready_count:
                            st.success("已選教材都具備精確來源能力，可走正式來源追蹤流程。")
                else:
                    st.warning("⚠️ 尚無已索引教材。請上傳 PDF 並執行 ETL 索引。")
                    source_doc = st.text_input(
                        "參考教材（可選，無來源追蹤）",
                        placeholder="如：Miller's Anesthesia 第9版",
                        help="手動輸入的教材名稱無法進行精確來源追蹤，只適合 preview 草稿。",
                    )
                    preview_only_mode = True

                additional_instructions = st.text_area(
                    "額外指示（可選）",
                    placeholder="如：請包含臨床案例分析...",
                    height=100,
                )

                generation_blocked = bool(selected_doc_ids and strict_source_tracking and missing_precise_docs)
                submitted = st.button(
                    "🚀 開始生成",
                    key="start_generation",
                    use_container_width=True,
                    type="primary",
                    disabled=generation_blocked,
                )

        # 預覽區
        with preview_section:
            if submitted:
                if not st.session_state.agent_available:
                    st.error("❌ Agent 未連線，無法生成")
                elif selected_doc_ids and strict_source_tracking and missing_precise_docs:
                    missing_titles = ", ".join(doc["title"] for doc in missing_precise_docs)
                    st.error(f"❌ 目前選到的教材仍缺少精確來源：{missing_titles}")
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
                        if selected_doc_ids:
                            prompt += f"- 文件 ID: {', '.join(selected_doc_ids)}\n"
                    prompt += f"- 生成模式: {'preview 草稿' if preview_only_mode else '正式來源追蹤'}\n"
                    if selected_section_details:
                        sec_names = [s["title"] for s in selected_section_details]
                        prompt += f"- 指定章節: {', '.join(sec_names)}\n"
                    if additional_instructions:
                        prompt += f"- 額外要求: {additional_instructions}\n"
                    if prompt_preset != "無":
                        prompt += f"- preset: {prompt_preset} / {PROMPT_PRESETS[prompt_preset]}\n"

                    # 根據是否有已索引教材來選擇不同的生成流程
                    if source_doc and selected_doc_ids:
                        doc_probe_steps = ""
                        doc_query_steps = ""
                        for did in selected_doc_ids:
                            doc_probe_steps += (
                                f'search_source_location(doc_id="{did}", query="[其中一個 target concept]")\n'
                            )
                            doc_query_steps += f'search_source_location(doc_id="{did}", query="[概念關鍵字]")\n'

                        # 組合章節聚焦指引
                        section_focus = ""
                        if selected_section_details:
                            sec_list = "\n".join(
                                f"  - {s['title']} (P.{s.get('page', '?')}, doc: {s['doc_id'][:12]})"
                                for s in selected_section_details
                            )
                            section_focus = f"""
### 📑 聚焦章節
用戶指定了以下章節，請**優先**從這些章節中提取知識點出題：
{sec_list}

使用 `get_section_content` 讀取指定章節內容：
```
get_section_content(doc_id="<doc_id>", section_id="<section_id>")
```
可用的 section_id：
{chr(10).join(f"  - {s['id']} ({s['title']})" for s in selected_section_details)}
"""

                        if preview_only_mode:
                            prompt += f"""
## Preview 草稿模式（不得假裝有精確來源）

已選教材目前**沒有完整精確來源能力**，因此這次只能生成可審閱草稿：

1. 先做 readiness probe：
```
{doc_probe_steps}```
2. 如果 `consult_knowledge_graph` 可用，可輔助閱讀；若失敗，改以全文/章節內容理解教材。
3. **不得編造頁碼、行號、bbox、original_text。**
4. **不得呼叫 `exam_save_question` 或 `exam_bulk_save` 正式入庫。**
5. 請直接輸出 JSON 題目物件，方便使用者在 UI 內預覽與人工審閱。

{section_focus}
每題仍需提供完整 explanation，包含：
- 為何正解正確
- 每個錯誤選項為何錯
- 一句臨床/考試重點
"""
                        else:
                            prompt += f"""
## 🚨 正式來源追蹤流程（必須遵守）

已選教材具備精確來源能力，請走正式流程：

1. `exam_get_generation_guide(question_type=\"mcq\")`
2. `exam_get_pipeline_blueprint(pipeline_type=\"exam-generation\")`
3. `exam_start_pipeline_run(...)`
4. `exam_get_topics()` 避免重複
5. 先做 readiness probe：
```
{doc_probe_steps}```
6. 查知識：`consult_knowledge_graph(query="[知識點關鍵字]")`
7. 取精確來源：
```
{doc_query_steps}```
8. 若任何 probe 顯示缺少 Marker blocks，必須停止並記錄 blocked，不能假裝完成。
9. 只有在取得真實來源後，才能產生題目與 explanation。

{section_focus}
正式儲存 payload 必須包含真實來源：
```json
{{
    "question_text": "...",
    "options": [...],
    "correct_answer": "A",
    "explanation": "逐一說明選項對錯",
    "source_doc": "{source_doc}",
    "source_chapter": "[章節]",
    "stem_source": {{
        "page": [MCP返回的頁碼],
        "line_start": [起始行],
        "line_end": [結束行],
        "original_text": "[MCP返回的原文]"
    }},
    "difficulty": "{diff_en}",
    "topics": {json.dumps(topics if topics else ["麻醉學"], ensure_ascii=False)}
}}
```
"""
                    elif source_doc:
                        # 有手動輸入的教材名稱，但未索引（提醒需要先索引）
                        prompt += f"""
## ⚠️ 注意：教材未索引

你指定了參考教材「{source_doc}」，但此教材**尚未索引**，無法使用 RAG 查詢精確來源。

### 兩種處理方式：

**方式 A：先索引教材（推薦）**
請用戶上傳 PDF 檔案，然後使用 `ingest_documents` 工具索引：
```
ingest_documents(file_path="path/to/pdf", title="{source_doc}")
```
索引完成後，重新開始生成流程。

**方式 B：直接生成（無來源追蹤）**
如果用戶確認要繼續，可以直接生成題目，但：
- ⚠️ 來源資訊將不完整
- ⚠️ 無法進行來源驗證

請詢問用戶選擇哪種方式。"""
                    else:
                        prompt += (
                            """
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
- difficulty: \""""
                            + diff_en
                            + """\"
- topics: """
                            + json.dumps(topics if topics else ["麻醉學"], ensure_ascii=False)
                            + """

請開始生成第 1 題。"""
                        )

                    logger.info("ui_generation_start", num_questions=num_questions)

                    # 建立 UI 元素
                    st.markdown("---")
                    st.subheader("🚀 生成中...")

                    # 進度顯示（在最上方）
                    progress_placeholder = st.empty()
                    progress_placeholder.info("⏳ 正在初始化 AI Agent...")

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
                    provider = st.session_state.agent_provider
                    full_response, saved_questions = stream_agent_generate(
                        prompt=prompt,
                        provider=provider,
                        output_placeholder=output_placeholder,
                        questions_container=questions_container,
                        progress_placeholder=progress_placeholder,
                    )

                    # 更新 session state
                    st.session_state.is_generating = False

                    # === 題目提取流程（三層策略）===
                    # 1. MCP 即時儲存的題目（stream 中已偵測到 question_id）
                    # 2. 從 AI 回應中提取 JSON 題目（新增）
                    # 3. 從 AI 回應中解析 Markdown 題目（舊有後備）
                    all_questions = list(saved_questions)  # MCP 已儲存的
                    mcp_saved_ids = {q.get("id") for q in saved_questions}

                    # 從 AI 完整回應中提取 JSON 格式題目
                    extracted = extract_questions_from_response(full_response)
                    for eq in extracted:
                        # 避免與 MCP 已儲存的重複
                        if eq.get("id") not in mcp_saved_ids:
                            all_questions.append(eq)

                    st.session_state.generated_questions = all_questions
                    st.session_state.last_generation_response = full_response

                    logger.info(
                        "ui_generation_completed",
                        mcp_saved=len(saved_questions),
                        json_extracted=len(extracted),
                        total=len(all_questions),
                    )

                    # 完成訊息
                    if all_questions:
                        progress_placeholder.success(
                            f"✅ 生成完成！共提取 {len(all_questions)} 題"
                            f"（MCP 即存: {len(saved_questions)}, JSON 提取: {len(extracted)}）"
                        )
                    else:
                        progress_placeholder.warning("⚠️ 生成完成，但未偵測到題目。")
                        with st.expander("🔍 除錯資訊"):
                            st.markdown("**可能原因：**")
                            st.markdown("1. AI 沒有以 JSON 格式輸出題目")
                            st.markdown("2. AI 沒有正確呼叫 `exam_save_question` MCP 工具")
                            st.markdown("3. MCP Server 沒有正常啟動")
                            st.markdown("---")
                            st.markdown("**完整輸出：**")
                            st.code(full_response[-5000:], language="text")

            # === 題目審閱表單（生成後或從 session state 讀取）===
            if st.session_state.generated_questions:
                render_question_review_form(st.session_state.generated_questions)

                # 顯示操作按鈕
                st.markdown("---")
                col1, col2, col3 = st.columns(3)
                with col1:
                    if st.button("🔄 再生成一批", use_container_width=True):
                        st.session_state.generated_questions = []
                        st.rerun()
                with col2:
                    if st.button("✍️ 立即練習", use_container_width=True):
                        qs = st.session_state.generated_questions
                        st.session_state.practice_questions = qs.copy()
                        st.session_state.practice_answers = {}
                        st.session_state.practice_submitted = False
                        st.session_state.current_page = "✍️ 作答練習"
                        st.rerun()
                with col3:
                    if st.button("📚 查看題庫", use_container_width=True):
                        st.session_state.current_page = "📚 題庫管理"
                        st.rerun()

                # 原始 AI 輸出（可展開）
                if st.session_state.get("last_generation_response"):
                    with st.expander("🤖 原始 AI 輸出"):
                        st.code(
                            st.session_state.last_generation_response[-5000:],
                            language="text",
                        )
            else:
                render_empty_state(
                    "等待生成結果",
                    "先設定教材與生成模式。若你要正式入庫，請確認教材顯示為可精確追來源。",
                )

    elif page == "✍️ 作答練習":
        # ===== 作答練習頁面 =====
        EXAM_TRACK_OPTIONS = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }

        all_repo_questions = load_questions()
        all_topics = sorted({topic for q in all_repo_questions for topic in q.get("topics", [])})
        render_page_hero(
            "作答練習",
            "從題庫快速抽題、作答、看詳解與來源；適合做短回合複習與錯題檢查。",
            [f"題庫 {len(all_repo_questions)} 題", "支援主題 / 難度 / 審查狀態篩選", "提交後即時計分"],
        )

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
                practice_topics = st.multiselect(
                    "主題篩選",
                    all_topics,
                    default=[],
                    help="可多選；留空表示不限主題。",
                )

            with col2:
                practice_validated_only = st.checkbox(
                    "✅ 只用已審查題目",
                    value=False,
                    help="勾選後只從已通過審查的題目中選題",
                )
                practice_exam_track = st.selectbox(
                    "考試類型",
                    EXAM_TRACK_OPTIONS,
                    format_func=lambda x: EXAM_TRACK_LABELS.get(x, x) or x,
                    index=0,
                    help="依考試類型篩選（ITE / PGY / Clerk 等）",
                )
                practice_random = st.checkbox("隨機順序", value=True)
                st.caption("建議先用主題篩選做小批次訓練，再用隨機順序做混合回顧。")

            if st.button("🎯 開始練習", use_container_width=True, type="primary"):
                # 載入並篩選題目（先用 DB 層篩 validated_only + exam_track）
                et = practice_exam_track if practice_exam_track != "全部" else None
                all_questions = load_questions(validated_only=practice_validated_only, exam_track=et)

                # 難度篩選
                diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
                if practice_difficulty != "全部":
                    diff_filter = diff_map.get(practice_difficulty)
                    all_questions = [q for q in all_questions if q.get("difficulty") == diff_filter]

                if practice_topics:
                    all_questions = [
                        q for q in all_questions if set(practice_topics).intersection(set(q.get("topics", [])))
                    ]

                # 隨機/選取
                if practice_random:
                    random.shuffle(all_questions)

                if not all_questions:
                    st.warning("目前篩選條件沒有可練習題目，請放寬難度或主題條件。")
                else:
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
            top_col1, top_col2, top_col3 = st.columns(3)
            with top_col1:
                st.metric("本回合題數", len(questions))
            with top_col2:
                st.metric("已作答", answered)
            with top_col3:
                remaining = len(questions) - answered
                st.metric("待完成", remaining)

            # 題目列表
            for i, q in enumerate(questions):
                q_id = q.get("id", str(i))

                with st.container(border=True):
                    st.markdown(f"### 第 {i + 1} 題")
                    st.markdown(q.get("question_text", ""))

                    # 選項
                    options = q.get("options", [])
                    option_labels = [
                        f"{chr(65 + j)}. {opt}" if not opt.startswith(chr(65 + j)) else opt
                        for j, opt in enumerate(options)
                    ]

                    # 作答
                    current_answer = st.session_state.practice_answers.get(q_id, "")
                    try:
                        current_index = option_labels.index(current_answer) if current_answer in option_labels else None
                    except ValueError:
                        current_index = None

                    selected = st.radio(
                        f"選擇答案 (題目 {i + 1})",
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
                        if st.button("📖 查看詳解", key=f"exp_{q_id}"):
                            st.session_state.show_explanations[q_id] = not st.session_state.show_explanations.get(
                                q_id, False
                            )

                        if st.session_state.show_explanations.get(q_id, False):
                            st.info(q.get("explanation", "暫無詳解"))

                            # 來源資訊
                            source = q.get("source") or {}
                            if source:
                                render_source_info(source, expanded=False)

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
                        st.session_state.practice_answers = {}
                        st.session_state.practice_submitted = False
                        st.session_state.show_explanations = {}
                        st.rerun()
        else:
            render_empty_state("尚未開始練習", "先選擇題數、難度或主題，再開始一輪作答。")

    elif page == "📚 題庫管理":
        # ===== 題庫管理頁面 =====
        EXAM_TRACK_OPTIONS_BANK = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS_BANK = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }

        questions = load_questions()
        all_topics = sorted({topic for q in questions for topic in q.get("topics", [])})
        render_page_hero(
            "題庫管理",
            "搜尋、篩選與抽查題庫內容，快速找出要複習、要修正或要拿去練習的題目。",
            [f"目前共 {len(questions)} 題", "可依關鍵字 / 難度 / 主題 / 審查狀態篩選", "可直接切換成練習"],
        )

        # 篩選區
        with st.container(border=True):
            filter_col1, filter_col2, filter_col3 = st.columns([1.3, 1, 1.2])
            with filter_col1:
                search_query = st.text_input("搜尋題目 / 詳解", placeholder="輸入關鍵字，例如 remimazolam")
            with filter_col2:
                bank_difficulty = st.selectbox("難度", ["全部", "easy", "medium", "hard"], index=0, key="bank_diff")
            with filter_col3:
                bank_topics = st.multiselect("主題", all_topics, default=[], key="bank_topics")

            filter_col4, filter_col5, filter_col6 = st.columns([1, 1, 1])
            with filter_col4:
                bank_validated_only = st.checkbox("✅ 只看已審查", value=False, key="bank_validated")
            with filter_col5:
                bank_exam_track = st.selectbox(
                    "考試類型",
                    EXAM_TRACK_OPTIONS_BANK,
                    format_func=lambda x: EXAM_TRACK_LABELS_BANK.get(x, x) or x,
                    index=0,
                    key="bank_exam_track",
                )
            with filter_col6:
                if st.button("🔄 刷新題庫", use_container_width=True):
                    st.rerun()

        # 依 DB 篩選
        et_bank = bank_exam_track if bank_exam_track != "全部" else None
        filtered_questions = load_questions(validated_only=bank_validated_only, exam_track=et_bank)
        if search_query:
            query = search_query.strip().lower()
            filtered_questions = [
                q
                for q in filtered_questions
                if query in q.get("question_text", "").lower() or query in q.get("explanation", "").lower()
            ]
        if bank_difficulty != "全部":
            filtered_questions = [q for q in filtered_questions if q.get("difficulty") == bank_difficulty]
        if bank_topics:
            filtered_questions = [
                q for q in filtered_questions if set(bank_topics).intersection(set(q.get("topics", [])))
            ]

        if not questions:
            st.info("📭 題庫空空如也，請先生成考題！")
        else:
            summary_col1, summary_col2 = st.columns([1, 1])
            with summary_col1:
                st.caption(f"顯示 {len(filtered_questions)} / {len(questions)} 題")
            with summary_col2:
                if filtered_questions and st.button("✍️ 用目前篩選結果練習", use_container_width=True):
                    st.session_state.practice_questions = filtered_questions[:10]
                    st.session_state.practice_answers = {}
                    st.session_state.practice_submitted = False
                    st.session_state.show_explanations = {}
                    st.session_state.current_page = "✍️ 作答練習"
                    st.rerun()

            if not filtered_questions:
                render_empty_state("沒有符合條件的題目", "試著放寬關鍵字、難度或主題篩選。")

            for i, q in enumerate(filtered_questions):
                with st.expander(f"#{i + 1} {q.get('question_text', '無題目')[:50]}..."):
                    # 狀態標籤列
                    badges = []
                    if q.get("is_validated"):
                        badges.append('<span class="status-chip-good">✅ 已審查</span>')
                    else:
                        badges.append('<span class="status-chip-warn">待審查</span>')
                    if question_has_precise_source(q):
                        badges.append('<span class="status-chip-good">含精確來源</span>')
                    else:
                        badges.append('<span class="status-chip-warn">來源待補強</span>')
                    if q.get("exam_track"):
                        badges.append(f'<span class="status-chip-good">{q["exam_track"].upper()}</span>')
                    st.markdown(" ".join(badges), unsafe_allow_html=True)

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

                    review_note = st.text_input(
                        "審查備註（可選）",
                        value=q.get("validation_notes") or "",
                        key=f"review_note_{q.get('id', i)}",
                    )
                    review_col1, review_col2 = st.columns(2)
                    with review_col1:
                        if st.button("✅ 標記通過", key=f"approve_question_{q.get('id', i)}", use_container_width=True):
                            from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

                            repo = get_question_repository()
                            repo.mark_validated(
                                q["id"],
                                passed=True,
                                actor_name="streamlit-admin",
                                notes=review_note or None,
                            )
                            st.rerun()
                    with review_col2:
                        if st.button("❌ 標記退回", key=f"reject_question_{q.get('id', i)}", use_container_width=True):
                            from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

                            repo = get_question_repository()
                            repo.mark_validated(
                                q["id"],
                                passed=False,
                                actor_name="streamlit-admin",
                                notes=review_note or None,
                            )
                            st.rerun()

                    # 來源資訊
                    source = q.get("source") or {}
                    if source:
                        render_source_info(source, expanded=False)

    elif page == "📋 出題需求":
        # ===== 出題需求 / 補題 backlog =====
        from src.application.services.heartbeat_service import HeartbeatService
        from src.domain.entities.scope_request import ScopeRequest, ScopeRequestStatus
        from src.infrastructure.persistence.sqlite_scope_request_repo import get_scope_request_repository

        EXAM_TRACK_OPTIONS_SCOPE = ["全部", "ite", "pgy", "clerk", "specialist", "board", "custom"]
        EXAM_TRACK_LABELS_SCOPE = {
            "全部": "全部",
            "ite": "ITE",
            "pgy": "PGY",
            "clerk": "Clerk",
            "specialist": "專科",
            "board": "國考/甄審",
            "custom": "自訂",
        }
        SCOPE_STATUS_OPTIONS = ["全部", "pending", "approved", "in_progress", "fulfilled", "rejected"]
        SCOPE_STATUS_LABELS = {
            "全部": "全部",
            "pending": "待處理",
            "approved": "已核准",
            "in_progress": "補題中",
            "fulfilled": "已完成",
            "rejected": "已駁回",
        }

        scope_repo = get_scope_request_repository()
        heartbeat = HeartbeatService()
        heartbeat_summary = heartbeat.get_status_summary()
        scope_stats = heartbeat_summary["scope_requests"]

        render_page_hero(
            "出題需求與補題 Backlog",
            "使用者可提交缺題需求，管理者可核准，heartbeat 會把缺口寫成 job 檔案交給外部 agent 補題。",
            [
                f"需求 {scope_stats.get('total', 0)} 筆",
                f"待處理 job {heartbeat_summary['jobs']['pending']} 筆",
                f"覆蓋缺口 {heartbeat_summary['coverage_gaps']} 項",
            ],
        )

        metric_col1, metric_col2, metric_col3, metric_col4 = st.columns(4)
        with metric_col1:
            st.metric("需求總數", scope_stats.get("total", 0))
        with metric_col2:
            open_requests = (
                scope_stats.get("by_status", {}).get("pending", 0)
                + scope_stats.get("by_status", {}).get("approved", 0)
                + scope_stats.get("by_status", {}).get("in_progress", 0)
            )
            st.metric("待處理需求", open_requests)
        with metric_col3:
            st.metric("待執行 Jobs", heartbeat_summary["jobs"]["pending"])
        with metric_col4:
            st.metric("已補題數", scope_stats.get("total_fulfilled", 0))

        with st.container(border=True):
            st.subheader("📝 提交出題需求")
            with st.form("scope_request_form"):
                form_col1, form_col2 = st.columns(2)
                with form_col1:
                    scope_topic = st.text_input("主題 / 標籤", placeholder="例如：惡性高熱")
                    scope_chapter = st.text_input("章節（可選）", placeholder="例如：Chapter 12")
                    scope_difficulty = st.selectbox("期望難度", ["不限", "easy", "medium", "hard"], index=0)
                with form_col2:
                    scope_exam_track = st.selectbox(
                        "考試類型",
                        EXAM_TRACK_OPTIONS_SCOPE,
                        format_func=lambda x: EXAM_TRACK_LABELS_SCOPE.get(x, x) or x,
                        index=0,
                    )
                    scope_target_count = st.number_input("希望補幾題", min_value=1, max_value=30, value=5)
                    scope_requested_by = st.text_input("提出者", value="user")

                scope_reason = st.text_area(
                    "需求原因",
                    placeholder="例如：最近練習發現這個主題題數太少，想補充臨床情境題。",
                    height=100,
                )

                submit_scope = st.form_submit_button("📨 提交需求", use_container_width=True, type="primary")

            if submit_scope:
                if not scope_topic.strip():
                    st.error("請輸入主題。")
                elif not scope_reason.strip():
                    st.error("請輸入需求原因，方便後台補題。")
                else:
                    request = ScopeRequest(
                        topic=scope_topic.strip(),
                        chapter=scope_chapter.strip() or None,
                        difficulty=None if scope_difficulty == "不限" else scope_difficulty,
                        exam_track=None if scope_exam_track == "全部" else scope_exam_track,
                        reason=scope_reason.strip(),
                        requested_by=scope_requested_by.strip() or "user",
                        target_count=int(scope_target_count),
                    )
                    scope_repo.save(request)
                    st.success("已建立出題需求。")
                    st.rerun()

        with st.container(border=True):
            st.subheader("🫀 Heartbeat Job 產生")
            hb_col1, hb_col2, hb_col3 = st.columns([1, 1, 1.2])
            with hb_col1:
                hb_max_requests = st.number_input(
                    "單次 job 上限",
                    min_value=1,
                    max_value=20,
                    value=5,
                    key="hb_max_requests",
                )
            with hb_col2:
                if st.button("🔍 Dry Run 分析缺口", use_container_width=True):
                    dry_result = heartbeat.run_heartbeat(max_requests=int(hb_max_requests), dry_run=True)
                    st.json(dry_result.to_dict())
            with hb_col3:
                if st.button("📝 產生補題 Jobs", use_container_width=True, type="primary"):
                    write_result = heartbeat.run_heartbeat(max_requests=int(hb_max_requests), dry_run=False)
                    if write_result.jobs_written:
                        st.success(f"已寫入 {write_result.jobs_written} 個 job 檔案。")
                        st.code("\n".join(write_result.job_paths))
                    else:
                        st.info("這次沒有新增 job，可能是目前沒有缺口，或相同主題已經有 pending job。")

        with st.container(border=True):
            st.subheader("📚 需求列表")
            filter_status = st.selectbox(
                "狀態篩選",
                SCOPE_STATUS_OPTIONS,
                format_func=lambda x: SCOPE_STATUS_LABELS.get(x, x) or x,
                index=0,
            )

            requests = load_scope_requests(status=None if filter_status == "全部" else filter_status)
            if not requests:
                render_empty_state("目前沒有需求", "提交第一筆出題需求後，heartbeat 才會有 backlog 可以轉成 job。")
            else:
                for req in requests:
                    progress = req.get("fulfilled_count", 0) / max(req.get("target_count", 1), 1)
                    title = f"{req.get('topic', '未命名')} · {SCOPE_STATUS_LABELS.get(req.get('status', 'pending'), req.get('status', 'pending'))}"
                    with st.expander(title):
                        badge_parts = [
                            f'<span class="status-chip-good">{SCOPE_STATUS_LABELS.get(req.get("status", "pending"), req.get("status", "pending"))}</span>'
                        ]
                        if req.get("exam_track"):
                            badge_parts.append(
                                f'<span class="status-chip-good">{str(req["exam_track"]).upper()}</span>'
                            )
                        if req.get("difficulty"):
                            badge_parts.append(f'<span class="status-chip-warn">{req["difficulty"]}</span>')
                        st.markdown(" ".join(badge_parts), unsafe_allow_html=True)

                        st.markdown(f"**主題:** {req.get('topic', '')}")
                        if req.get("chapter"):
                            st.markdown(f"**章節:** {req.get('chapter', '')}")
                        st.markdown(f"**提出者:** {req.get('requested_by', 'user')}")
                        st.markdown(f"**需求原因:** {req.get('reason', '')}")
                        st.progress(
                            progress, text=f"已完成 {req.get('fulfilled_count', 0)} / {req.get('target_count', 0)} 題"
                        )

                        admin_note = st.text_input(
                            "管理備註",
                            value=req.get("admin_notes") or "",
                            key=f"scope_admin_note_{req.get('id')}",
                        )

                        action_col1, action_col2 = st.columns(2)
                        with action_col1:
                            if st.button("✅ 核准需求", key=f"scope_approve_{req.get('id')}", use_container_width=True):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.APPROVED,
                                    admin_notes=admin_note or None,
                                )
                                st.rerun()
                        with action_col2:
                            if st.button("❌ 駁回需求", key=f"scope_reject_{req.get('id')}", use_container_width=True):
                                scope_repo.update_status(
                                    req["id"],
                                    ScopeRequestStatus.REJECTED,
                                    admin_notes=admin_note or None,
                                )
                                st.rerun()

        pending_jobs = heartbeat.list_jobs(status="pending")
        if pending_jobs:
            with st.container(border=True):
                st.subheader("⏳ Pending Jobs")
                for job in pending_jobs[:10]:
                    st.markdown(f"- {job.get('topic', '')} · 缺 {job.get('deficit', 0)} 題 · {job.get('_path', '')}")

    elif page == "📊 統計":
        # ===== 統計頁面 =====
        render_page_hero(
            "題庫統計",
            "快速掌握題庫規模、難度分布與高頻知識點，幫助決定下一輪該補哪些題型。",
            ["即時讀取 SQLite 題庫", "難度分布", "高頻主題一覽"],
        )

        stats = get_questions_stats()
        heartbeat_summary = get_heartbeat_summary()

        col1, col2, col3 = st.columns(3)

        with col1:
            st.metric("📝 總題數", stats["question_count"])
            st.metric("📄 考卷數", stats["exam_count"])
            st.metric("✅ 已驗證題數", stats["validated"])

        with col2:
            st.subheader("難度分布")
            diff = stats["difficulty"]
            total = sum(diff.values()) or 1

            st.progress(diff["easy"] / total, text=f"簡單: {diff['easy']} 題")
            st.progress(diff["medium"] / total, text=f"中等: {diff['medium']} 題")
            st.progress(diff["hard"] / total, text=f"困難: {diff['hard']} 題")

        with col3:
            st.subheader("補題狀態")
            st.metric(
                "待處理需求",
                (
                    heartbeat_summary["scope_requests"].get("by_status", {}).get("pending", 0)
                    + heartbeat_summary["scope_requests"].get("by_status", {}).get("approved", 0)
                    + heartbeat_summary["scope_requests"].get("by_status", {}).get("in_progress", 0)
                ),
            )
            st.metric("Pending Jobs", heartbeat_summary["jobs"]["pending"])
            st.metric("覆蓋缺口", heartbeat_summary["coverage_gaps"])

        st.markdown("---")

        top_topics = sorted(stats["by_topic"].items(), key=lambda item: item[1], reverse=True)[:8]
        if top_topics:
            st.subheader("🏷️ 高頻主題")
            topic_max = top_topics[0][1] or 1
            for topic_name, topic_count in top_topics:
                st.progress(topic_count / topic_max, text=f"{topic_name}: {topic_count} 題")

            st.markdown("---")

        top_gaps = heartbeat_summary.get("top_gaps", [])
        if top_gaps:
            st.subheader("🫀 優先補題缺口")
            for gap in top_gaps:
                label = gap["topic"]
                if gap.get("difficulty"):
                    label += f" ({gap['difficulty']})"
                st.markdown(f"- {label}: 尚缺 {gap['deficit']} 題")

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
    with st.container(border=True):
        st.subheader("💬 AI 助手")

        context_options, context_mapping = build_question_context_options()
        if st.session_state.chat_question_context not in context_options:
            st.session_state.chat_question_context = "不指定題目"
        st.session_state.chat_question_context = st.selectbox(
            "討論題目上下文",
            context_options,
            index=context_options.index(st.session_state.chat_question_context),
            help="可先指定一題，再和 AI 討論題目與詳解",
        )

        selected_question = context_mapping.get(st.session_state.chat_question_context)
        if selected_question:
            source_state = "精確來源可用" if question_has_precise_source(selected_question) else "來源待補強"
            st.caption(f"目前上下文：{selected_question.get('question_text', '')[:48]} · {source_state}")

        quick_prompt = ""
        if not st.session_state.messages:
            render_empty_state("從右側開始即時討論", "你可以詢問題目詳解、誘答選項設計，或請 AI 幫你檢查目前工作流。")
            qp_col1, qp_col2, qp_col3 = st.columns(3)
            if qp_col1.button("流程建議", use_container_width=True):
                quick_prompt = CHAT_QUICK_PROMPTS[0]
            if qp_col2.button("檢查詳解", use_container_width=True):
                quick_prompt = CHAT_QUICK_PROMPTS[1]
            if qp_col3.button("審閱清單", use_container_width=True):
                quick_prompt = CHAT_QUICK_PROMPTS[2]

        chat_container = st.container(height=520)
        with chat_container:
            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

        if not st.session_state.agent_available:
            st.warning("⚠️ Agent 未連線")

        prompt = st.chat_input("輸入問題...", key="chat_input", disabled=not st.session_state.agent_available)
        if quick_prompt:
            prompt = quick_prompt

    if prompt:
        # 添加用戶訊息
        st.session_state.messages.append({"role": "user", "content": prompt, "timestamp": datetime.now().isoformat()})

        # 生成回應
        effective_prompt = build_discussion_prompt(prompt, selected_question)

        if st.session_state.agent_available:
            with st.spinner("思考中..."):
                try:
                    full_response = ""
                    for chunk in stream_agent_response(effective_prompt, st.session_state.agent_provider):
                        full_response += chunk
                    response = full_response if full_response else "無回應"
                except Exception:
                    response = run_agent_sync(effective_prompt, st.session_state.agent_provider)
        else:
            response = "[錯誤] Agent 未連線"

        # 添加助手訊息
        st.session_state.messages.append(
            {"role": "assistant", "content": response, "timestamp": datetime.now().isoformat()}
        )

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
    st.caption(f"模型: {st.session_state.agent_model or 'N/A'}")
with col3:
    st.caption(
        f"Agent({st.session_state.agent_provider_name}): {'已連線' if st.session_state.agent_available else '未連線'}"
    )
