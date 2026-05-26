"""Prompt orchestration and streaming helpers for the Streamlit generation page."""

from __future__ import annotations

import json
import re
import time
import uuid
from dataclasses import dataclass
from json import JSONDecodeError
from typing import Any

import streamlit as st

from src.infrastructure.logging import get_logger
from src.presentation.streamlit.generation.fragments import render_question_card_inline

logger = get_logger(__name__)


@dataclass
class GenerationExecutionUi:
    """Grouped placeholders used during streamed generation."""

    status_container: Any
    progress_placeholder: Any
    output_placeholder: Any
    questions_container: Any


def create_generation_execution_ui() -> GenerationExecutionUi:
    """Render the long-running generation status block and return its placeholders."""
    st.markdown("---")
    st.subheader("🚀 生成中...")

    status_container = st.status("⏳ 生成工作流程", expanded=True)
    with status_container:
        progress_placeholder = st.empty()
        progress_placeholder.info("⏳ 正在初始化 AI Agent...")

    output_col, preview_col = st.columns([1, 1])

    with output_col:
        st.markdown("#### 🤖 AI 輸出")
        output_placeholder = st.empty()
        output_placeholder.code("等待 AI 回應...", language="text")

    with preview_col:
        st.markdown("#### 📋 即時題目預覽")
        questions_container = st.container()
        with questions_container:
            st.caption("若串流過程中偵測到題目，會先顯示在這裡...")

    return GenerationExecutionUi(
        status_container=status_container,
        progress_placeholder=progress_placeholder,
        output_placeholder=output_placeholder,
        questions_container=questions_container,
    )


def build_generation_prompt(
    *,
    num_questions: int,
    question_type: str,
    difficulty: str,
    topics: list[str],
    source_doc: str,
    selected_doc_ids: list[str],
    preview_only_mode: bool,
    selected_section_details: list[dict],
    additional_instructions: str,
    prompt_preset: str,
    prompt_presets: dict[str, str],
    prompt_context: str,
    source_mode: str = "使用既有已拆解教材",
    template_context: dict[str, Any] | None = None,
) -> str:
    """Build the full agent prompt for the generation flow."""
    diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
    type_map = {"單選題": "MCQ 選擇題", "多選題": "多選題", "是非題": "是非題"}
    skill_trigger = type_map.get(question_type, "選擇題")
    diff_en = diff_map.get(difficulty, "medium")
    template_topics = list(template_context.get("topics", [])) if template_context else []
    semantic_anchor_topics = topics or template_topics
    semantic_anchor_topics = semantic_anchor_topics or ["麻醉學"]

    prompt = f"""請生成 {num_questions} 道{skill_trigger}。

## 考題配置
- 題型: {question_type}
- 難度: {difficulty} ({diff_en})
- 題數: {num_questions}
- 來源模式: {source_mode}
"""
    if topics:
        prompt += f"- 知識點範圍: {', '.join(topics)}\n"
    if source_doc:
        prompt += f"- 參考教材: {source_doc}\n"
        if selected_doc_ids:
            prompt += f"- 文件 ID: {', '.join(selected_doc_ids)}\n"
    prompt += f"- 生成模式: {'preview 草稿' if preview_only_mode else '正式來源追蹤'}\n"
    if selected_section_details:
        sec_names = [str(section.get("title") or "").strip() for section in selected_section_details]
        sec_names = [name for name in sec_names if name]
        prompt += f"- 指定章節: {', '.join(sec_names)}\n"
    if additional_instructions:
        prompt += f"- 額外要求: {additional_instructions}\n"
    if prompt_preset != "無":
        prompt += f"- preset: {prompt_preset} / {prompt_presets[prompt_preset]}\n"
    if prompt_context:
        prompt += (
            "\n## 教材內容上下文（請直接依據以下 section / chapter / full text 出題）\n"
            + prompt_context
            + "\n"
        )

    prompt += f"""
## 結構化出題要求
- 每題請先在內部拆成三層：題組層、題幹層、選項層。
- 題組層：定義 shared context、anchor topics、anchor concepts、題型任務。
- 題幹層：明確寫出這題真正要考的 topics / concepts，避免題幹太散。
- 選項層：每個選項都要有自己的 topics / concepts / role，不能只靠語氣湊 distractor。
- 正確選項要與題幹核心概念直接對齊；錯誤選項要各自代表不同的常見混淆點。
- 只輸出 JSON 題目物件或 JSON array，供 UI 預覽並自動送入待審草稿。
- **不得呼叫 `exam_save_question`、`exam_bulk_save` 或任何正式入庫工具。**
- 若沒有真實來源，`source_doc` / `source_chapter` / `stem_source` 可留空，但不得編造 page / line / bbox / original_text。
- 每題 explanation 都要完整說明：正解為何正確、每個錯誤選項為何錯、最後補一句臨床或考試重點。
- 若輸出 JSON，請額外附上 `semantic_structure` 欄位，格式如下：
```json
{{
  "question_group": {{
    "pattern": "[題型]",
    "task_focus": "[考察任務]",
    "anchor_topics": {json.dumps(semantic_anchor_topics, ensure_ascii=False)},
    "anchor_concepts": ["核心概念"]
  }},
  "stem_focus": {{
    "tested_topics": ["題幹主題"],
    "tested_concepts": ["題幹概念"]
  }},
  "options_analysis": [
    {{"label": "A", "role": "correct_answer", "topics": ["選項主題"], "concept_names": ["選項概念"]}},
    {{"label": "B", "role": "distractor", "topics": ["選項主題"], "concept_names": ["選項概念"]}}
  ]
}}
```
"""

    if template_context:
        prompt += _build_template_rewrite_section(template_context)
    elif source_doc and selected_doc_ids:
        section_focus = _build_section_focus(selected_section_details)
        doc_probe_steps = "".join(
            f'search_source_location(doc_id="{doc_id}", query="[其中一個 target concept]")\n'
            for doc_id in selected_doc_ids
        )
        doc_query_steps = "".join(
            f'search_source_location(doc_id="{doc_id}", query="[概念關鍵字]")\n'
            for doc_id in selected_doc_ids
        )

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
9. 只有在取得真實來源後，才能輸出題目 JSON 與 explanation；UI 會把結果先送入待審草稿。

{section_focus}
輸出的 JSON payload 必須包含真實來源：
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
    "topics": {json.dumps(semantic_anchor_topics, ensure_ascii=False)}
}}
```
"""
    elif source_mode == "先上傳新教材再出題":
        prompt += f"""
## ⚠️ 尚未選定已索引教材

你選擇了「先上傳新教材再出題」，但目前還沒有在工作台中選到已索引教材。

請停止生成，回報使用者需要先完成 ETL，並在「已索引教材」清單中選擇至少一份教材後再重新執行。"""
    else:
        prompt += """
## ⚠️ 目前缺少可用來源

請停止生成，回報使用者需先選擇「已拆解教材」或「歷史模板」，不要自行假設來源。"""

    return prompt


def _build_section_focus(selected_section_details: list[dict]) -> str:
    if not selected_section_details:
        return ""

    sec_list = "\n".join(
        f"  - {section.get('title', '-') } (P.{section.get('page', '?')}, doc: {(section.get('doc_id') or '')[:12]})"
        for section in selected_section_details
    )
    section_ids = "\n".join(
        f"  - {section.get('id', '-') } ({section.get('title', '-')})"
        for section in selected_section_details
    )
    return f"""
### 📑 聚焦章節
用戶指定了以下章節，請**優先**從這些章節中提取知識點出題：
{sec_list}

使用 `get_section_content` 讀取指定章節內容：
```
get_section_content(doc_id="<doc_id>", section_id="<section_id>")
```
可用的 section_id：
{section_ids}
"""


def _build_template_rewrite_section(template_context: dict[str, Any]) -> str:
    blueprint = template_context.get("blueprint") or {}
    recommended_rules = blueprint.get("recommended_rules") or []
    sample_source_refs = blueprint.get("sample_source_refs") or []
    topic_text = ", ".join(template_context.get("topics", []) or ["麻醉學"])
    source_exam_name = str(template_context.get("source_exam_name", "") or "").strip()
    source_line = f"{template_context.get('source_exam_year', '-')} 年"
    if source_exam_name:
        source_line += f" {source_exam_name}"
    source_line += f" 第 {template_context.get('source_question_number', '-')} 題"

    rules_block = "\n".join(f"- {rule}" for rule in recommended_rules[:4]) or "- 正式入庫前仍需人工 QA。"
    refs_block = "\n".join(f"- {ref}" for ref in sample_source_refs[:4]) or "- 無"

    return f"""
## 歷史題型模板改寫模式

本次請以歷史模板為骨架改寫新題；請保留考察任務與知識重心，但生成全新的題幹、選項與詳解。

- 模板名稱: {template_context.get("label", "-")}
- 來源題: {source_line}
- 題型骨架: {template_context.get("pattern_label", "-")}
- 建議難度: {template_context.get("difficulty", "-")}
- Bloom: {template_context.get("bloom_level", "-")}
- 建議主題: {topic_text}
- 骨架題幹: {template_context.get("stem_scaffold", "-")}
- 參考原題幹: {template_context.get("reference_question_text", "-")}

### 模板改寫規則
{rules_block}
- 不得直接複製原題幹、原選項或原答案文字。
- 每題都要產出完整 explanation 與 `semantic_structure`。
- 若未提供教材證據，`source_doc`、`source_chapter`、`stem_source` 可留空，但不得假造引用。
- 結果只需輸出 JSON；UI 會自動把這批結果送入待審草稿。

### 歷史參考分布
{refs_block}
"""


def extract_questions_from_response(text: str) -> list[dict]:
    """Extract all JSON question objects from a mixed AI response."""
    questions: list[dict] = []
    seen_texts: set[str] = set()

    raw_candidates: list[str] = []
    raw_candidates.extend(re.findall(r"```(?:json)?\s*(\{.+?\})\s*```", text, re.DOTALL))
    raw_candidates.extend(_extract_json_candidates(text))

    for raw_json in raw_candidates:
        try:
            obj = json.loads(raw_json)
        except json.JSONDecodeError:
            cleaned = re.sub(r",\s*}", "}", raw_json)
            cleaned = re.sub(r",\s*]", "]", cleaned)
            try:
                obj = json.loads(cleaned)
            except json.JSONDecodeError:
                continue

        if isinstance(obj, list):
            payloads = obj
        elif isinstance(obj, dict):
            payloads = [obj]
        else:
            continue

        for payload in payloads:
            if not isinstance(payload, dict):
                continue
            if not payload.get("question_text") or not payload.get("options"):
                continue

            fingerprint = str(payload.get("question_text") or "")[:80]
            if fingerprint in seen_texts:
                continue
            seen_texts.add(fingerprint)
            questions.append(normalize_ai_question(payload))

    return questions


def _extract_json_candidates(text: str) -> list[str]:
    decoder = json.JSONDecoder()
    candidates: list[str] = []
    index = 0
    text_len = len(text)

    while index < len(text):
        if text[index] not in "{[":
            index += 1
            continue
        try:
            _, end = decoder.raw_decode(text[index:])
        except JSONDecodeError:
            index += 1
            continue
        start = index
        end = start + end
        if end <= text_len:
            candidates.append(text[start:end])
        index = end

    return candidates


def normalize_question_type(value: object) -> str:
    """Normalize model/provider question type aliases to stable UI schema values."""
    raw = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "mcq": "single_choice",
        "single": "single_choice",
        "single_choice": "single_choice",
        "choice": "single_choice",
        "multiple": "multiple_choice",
        "multi": "multiple_choice",
        "multi_choice": "multiple_choice",
        "multiple_choice": "multiple_choice",
        "true_false": "true_false",
        "tf": "true_false",
        "是非題": "true_false",
        "單選題": "single_choice",
        "多選題": "multiple_choice",
    }
    return aliases.get(raw, raw or "single_choice")


def normalize_answer_labels(value: object) -> str:
    """Normalize answer aliases such as 1/2 or full-width punctuation to A,B labels."""
    if isinstance(value, list):
        parts = [str(item) for item in value]
    else:
        text = str(value or "").strip().upper()
        text = (
            text.replace("，", ",")
            .replace("、", ",")
            .replace("；", ",")
            .replace(";", ",")
            .replace("(", "")
            .replace(")", "")
        )
        parts = re.split(r"[\s,]+", text)

    labels: list[str] = []
    digit_map = {"1": "A", "2": "B", "3": "C", "4": "D", "5": "E"}
    for part in parts:
        token = str(part or "").strip().upper().strip(".:：")
        if not token:
            continue
        token = digit_map.get(token, token)
        if re.fullmatch(r"[A-H]", token) and token not in labels:
            labels.append(token)
    return ",".join(labels)


def normalize_ai_question(raw: dict) -> dict:
    """Normalize a generated JSON question into the Streamlit review schema."""
    normalized_question_type = normalize_question_type(
        raw.get("question_type") or raw.get("type") or raw.get("question_kind")
    )
    question: dict = {
        "id": raw.get("id", str(uuid.uuid4())),
        "question_text": raw.get("question_text", ""),
        "options": raw.get("options", []),
        "correct_answer": normalize_answer_labels(
            raw.get("correct_answer")
            or raw.get("correct_answers")
            or raw.get("answer")
            or ""
        ),
        "question_type": normalized_question_type,
        "type": normalized_question_type,
        "explanation": raw.get("explanation", ""),
        "difficulty": raw.get("difficulty", "medium"),
        "topics": raw.get("topics", []),
    }

    cleaned_options = []
    for option in question["options"]:
        cleaned_options.append(re.sub(r"^[A-Za-z][.、:：]\s*", "", str(option)))
    question["options"] = cleaned_options

    source: dict = {}
    if raw.get("source_doc"):
        source["document"] = raw["source_doc"]
    elif raw.get("source_doc_id"):
        source["document"] = raw["source_doc_id"]
    elif raw.get("source") and isinstance(raw["source"], dict):
        source = raw["source"]
    if raw.get("source_chapter"):
        source["chapter"] = raw["source_chapter"]
    if raw.get("stem_source") and isinstance(raw["stem_source"], dict):
        source["stem_source"] = raw["stem_source"]
    elif raw.get("source_page") or raw.get("source_text"):
        source["stem_source"] = {
            "page": raw.get("source_page"),
            "original_text": raw.get("source_text") or raw.get("original_text") or "",
        }
    if raw.get("answer_source") and isinstance(raw["answer_source"], dict):
        source["answer_source"] = raw["answer_source"]
    if raw.get("explanation_sources") and isinstance(raw["explanation_sources"], list):
        source["explanation_sources"] = raw["explanation_sources"]
    if source:
        question["source"] = source

    for key in ("preview_only", "formal_save_ready", "generation_mode", "evidence_pack"):
        if key in raw:
            question[key] = raw[key]
    if isinstance(raw.get("semantic_structure"), dict):
        question["semantic_structure"] = raw["semantic_structure"]

    return question


def parse_mcp_result(text: str) -> dict | None:
    """Parse a question-save result from streamed MCP output."""
    patterns = [
        r'\{[^{}]*"question_id"\s*:\s*"[^"]+?"[^{}]*\}',
        r'\{[^{}]*"success"\s*:\s*true[^{}]*\}',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, text, re.DOTALL | re.IGNORECASE)
        for match in matches:
            try:
                result = json.loads(match)
            except json.JSONDecodeError:
                continue
            if result.get("question_id"):
                return result

    question_id_match = re.search(r'題目\s*ID[：:]\s*[`"]?([a-f0-9-]{36})[`"]?', text)
    if question_id_match:
        return {"question_id": question_id_match.group(1), "success": True}
    return None


def parse_question_from_output(text: str) -> dict | None:
    """Parse a question-like markdown block from streamed output."""
    question = {}
    question_patterns = [
        r"\*\*題目[：:]\*\*\s*(.+?)(?=\*\*選項|\*\*Options|[A-D][.、]|$)",
        r"題目[：:]\s*(.+?)(?=選項|[A-D][.、]|$)",
    ]
    for pattern in question_patterns:
        match = re.search(pattern, text, re.DOTALL | re.IGNORECASE)
        if match:
            question["question_text"] = match.group(1).strip()
            break

    options = []
    option_pattern = r"([A-D])[.、:：]\s*(.+?)(?=[A-D][.、:：]|\*\*答案|\*\*正確|答案[：:]|$)"
    for match in re.finditer(option_pattern, text, re.DOTALL):
        option_text = match.group(2).strip()
        if option_text and len(option_text) > 1:
            options.append(option_text)
    if options:
        question["options"] = options

    answer_patterns = [
        r"\*\*(?:答案|正確答案)[：:]\*\*\s*([A-D])",
        r"(?:答案|正確答案)[：:]\s*([A-D])",
    ]
    for pattern in answer_patterns:
        match = re.search(pattern, text, re.IGNORECASE)
        if match:
            question["correct_answer"] = match.group(1).upper()
            break

    difficulty_match = re.search(r"難度[：:]\s*(easy|medium|hard|簡單|中等|困難)", text, re.IGNORECASE)
    if difficulty_match:
        diff_map = {"簡單": "easy", "中等": "medium", "困難": "hard"}
        question["difficulty"] = diff_map.get(difficulty_match.group(1), difficulty_match.group(1).lower())

    explanation_patterns = [
        r"\*\*(?:解析|詳解)[：:]\*\*\s*(.+?)(?=\*\*|題目 ID|$)",
        r"(?:解析|詳解)[：:]\s*(.+?)(?=題目|$)",
    ]
    for pattern in explanation_patterns:
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
    execution_ui: GenerationExecutionUi,
    session_key: str | None = None,
) -> tuple[str, list[dict]]:
    """Stream generation output into the grouped UI placeholders."""
    logger.info("generation_start", provider=getattr(provider, "name", "unknown"), prompt_len=len(prompt))
    started_at = time.monotonic()
    full_response = ""
    current_question_buffer = ""
    saved_questions = []
    last_update_time = time.time()

    try:
        for line in provider.stream(prompt, session_key=session_key):
            if not line:
                continue

            full_response += line
            current_question_buffer += line
            current_time = time.time()
            if current_time - last_update_time > 0.1:
                display_text = full_response[-3000:] if len(full_response) > 3000 else full_response
                execution_ui.output_placeholder.markdown(f"```\n{display_text}\n```")
                execution_ui.progress_placeholder.markdown(
                    f"⏳ 已接收 {len(full_response)} 字元，已儲存 {len(saved_questions)} 題"
                )
                last_update_time = current_time

            mcp_result = parse_mcp_result(current_question_buffer)
            if mcp_result and mcp_result.get("question_id"):
                question_id = mcp_result.get("question_id")
                logger.info("mcp_result_detected", question_id=question_id)

                parsed_question = parse_question_from_output(current_question_buffer)
                if parsed_question:
                    parsed_question["id"] = question_id
                    saved_questions.append(parsed_question)
                    logger.info(
                        "question_saved",
                        index=len(saved_questions),
                        question_id=question_id,
                        question_text=parsed_question.get("question_text", "")[:80],
                    )
                    with execution_ui.questions_container:
                        render_question_card_inline(parsed_question, len(saved_questions))
                current_question_buffer = ""

        execution_ui.output_placeholder.markdown(f"```\n{full_response[-3000:]}\n```")
    except Exception as exc:  # noqa: BLE001
        logger.exception("generation_error", error=str(exc))
        execution_ui.output_placeholder.error(f"生成錯誤: {exc}")

    elapsed_ms = int((time.monotonic() - started_at) * 1000)
    logger.info(
        "generation_done",
        duration_ms=elapsed_ms,
        total_questions=len(saved_questions),
        total_chars=len(full_response),
    )
    return full_response, saved_questions
