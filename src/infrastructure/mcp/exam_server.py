"""
Exam MCP Server - 考題生成 MCP 工具

提供考題生成相關的 MCP 工具，供 Crush agent 調用。
使用 SQLite Repository 作為持久層，支援完整 CRUD + 審計追蹤。
"""

import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from json import JSONDecodeError

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import TextContent, Tool

from src.application.services.exam_tool_application_service import ExamToolApplicationService
from src.application.services.past_exam_extraction_service import PastExamExtractionService
from src.domain.entities.past_exam import Concept, PastExam
from src.infrastructure.logging import bootstrap_logging, get_logger, new_run_id
from src.infrastructure.mcp.exam_tool_handlers import build_tool_handler_registry, dispatch_tool
from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

# 結構化日誌
logger = get_logger(__name__)
mcp_logger = get_logger("mcp_trace")
_ALLOWED_PIPELINE_STATUSES = {"active", "completed", "blocked", "failed"}
_ALLOWED_PHASE_STATUSES = {"not_started", "in_progress", "completed", "blocked", "failed"}

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXAMS_DIR = DATA_DIR / "exams"
QUESTIONS_DIR = DATA_DIR / "questions"
PIPELINE_RUNS_DIR = DATA_DIR / "pipeline_runs"
PROMPTS_DIR = PROJECT_ROOT / ".github" / "prompts"

# 取得 Repository
repo = get_question_repository()
past_exam_repo = get_past_exam_repository()


def _safe_args(arguments: dict) -> dict:
    """截斷過長的參數值，避免日誌爆量"""
    safe = {}
    for k, v in arguments.items():
        if isinstance(v, str) and len(v) > 200:
            safe[k] = v[:200] + "..."
        elif isinstance(v, list) and len(v) > 10:
            safe[k] = v[:10]
        else:
            safe[k] = v
    return safe


def _coerce_limit(value, *, default: int = 20, min_value: int = 1, max_value: int = 200) -> int:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return default
        try:
            candidate = int(text)
        except ValueError:
            return default
    else:
        return default

    return max(min_value, min(candidate, max_value))


def _coerce_required_positive_int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        candidate = value
    elif isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            candidate = int(text)
        except ValueError:
            return None
    else:
        return None

    if candidate <= 0:
        return None
    return candidate


def _build_pipeline_blueprint(pipeline_type: str) -> dict:
    """建立多階段 pipeline 藍圖。"""
    if pipeline_type == "past-exam-extraction":
        phases = [
            {
                "key": "ingest_past_exams",
                "title": "考古題匯入",
                "goal": "將掃描 PDF 解析為可定位的原始內容。",
                "required_tools": ["parse_pdf_structure", "ingest_documents"],
                "recommended_prompts": ["extract-past-exam-patterns.prompt.md"],
                "gate_checks": ["至少一份考古題文件成功建立 doc_id"],
            },
            {
                "key": "normalize_questions",
                "title": "題目正規化",
                "goal": "把題目、答案、詳解拆成結構化 question records。",
                "required_tools": ["exam_extract_past_exam_questions"],
                "recommended_prompts": ["batch-import.prompt.md"],
                "gate_checks": ["extracted_question_count > 0"],
            },
            {
                "key": "classify_patterns",
                "title": "題型與概念分類",
                "goal": "萃取題型、知識點、出題套路、難度。",
                "required_tools": ["exam_classify_past_exam_patterns"],
                "recommended_prompts": ["extract-past-exam-patterns.prompt.md"],
                "gate_checks": ["classified_question_count > 0", "concept_count > 0"],
            },
            {
                "key": "build_blueprint",
                "title": "建立考古題藍圖",
                "goal": "彙整高頻概念、年度趨勢、常見題型模板。",
                "required_tools": ["exam_build_past_exam_blueprint"],
                "recommended_prompts": ["extract-past-exam-patterns.prompt.md"],
                "gate_checks": ["blueprint_json 已產出"],
            },
            {
                "key": "publish_reference_pack",
                "title": "發布參考包",
                "goal": "讓 Copilot/Claude 在出題時可直接取用藍圖與樣題。",
                "required_tools": ["exam_run_past_exam_extraction", "exam_record_phase_result"],
                "recommended_prompts": ["generate-mcq.prompt.md"],
                "gate_checks": ["reference_pack 已寫入 pipeline run artifacts"],
            },
        ]
    else:
        phases = [
            {
                "key": "define_blueprint",
                "title": "定義出題藍圖",
                "goal": "決定題數、難度、知識點與參考的考古題樣式。",
                "required_tools": ["exam_get_generation_guide", "exam_get_topics", "exam_get_pipeline_run"],
                "recommended_prompts": ["generate-from-blueprint.prompt.md", "generate-mcq.prompt.md"],
                "gate_checks": ["target_question_count > 0", "target_concepts 非空"],
            },
            {
                "key": "retrieve_evidence",
                "title": "檢索教材證據",
                "goal": "從 asset-aware MCP 取回實際教材原文與來源位置。",
                "required_tools": ["consult_knowledge_graph", "search_source_location"],
                "recommended_prompts": ["generate-mcq.prompt.md"],
                "gate_checks": [
                    "evidence_refs_count > 0 或 allow_source_free=true",
                    "正式入庫前需 source_ready=true（代表可取得精確來源，例如 Marker blocks 可用）",
                ],
            },
            {
                "key": "draft_questions",
                "title": "起草候選題目",
                "goal": "根據藍圖與證據生成候選題目。",
                "required_tools": ["exam_bulk_save"],
                "recommended_prompts": ["generate-mcq.prompt.md"],
                "gate_checks": ["candidate_count > 0", "source_ready=true 或 allow_source_free=true"],
            },
            {
                "key": "validate_candidates",
                "title": "驗證與去重",
                "goal": "檢查格式、來源完整度與是否過度貼近考古題。",
                "required_tools": ["exam_validate_question", "exam_search"],
                "recommended_prompts": ["manage-questions.prompt.md"],
                "gate_checks": ["validated_count > 0"],
            },
            {
                "key": "persist_questions",
                "title": "正式入庫",
                "goal": "把通過驗證的題目寫入題庫並留下審計資訊。",
                "required_tools": ["exam_bulk_save", "exam_get_audit_log"],
                "recommended_prompts": ["manage-questions.prompt.md"],
                "gate_checks": ["saved_count > 0"],
            },
            {
                "key": "review_and_iterate",
                "title": "人工審閱與迭代",
                "goal": "標記需要重寫的題目，形成 closed-loop 改進。",
                "required_tools": ["exam_mark_validated", "exam_update_question"],
                "recommended_prompts": ["add-explanation.prompt.md", "manage-questions.prompt.md"],
                "gate_checks": ["review_status 已更新"],
            },
        ]

    return {
        "pipeline_type": pipeline_type,
        "inspired_by": "med-paper-assistant multi-phase harness",
        "core_patterns": [
            "phase-gated workflow",
            "persistent pipeline session state",
            "prompt-guided orchestration",
            "MCP-to-MCP trust boundary",
            "closed-loop review and audit",
        ],
        "phases": phases,
    }


def _pipeline_run_path(run_id: str) -> Path:
    return PIPELINE_RUNS_DIR / f"{run_id}.json"


def _save_pipeline_run(state: dict) -> None:
    PIPELINE_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    target_path = _pipeline_run_path(state["run_id"])
    temp_path = PIPELINE_RUNS_DIR / f".{target_path.name}.{uuid.uuid4().hex}.tmp"

    try:
        temp_path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        temp_path.replace(target_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def _load_pipeline_run(run_id: str) -> dict | None:
    normalized_run_id = str(run_id).strip()
    if normalized_run_id.endswith(".json"):
        normalized_run_id = normalized_run_id[:-5]
    path = _pipeline_run_path(normalized_run_id)
    if not path.exists():
        return None
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (JSONDecodeError, OSError, UnicodeDecodeError):
        logger.warning("pipeline_run_json_invalid", run_id=run_id, path=str(path))
        return None

    if not isinstance(state, dict):
        logger.warning("pipeline_run_payload_invalid", run_id=run_id, payload_type=type(state).__name__)
        return None
    return state


def _phase_index(phases: list[dict], phase_key: str) -> int:
    for index, phase in enumerate(phases):
        if phase["key"] == phase_key:
            return index
    return -1


def _build_pipeline_run(
    name: str,
    objective: str,
    pipeline_type: str,
    target_question_count: int,
    source_doc_ids: list[str],
    notes: str | None,
) -> dict:
    blueprint = _build_pipeline_blueprint(pipeline_type)
    now = datetime.now().isoformat()
    phases = []
    for order, phase in enumerate(blueprint["phases"], start=1):
        phases.append(
            {
                "order": order,
                "key": phase["key"],
                "title": phase["title"],
                "status": "not_started",
                "summary": "",
                "artifacts": {},
                "metrics": {},
                "updated_at": None,
            }
        )

    return {
        "run_id": f"run_{uuid.uuid4().hex[:10]}",
        "name": name,
        "objective": objective,
        "pipeline_type": pipeline_type,
        "status": "active",
        "target_question_count": target_question_count,
        "source_doc_ids": source_doc_ids,
        "notes": notes,
        "created_at": now,
        "updated_at": now,
        "current_phase": phases[0]["key"] if phases else None,
        "blueprint": blueprint,
        "phases": phases,
    }


def _validate_phase_gate_state(state: dict, phase_key: str) -> dict:
    phases = state.get("phases", [])
    idx = _phase_index(phases, phase_key)
    if idx == -1:
        return {"valid": False, "blockers": [f"Unknown phase: {phase_key}"]}

    blockers = []
    previous_incomplete = [phase["key"] for phase in phases[:idx] if phase["status"] != "completed"]
    if previous_incomplete:
        blockers.append(f"先完成前置階段: {', '.join(previous_incomplete)}")

    metrics_by_phase = {phase["key"]: phase.get("metrics", {}) for phase in phases}
    artifacts_by_phase = {phase["key"]: phase.get("artifacts", {}) for phase in phases}

    if phase_key == "normalize_questions":
        if not state.get("source_doc_ids") and not artifacts_by_phase.get("ingest_past_exams"):
            blockers.append("缺少已匯入的考古題文件或 ingest artifact")
    elif phase_key == "classify_patterns":
        if metrics_by_phase.get("normalize_questions", {}).get("extracted_question_count", 0) <= 0:
            blockers.append("normalize_questions 尚未產出 extracted_question_count")
    elif phase_key == "build_blueprint":
        if metrics_by_phase.get("classify_patterns", {}).get("classified_question_count", 0) <= 0:
            blockers.append("classify_patterns 尚未完成分類")
        if metrics_by_phase.get("classify_patterns", {}).get("concept_count", 0) <= 0:
            blockers.append("classify_patterns 尚未產出 concept_count")
    elif phase_key == "publish_reference_pack":
        if not artifacts_by_phase.get("build_blueprint", {}).get("blueprint_json"):
            blockers.append("缺少 build_blueprint 產出的 blueprint_json")
    elif phase_key == "retrieve_evidence":
        define_artifacts = artifacts_by_phase.get("define_blueprint", {})
        if not define_artifacts.get("target_concepts"):
            blockers.append("define_blueprint 尚未提供 target_concepts")
    elif phase_key == "draft_questions":
        metrics = metrics_by_phase.get("retrieve_evidence", {})
        evidence_artifacts = artifacts_by_phase.get("retrieve_evidence", {})
        allow_source_free = evidence_artifacts.get("allow_source_free")
        if metrics.get("evidence_refs_count", 0) <= 0 and not allow_source_free:
            blockers.append("retrieve_evidence 尚未提供 evidence_refs_count > 0")
        if not allow_source_free and not evidence_artifacts.get("source_ready"):
            blockers.append(
                "retrieve_evidence 尚未標記 source_ready=true（例如文件缺少 Marker blocks 或精確來源尚未驗證）"
            )
    elif phase_key == "validate_candidates":
        if metrics_by_phase.get("draft_questions", {}).get("candidate_count", 0) <= 0:
            blockers.append("draft_questions 尚未產生 candidate_count")
    elif phase_key == "persist_questions":
        if metrics_by_phase.get("validate_candidates", {}).get("validated_count", 0) <= 0:
            blockers.append("validate_candidates 尚未提供 validated_count")
    elif phase_key == "review_and_iterate":
        if metrics_by_phase.get("persist_questions", {}).get("saved_count", 0) <= 0:
            blockers.append("persist_questions 尚未提供 saved_count")

    next_phase = phases[idx + 1]["key"] if idx + 1 < len(phases) else None
    return {"valid": not blockers, "blockers": blockers, "next_phase": next_phase}


def _available_prompt_workflows(prompt_names: list[str]) -> list[dict]:
    """列出 blueprint 引用到的 prompt workflow 是否存在。"""
    workflows = []
    for name in prompt_names:
        path = PROMPTS_DIR / name
        workflows.append(
            {
                "name": name,
                "path": str(path.relative_to(PROJECT_ROOT)),
                "exists": path.exists(),
            }
        )
    return workflows


def _next_incomplete_phase(phases: list[dict]) -> str | None:
    for phase in phases:
        if phase["status"] != "completed":
            return phase["key"]
    return None


def _get_past_exam_service() -> PastExamExtractionService:
    return PastExamExtractionService(DATA_DIR)


def _summarize_past_exam_questions(past_exam: PastExam, limit: int = 5) -> list[dict]:
    return [
        {
            "question_number": question.question_number,
            "question_text": question.question_text,
            "correct_answer": question.correct_answer,
            "pattern": question.pattern.value if hasattr(question.pattern, "value") else question.pattern,
            "concept_names": question.concept_names,
            "difficulty": question.difficulty,
            "source_page": question.source_page,
        }
        for question in past_exam.questions[:limit]
    ]


def _reconstruct_concepts_from_questions(past_exam: PastExam) -> list[Concept]:
    concept_names = []
    for question in past_exam.questions:
        concept_names.extend(question.concept_names)

    unique_names = []
    seen = set()
    for concept_name in concept_names:
        if concept_name in seen:
            continue
        seen.add(concept_name)
        unique_names.append(concept_name)

    return [
        Concept(
            id=f"concept_{concept_name.lower().replace(' ', '_')}",
            name=concept_name,
            category="未分類",
            subcategory="由已分類題目重建",
            keywords=[concept_name],
        )
        for concept_name in unique_names
    ]


def _load_past_exam(args: dict) -> tuple[PastExam | None, str | None]:
    past_exam_id = args.get("past_exam_id")
    doc_id = args.get("doc_id")
    if past_exam_id:
        past_exam = past_exam_repo.get_exam(past_exam_id)
        return past_exam, None if past_exam is not None else f"Past exam not found: {past_exam_id}"
    if doc_id:
        past_exam = past_exam_repo.get_exam_by_doc_id(doc_id)
        return past_exam, None if past_exam is not None else f"Past exam not found for doc_id: {doc_id}"
    return None, "必須提供 past_exam_id 或 doc_id"


def _record_phase_if_requested(
    run_id: str | None,
    phase_key: str,
    summary: str,
    metrics: dict | None = None,
    artifacts: dict | None = None,
    next_action: str | None = None,
) -> None:
    if not run_id:
        return
    record_phase_result(
        {
            "run_id": run_id,
            "phase_key": phase_key,
            "status": "completed",
            "summary": summary,
            "metrics": metrics or {},
            "artifacts": artifacts or {},
            "next_action": next_action,
        }
    )


def _ensure_ingest_phase_for_run(run_id: str | None, doc_id: str, title: str) -> None:
    if not run_id:
        return

    state = _load_pipeline_run(run_id)
    if state is None:
        return

    phase_index = _phase_index(state.get("phases", []), "ingest_past_exams")
    if phase_index == -1:
        return

    phase = state["phases"][phase_index]
    if phase["status"] == "completed":
        return

    _record_phase_if_requested(
        run_id=run_id,
        phase_key="ingest_past_exams",
        summary=f"已確認 {doc_id} 的 asset-aware artifacts 可用。",
        metrics={"doc_count": 1},
        artifacts={"doc_ids": [doc_id], "titles": [title]},
        next_action="進入 normalize_questions",
    )


def _build_question_tool_service() -> ExamToolApplicationService:
    """Create an application adapter using the current module-level dependencies."""
    return ExamToolApplicationService(
        repo=repo,
        project_root=PROJECT_ROOT,
        exams_dir=EXAMS_DIR,
        questions_dir=QUESTIONS_DIR,
    )


def create_exam_mcp_server() -> Server:
    """建立並配置 MCP Server"""

    server = Server("exam-generator")

    # 確保資料目錄存在
    EXAMS_DIR.mkdir(parents=True, exist_ok=True)
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    PIPELINE_RUNS_DIR.mkdir(parents=True, exist_ok=True)

    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出可用的工具"""
        return [
            Tool(
                name="exam_save_question",
                description="儲存生成的考題到題庫。來源資訊必須來自 MCP 查詢結果（consult_knowledge_graph + search_source_location），不可 AI 編造。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_text": {"type": "string", "description": "題目文字"},
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "選項列表 (A, B, C, D...)",
                        },
                        "correct_answer": {"type": "string", "description": "正確答案 (如 'A' 或 'B, D')"},
                        "explanation": {"type": "string", "description": "詳解說明"},
                        "source_doc": {"type": "string", "description": "來源文件名稱（必須來自 MCP 查詢）"},
                        "source_chapter": {"type": "string", "description": "章節編號（如 Ch.15）"},
                        "source_section": {"type": "string", "description": "小節標題"},
                        "stem_source": {
                            "type": "object",
                            "description": "題幹概念來源（必須來自 search_source_location）",
                            "properties": {
                                "page": {"type": "integer", "description": "頁碼 (1-based)"},
                                "line_start": {"type": "integer", "description": "起始行號"},
                                "line_end": {"type": "integer", "description": "結束行號"},
                                "bbox": {
                                    "type": "array",
                                    "items": {"type": "number"},
                                    "description": "位置 [x0, y0, x1, y1]",
                                },
                                "original_text": {"type": "string", "description": "原文引用"},
                            },
                        },
                        "answer_source": {
                            "type": "object",
                            "description": "正確答案依據來源",
                            "properties": {
                                "page": {"type": "integer"},
                                "line_start": {"type": "integer"},
                                "line_end": {"type": "integer"},
                                "bbox": {"type": "array", "items": {"type": "number"}},
                                "original_text": {"type": "string"},
                            },
                        },
                        "explanation_sources": {
                            "type": "array",
                            "description": "詳解參考來源列表",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "page": {"type": "integer"},
                                    "line_start": {"type": "integer"},
                                    "line_end": {"type": "integer"},
                                    "bbox": {"type": "array", "items": {"type": "number"}},
                                    "original_text": {"type": "string"},
                                },
                            },
                        },
                        "source_page": {"type": "integer", "description": "[DEPRECATED] 使用 stem_source.page"},
                        "source_lines": {
                            "type": "string",
                            "description": "[DEPRECATED] 使用 stem_source.line_start/end",
                        },
                        "source_text": {"type": "string", "description": "[DEPRECATED] 使用 stem_source.original_text"},
                        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"], "description": "難度等級"},
                        "topics": {"type": "array", "items": {"type": "string"}, "description": "知識點標籤"},
                        "user_prompt": {"type": "string", "description": "用戶原始請求"},
                        "skill_used": {"type": "string", "description": "使用的 Skill 名稱"},
                        "reasoning": {"type": "string", "description": "AI 推理過程"},
                    },
                    "required": ["question_text", "options", "correct_answer"],
                },
            ),
            Tool(
                name="exam_list_questions",
                description="列出題庫中的考題",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {"type": "string", "description": "篩選特定知識點"},
                        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"], "description": "篩選難度"},
                        "limit": {"type": "integer", "description": "最大返回數量"},
                    },
                },
            ),
            Tool(
                name="exam_create_exam",
                description="建立一份考卷（從題庫選題）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "考卷名稱"},
                        "question_count": {"type": "integer", "description": "題數"},
                        "topics": {"type": "array", "items": {"type": "string"}, "description": "範圍限定"},
                    },
                    "required": ["name", "question_count"],
                },
            ),
            Tool(
                name="exam_get_stats", description="取得題庫統計資訊", inputSchema={"type": "object", "properties": {}}
            ),
            Tool(
                name="exam_get_question",
                description="取得單一題目詳情",
                inputSchema={
                    "type": "object",
                    "properties": {"question_id": {"type": "string", "description": "題目 ID"}},
                    "required": ["question_id"],
                },
            ),
            Tool(
                name="exam_delete_question",
                description="刪除題目",
                inputSchema={
                    "type": "object",
                    "properties": {"question_id": {"type": "string", "description": "題目 ID"}},
                    "required": ["question_id"],
                },
            ),
            Tool(
                name="exam_validate_question",
                description="驗證題目格式是否完整正確",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_text": {"type": "string"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "correct_answer": {"type": "string"},
                        "question_type": {"type": "string", "enum": ["single_choice", "multiple_choice", "true_false"]},
                    },
                    "required": ["question_text", "options", "correct_answer"],
                },
            ),
            Tool(
                name="exam_update_question",
                description="更新已存在的題目（支援部分更新）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"},
                        "question_text": {"type": "string", "description": "新題目文字"},
                        "options": {"type": "array", "items": {"type": "string"}},
                        "correct_answer": {"type": "string"},
                        "explanation": {"type": "string"},
                        "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                        "topics": {"type": "array", "items": {"type": "string"}},
                        "actor_name": {"type": "string", "description": "修改者名稱 (如 skill 名稱)"},
                        "reason": {"type": "string", "description": "修改原因"},
                    },
                    "required": ["question_id"],
                },
            ),
            Tool(
                name="exam_get_audit_log",
                description="取得題目的修改歷史記錄",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"},
                        "limit": {"type": "integer", "description": "最大筆數", "default": 20},
                    },
                    "required": ["question_id"],
                },
            ),
            Tool(
                name="exam_mark_validated",
                description="標記題目驗證結果",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"},
                        "passed": {"type": "boolean", "description": "是否通過驗證"},
                        "notes": {"type": "string", "description": "驗證備註"},
                    },
                    "required": ["question_id", "passed"],
                },
            ),
            Tool(
                name="exam_search",
                description="搜尋題目（全文檢索）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "搜尋關鍵字"},
                        "limit": {"type": "integer", "description": "最大筆數", "default": 20},
                    },
                    "required": ["keyword"],
                },
            ),
            Tool(
                name="exam_restore_question",
                description="還原已刪除的題目",
                inputSchema={
                    "type": "object",
                    "properties": {"question_id": {"type": "string", "description": "題目 ID"}},
                    "required": ["question_id"],
                },
            ),
            Tool(
                name="exam_get_generation_guide",
                description="取得出題指引。任何 Agent 出題前必須先呼叫此工具，取得正確的出題流程、題目 JSON Schema、品質要求。這是防止 Agent 幻覺的關鍵工具。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_type": {
                            "type": "string",
                            "enum": ["mcq", "essay", "true_false"],
                            "description": "題目類型",
                            "default": "mcq",
                        },
                        "with_source_tracking": {
                            "type": "boolean",
                            "description": "是否需要來源追蹤指引",
                            "default": True,
                        },
                    },
                },
            ),
            Tool(
                name="exam_get_topics",
                description="取得題庫中所有知識點及其題數分布，幫助 Agent 決定出題方向，避免重複出題。",
                inputSchema={
                    "type": "object",
                    "properties": {},
                },
            ),
            Tool(
                name="exam_bulk_save",
                description="批次儲存多道考題。減少 Agent 來回次數，一次儲存多題。每題格式同 exam_save_question。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "questions": {
                            "type": "array",
                            "description": "題目列表，每個元素格式同 exam_save_question 的參數",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "question_text": {"type": "string"},
                                    "options": {"type": "array", "items": {"type": "string"}},
                                    "correct_answer": {"type": "string"},
                                    "explanation": {"type": "string"},
                                    "source_doc": {"type": "string"},
                                    "source_chapter": {"type": "string"},
                                    "stem_source": {"type": "object"},
                                    "answer_source": {"type": "object"},
                                    "explanation_sources": {
                                        "type": "array",
                                        "items": {"type": "object"},
                                    },
                                    "difficulty": {"type": "string", "enum": ["easy", "medium", "hard"]},
                                    "topics": {"type": "array", "items": {"type": "string"}},
                                },
                                "required": ["question_text", "options", "correct_answer"],
                            },
                        },
                    },
                    "required": ["questions"],
                },
            ),
            Tool(
                name="exam_get_past_exam",
                description="讀取已抽出的考古題資料，支援以 past_exam_id 或 doc_id 查詢。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "past_exam_id": {"type": "string", "description": "考古題 aggregate ID"},
                        "doc_id": {"type": "string", "description": "asset-aware ingest 後的 doc_id"},
                    },
                },
            ),
            Tool(
                name="exam_extract_past_exam_questions",
                description="從 asset-aware 已攝入的 doc_id 讀取 markdown/manifest，抽出結構化考古題與答案配對。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "asset-aware doc_id"},
                        "exam_name": {"type": "string", "description": "考卷名稱，可覆蓋 manifest title"},
                        "exam_year": {"type": "integer", "description": "考試年度 (西元或民國均可)"},
                        "run_id": {"type": "string", "description": "可選的 pipeline run ID"},
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="exam_classify_past_exam_patterns",
                description="對已抽出的考古題做 concept / pattern / difficulty 分類，並寫回 SQLite。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "past_exam_id": {"type": "string", "description": "考古題 aggregate ID"},
                        "doc_id": {"type": "string", "description": "asset-aware doc_id"},
                        "run_id": {"type": "string", "description": "可選的 pipeline run ID"},
                    },
                },
            ),
            Tool(
                name="exam_build_past_exam_blueprint",
                description="從已分類的考古題彙整 pattern distribution、高頻 concepts、generation rules。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "past_exam_id": {"type": "string", "description": "考古題 aggregate ID"},
                        "doc_id": {"type": "string", "description": "asset-aware doc_id"},
                        "run_id": {"type": "string", "description": "可選的 pipeline run ID"},
                    },
                },
            ),
            Tool(
                name="exam_run_past_exam_extraction",
                description="一口氣執行考古題 normalize -> classify -> blueprint，串起 asset-aware 與 exam-generator。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "doc_id": {"type": "string", "description": "asset-aware doc_id"},
                        "exam_name": {"type": "string", "description": "考卷名稱，可覆蓋 manifest title"},
                        "exam_year": {"type": "integer", "description": "考試年度 (西元或民國均可)"},
                        "run_id": {"type": "string", "description": "可選的 pipeline run ID"},
                    },
                    "required": ["doc_id"],
                },
            ),
            Tool(
                name="exam_get_pipeline_blueprint",
                description="取得 med-paper-assistant 風格的多 phase 出題/考古題萃取藍圖，讓 Agent 有穩定的工作流骨架。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "pipeline_type": {
                            "type": "string",
                            "enum": ["exam-generation", "past-exam-extraction"],
                            "description": "要取得哪種 pipeline 藍圖",
                            "default": "exam-generation",
                        }
                    },
                },
            ),
            Tool(
                name="exam_start_pipeline_run",
                description="建立一個可跨回合恢復的 pipeline run，保存目標、來源文件、phase 狀態，作為 Agent harness 的穩定工作狀態。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {"type": "string", "description": "這次 pipeline 的名稱"},
                        "objective": {"type": "string", "description": "這次要完成的目標"},
                        "pipeline_type": {
                            "type": "string",
                            "enum": ["exam-generation", "past-exam-extraction"],
                            "default": "exam-generation",
                        },
                        "target_question_count": {"type": "integer", "description": "目標題數", "default": 10},
                        "source_doc_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "相關教材或考古題的 doc_id",
                        },
                        "notes": {"type": "string", "description": "補充說明"},
                    },
                    "required": ["name", "objective"],
                },
            ),
            Tool(
                name="exam_get_pipeline_run",
                description="讀取目前 pipeline run 狀態，讓 Agent 可以跨對話恢復 phase 與 artifacts。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "pipeline run ID"},
                    },
                    "required": ["run_id"],
                },
            ),
            Tool(
                name="exam_record_phase_result",
                description="記錄某個 phase 的進度、摘要、metrics 與 artifacts，形成可追蹤的 closed-loop pipeline。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "pipeline run ID"},
                        "phase_key": {"type": "string", "description": "階段 key"},
                        "status": {
                            "type": "string",
                            "enum": ["not_started", "in_progress", "completed", "blocked", "failed"],
                            "description": "階段狀態",
                        },
                        "summary": {"type": "string", "description": "這個 phase 做了什麼"},
                        "artifacts": {"type": "object", "description": "這個 phase 產出的資料或引用"},
                        "metrics": {"type": "object", "description": "這個 phase 的數值指標"},
                        "next_action": {"type": "string", "description": "建議的下一步"},
                    },
                    "required": ["run_id", "phase_key", "status"],
                },
            ),
            Tool(
                name="exam_validate_phase_gate",
                description="驗證某個 phase 是否已滿足前置條件，避免 Agent 跳步。這是多階段 harness 的 gate。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "run_id": {"type": "string", "description": "pipeline run ID"},
                        "phase_key": {"type": "string", "description": "欲驗證的階段 key"},
                    },
                    "required": ["run_id", "phase_key"],
                },
            ),
            Tool(
                name="exam_list_pipeline_runs",
                description="列出已存在的 pipeline runs，讓 Agent 可以恢復中斷的多階段工作流。",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "status": {
                            "type": "string",
                            "enum": ["active", "completed", "blocked", "failed"],
                            "description": "可選的狀態篩選",
                        },
                        "limit": {"type": "integer", "description": "最多返回幾筆", "default": 20},
                    },
                },
            ),
        ]

    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """處理工具調用"""

        t0 = time.monotonic()
        log = mcp_logger.bind(tool=name)
        log.info("mcp_tool_call_start", arguments=_safe_args(arguments) if isinstance(arguments, dict) else arguments)

        try:
            if not isinstance(arguments, dict):
                error = "arguments must be an object"
                log.warning("mcp_tool_call_invalid_arguments", error=error)
                return [TextContent(type="text", text=json.dumps({"error": error}, ensure_ascii=False))]

            registry = build_tool_handler_registry(
                app_service=_build_question_tool_service(),
                legacy_handlers={
                    "exam_get_generation_guide": get_generation_guide,
                    "exam_get_topics": lambda _arguments: get_topics(),
                    "exam_get_past_exam": get_past_exam,
                    "exam_extract_past_exam_questions": extract_past_exam_questions,
                    "exam_classify_past_exam_patterns": classify_past_exam_patterns,
                    "exam_build_past_exam_blueprint": build_past_exam_blueprint,
                    "exam_run_past_exam_extraction": run_past_exam_extraction,
                    "exam_get_pipeline_blueprint": get_pipeline_blueprint,
                    "exam_start_pipeline_run": start_pipeline_run,
                    "exam_get_pipeline_run": get_pipeline_run,
                    "exam_record_phase_result": record_phase_result,
                    "exam_validate_phase_gate": validate_phase_gate,
                    "exam_list_pipeline_runs": list_pipeline_runs,
                },
            )
            result = dispatch_tool(name, arguments, registry)
            if not isinstance(result, dict):
                error = "tool handler did not return a dictionary"
                log.warning("mcp_tool_call_invalid_result", tool=name, result_type=type(result).__name__)
                return [TextContent(type="text", text=json.dumps({"error": error}, ensure_ascii=False))]

            elapsed_ms = int((time.monotonic() - t0) * 1000)
            success = result.get("success", not result.get("error"))
            log.info(
                "mcp_tool_call_done",
                duration_ms=elapsed_ms,
                success=success,
                question_id=result.get("question_id"),
            )

            return [TextContent(type="text", text=json.dumps(result, ensure_ascii=False, indent=2))]
        except Exception as e:
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            log.exception("mcp_tool_call_error", error=str(e), duration_ms=elapsed_ms)
            return [TextContent(type="text", text=json.dumps({"error": str(e)}, ensure_ascii=False))]

    return server


def save_question(args: dict) -> dict:
    """儲存考題到 SQLite（支援完整 Source 結構）"""
    return _build_question_tool_service().save_question(args)


def list_questions(args: dict) -> dict:
    """列出考題 (使用 Repository)"""
    return _build_question_tool_service().list_questions(args)


def create_exam(args: dict) -> dict:
    """建立考卷"""
    return _build_question_tool_service().create_exam(args)


def get_stats() -> dict:
    """取得統計 (使用 Repository)"""
    return _build_question_tool_service().get_stats()


def get_question(args: dict) -> dict:
    """取得單一題目 (使用 Repository)"""
    return _build_question_tool_service().get_question(args)


def delete_question(args: dict) -> dict:
    """刪除題目 (使用 Repository，軟刪除)"""
    return _build_question_tool_service().delete_question(args)


def validate_question(args: dict) -> dict:
    """驗證題目格式"""
    return _build_question_tool_service().validate_question(args)


def update_question(args: dict) -> dict:
    """更新已存在的題目"""
    return _build_question_tool_service().update_question(args)


def get_audit_log(args: dict) -> dict:
    """取得題目的審計日誌"""
    return _build_question_tool_service().get_audit_log(args)


def mark_validated(args: dict) -> dict:
    """標記題目驗證結果"""
    return _build_question_tool_service().mark_validated(args)


def search_questions(args: dict) -> dict:
    """搜尋題目"""
    return _build_question_tool_service().search_questions(args)


def restore_question(args: dict) -> dict:
    """還原已刪除的題目"""
    return _build_question_tool_service().restore_question(args)


def get_generation_guide(args: dict) -> dict:
    """返回出題指引，讓任何 Agent 都知道正確的出題流程"""
    question_type = args.get("question_type", "mcq")
    with_source = args.get("with_source_tracking", True)

    # 取得現有統計作為上下文
    stats = repo.get_statistics()

    guide = {
        "guide_version": "1.0",
        "current_stats": {
            "total_questions": stats["total"],
            "topic_distribution": stats["by_topic"],
            "difficulty_distribution": stats["by_difficulty"],
        },
        "workflow": _build_workflow_guide(question_type, with_source),
        "question_schema": _build_question_schema(question_type),
        "pipeline_harness": {
            "recommended_pipeline_type": "exam-generation",
            "recommended_tools": [
                "exam_get_pipeline_blueprint",
                "exam_start_pipeline_run",
                "exam_validate_phase_gate",
                "exam_record_phase_result",
                "exam_get_pipeline_run",
            ],
            "why": "先建立 pipeline run 再出題，可保存 blueprint、證據、候選題與審閱結果，避免 Agent 跳步或中途失憶。",
        },
        "quality_rules": [
            "先定義 blueprint（題數、概念、難度、參考的考古題樣式），再開始出題",
            "正式入庫的完整題目必須同時具備題幹、正解、逐一反駁錯誤選項的 explanation，以及可追溯來源",
            "每個選項長度應相近，避免最長選項就是答案",
            "題幹必須包含足夠資訊，不依賴選項才能理解問題",
            "錯誤選項(誘答選項)必須合理，不能一眼看出是錯的",
            "避免否定題幹（「下列何者不正確」），除非必要",
            "難度 easy=記憶型, medium=理解/應用型, hard=分析/綜合型",
            "每題必須標記 topics (知識點標籤)",
            "explanation 必須解釋為什麼正確答案對、每個錯誤選項為什麼錯",
        ],
        "anti_hallucination_rules": [
            "❌ 禁止：未查詢知識庫就直接出題",
            "❌ 禁止：編造頁碼或來源資訊",
            "❌ 禁止：使用「根據記憶」作為來源",
            "❌ 禁止：在 search_source_location 無法提供精確來源時，仍聲稱題目可正式入庫",
            "✅ 必須：先用 consult_knowledge_graph 查詢相關知識",
            "✅ 必須：用 search_source_location 取得精確來源",
            "✅ 必須：stem_source.original_text 必須是 MCP 返回的原文",
            "✅ 必須：若文件缺少 Marker blocks，先重新 ingest（use_marker=True）或明確降級為 preview 草稿，不可直接寫入正式題庫",
        ],
    }

    return guide


def _build_workflow_guide(question_type: str, with_source: bool) -> list[dict]:
    """建構出題步驟指引"""
    steps = []

    steps.append(
        {
            "step": 1,
            "action": "exam_get_generation_guide",
            "description": "取得出題指引（你已經在這一步）",
            "done": True,
        }
    )

    steps.append(
        {
            "step": 2,
            "action": "exam_get_pipeline_blueprint",
            "description": "先取得多階段出題 blueprint，確認 phase、gate、需要保存的 artifacts。",
        }
    )

    steps.append(
        {
            "step": 3,
            "action": "exam_start_pipeline_run",
            "description": "建立這次出題 session，讓 Agent 可跨對話恢復目前 phase。",
        }
    )

    steps.append(
        {
            "step": 4,
            "action": "exam_get_topics",
            "description": "查看現有知識點分布，決定出題方向，避免與已有題目重複",
        }
    )

    if with_source:
        steps.append(
            {
                "step": 5,
                "action": "search_source_location (asset-aware MCP) readiness probe",
                "description": "先確認 doc_id 可取得精確來源。若回傳缺少 blocks / 需 use_marker=True，必須先重新 ingest，並將 retrieve_evidence 記錄為 blocked。",
                "mcp_server": "asset-aware",
            }
        )
        steps.append(
            {
                "step": 6,
                "action": "consult_knowledge_graph (asset-aware MCP)",
                "description": "查詢 RAG 知識庫取得相關內容。若 KG 服務失敗，可暫時改用 fetch_document_asset/full_text 輔助閱讀，但只有在 search_source_location 成功時才能正式入庫。",
                "mcp_server": "asset-aware",
            }
        )
        steps.append(
            {
                "step": 7,
                "action": "search_source_location (asset-aware MCP)",
                "description": "精確定位來源。參數: doc_id='...', query='[關鍵概念]'。返回: page, lines, original_text",
                "mcp_server": "asset-aware",
            }
        )
        steps.append(
            {
                "step": 8,
                "action": "根據查詢結果構思題目",
                "description": "根據 step 5-7 的真實內容，構思題幹+選項+詳解。詳解必須說明正解為何正確，並逐一反駁每個錯誤選項。不要憑記憶！",
            }
        )
        steps.append(
            {
                "step": 9,
                "action": "exam_record_phase_result + exam_save_question / exam_bulk_save",
                "description": "先記錄 retrieve_evidence / draft_questions 的 artifacts，再正式入庫。retrieve_evidence 必須包含 source_ready=true；若 source_ready=false，只能輸出 preview 草稿，不可寫入正式題庫。",
            }
        )
    else:
        steps.append(
            {
                "step": 5,
                "action": "構思題目",
                "description": "⚠️ 無來源追蹤模式：題目內容準確性無法驗證",
            }
        )
        steps.append(
            {
                "step": 6,
                "action": "exam_record_phase_result + exam_save_question / exam_bulk_save",
                "description": "記錄 blueprint 與 candidate artifacts，確保後續人工審閱仍有依據。",
            }
        )

    return steps


def _build_question_schema(question_type: str) -> dict:
    """建構題目 JSON Schema 範例"""
    if question_type == "mcq":
        return {
            "description": "選擇題 (MCQ) 格式",
            "example": {
                "question_text": "關於 Propofol 的藥理特性，下列何者正確？",
                "options": [
                    "A. 主要作用於 NMDA 受體",
                    "B. 作用於 GABA-A 受體，增強抑制性神經傳導",
                    "C. 不影響血壓",
                    "D. 主要經腎臟代謝",
                ],
                "correct_answer": "B",
                "explanation": "Propofol 主要作用於 GABA-A 受體... (A) 錯誤因為... (C) 錯誤因為... (D) 錯誤因為...",
                "source_doc": "Miller's Anesthesia 9th Edition",
                "source_chapter": "Ch.15",
                "stem_source": {
                    "page": 342,
                    "line_start": 15,
                    "line_end": 28,
                    "original_text": "Propofol acts primarily at GABA-A receptors...",
                },
                "answer_source": {
                    "page": 342,
                    "line_start": 20,
                    "line_end": 25,
                    "original_text": "enhancing inhibitory neurotransmission...",
                },
                "difficulty": "medium",
                "topics": ["藥理學", "Propofol", "靜脈麻醉劑"],
            },
        }
    elif question_type == "true_false":
        return {
            "description": "是非題格式",
            "example": {
                "question_text": "Succinylcholine 是非去極化肌肉鬆弛劑。",
                "options": ["A. 正確", "B. 錯誤"],
                "correct_answer": "B",
                "explanation": "Succinylcholine 是去極化(depolarizing)肌鬆弛劑，不是非去極化。",
                "difficulty": "easy",
                "topics": ["藥理學", "肌肉鬆弛劑"],
            },
        }
    else:
        return {
            "description": "問答題格式",
            "example": {
                "question_text": "請說明 Malignant Hyperthermia 的病理機轉與緊急處理步驟。",
                "options": [],
                "correct_answer": "參考答案：MH 是由 RYR1 基因突變...",
                "explanation": "詳解：...",
                "difficulty": "hard",
                "topics": ["惡性高熱", "緊急處理"],
            },
        }


def get_topics() -> dict:
    """取得所有知識點分布"""
    stats = repo.get_statistics()
    topic_dist = stats.get("by_topic", {})

    # 排序：題數多的在前
    sorted_topics = sorted(topic_dist.items(), key=lambda x: x[1], reverse=True)

    return {
        "total_questions": stats["total"],
        "total_topics": len(sorted_topics),
        "topics": [{"name": name, "count": count} for name, count in sorted_topics],
        "suggestion": _suggest_topics(sorted_topics, stats["total"]),
    }


def _suggest_topics(sorted_topics: list, total: int) -> str:
    """根據現有分布建議出題方向"""
    if total == 0:
        return "題庫為空，建議從基礎知識點開始出題。"

    if not sorted_topics:
        return "建議新增知識點標籤。"

    top_topics = [t[0] for t in sorted_topics[:3]]
    low_topics = [t[0] for t in sorted_topics if t[1] <= 2]

    parts = []
    if top_topics:
        parts.append(f"題目最多的知識點：{', '.join(top_topics)}")
    if low_topics:
        parts.append(f"題目較少（可加強）：{', '.join(low_topics[:5])}")

    return " | ".join(parts)


def bulk_save(args: dict) -> dict:
    """批次儲存多道考題"""
    return _build_question_tool_service().bulk_save(args)


def get_past_exam(args: dict) -> dict:
    """讀取已抽出的考古題資料。"""
    past_exam, error = _load_past_exam(args)
    if error:
        return {"success": False, "error": error}
    if past_exam is None:
        return {"success": False, "error": "Past exam lookup returned None"}

    return {
        "success": True,
        "past_exam": past_exam.to_dict(),
        "sample_questions": _summarize_past_exam_questions(past_exam),
    }


def extract_past_exam_questions(args: dict) -> dict:
    """從 asset-aware artifacts 抽出結構化考古題。"""
    doc_id = args.get("doc_id", "")
    if not doc_id:
        return {"success": False, "error": "缺少 doc_id"}

    service = _get_past_exam_service()
    document = service.load_asset_document(doc_id)
    run_id = args.get("run_id")
    _ensure_ingest_phase_for_run(run_id, doc_id, document.title)

    extraction = service.extract_questions(
        document,
        exam_name=args.get("exam_name"),
        exam_year=args.get("exam_year", 0),
    )
    existing_exam = past_exam_repo.get_exam_by_doc_id(doc_id)
    imported_at = (
        existing_exam.imported_at
        if existing_exam is not None and isinstance(existing_exam.imported_at, datetime)
        else datetime.now()
    )

    past_exam = PastExam(
        id=existing_exam.id if existing_exam is not None else PastExam().id,
        exam_year=extraction.exam_year,
        exam_name=extraction.exam_name,
        total_questions=len(extraction.questions),
        questions=extraction.questions,
        source_pdf=document.manifest.get("filename", ""),
        source_doc_id=doc_id,
        imported_at=imported_at,
        imported_by=existing_exam.imported_by if existing_exam is not None else "agent",
        is_ocr_done=True,
        is_parsed=True,
        is_classified=existing_exam.is_classified if existing_exam is not None else False,
    )
    past_exam_repo.save_exam(past_exam)
    past_exam_repo.save_questions(past_exam.id, extraction.questions)

    _record_phase_if_requested(
        run_id=run_id,
        phase_key="normalize_questions",
        summary=f"已從 {doc_id} 抽出 {len(extraction.questions)} 題結構化考古題。",
        metrics={
            "extracted_question_count": len(extraction.questions),
            "answer_key_count": len(extraction.answer_map),
        },
        artifacts={
            "past_exam_id": past_exam.id,
            "doc_id": doc_id,
            "sample_questions": _summarize_past_exam_questions(past_exam, limit=3),
        },
        next_action="進入 classify_patterns",
    )

    return {
        "success": True,
        "past_exam_id": past_exam.id,
        "doc_id": doc_id,
        "exam_name": past_exam.exam_name,
        "exam_year": past_exam.exam_year,
        "extracted_question_count": len(extraction.questions),
        "answer_key_count": len(extraction.answer_map),
        "sample_questions": _summarize_past_exam_questions(past_exam, limit=5),
    }


def classify_past_exam_patterns(args: dict) -> dict:
    """對已抽出的考古題做 concept / pattern 分類。"""
    past_exam, error = _load_past_exam(args)
    if error:
        return {"success": False, "error": error}
    if past_exam is None:
        return {"success": False, "error": "Past exam lookup returned None"}
    if not past_exam.questions:
        return {"success": False, "error": "此 past exam 尚未有結構化題目"}

    service = _get_past_exam_service()
    classified_questions, concepts = service.classify_questions(past_exam.questions)
    past_exam.questions = classified_questions
    past_exam.total_questions = len(classified_questions)
    past_exam.is_classified = True
    past_exam_repo.save_exam(past_exam)
    past_exam_repo.save_questions(past_exam.id, classified_questions)
    past_exam_repo.upsert_concepts(concepts)

    blueprint_preview = service.build_blueprint(classified_questions, concepts)
    run_id = args.get("run_id")
    _record_phase_if_requested(
        run_id=run_id,
        phase_key="classify_patterns",
        summary=f"已完成 {len(classified_questions)} 題的 concept/pattern 分類。",
        metrics={
            "classified_question_count": len(classified_questions),
            "concept_count": len(concepts),
        },
        artifacts={
            "past_exam_id": past_exam.id,
            "pattern_distribution": blueprint_preview["pattern_distribution"],
            "high_frequency_concepts": blueprint_preview["high_frequency_concepts"],
        },
        next_action="進入 build_blueprint",
    )

    return {
        "success": True,
        "past_exam_id": past_exam.id,
        "classified_question_count": len(classified_questions),
        "concept_count": len(concepts),
        "pattern_distribution": blueprint_preview["pattern_distribution"],
        "high_frequency_concepts": blueprint_preview["high_frequency_concepts"],
        "sample_questions": _summarize_past_exam_questions(past_exam, limit=5),
    }


def build_past_exam_blueprint(args: dict) -> dict:
    """從已分類的考古題彙整藍圖。"""
    past_exam, error = _load_past_exam(args)
    if error:
        return {"success": False, "error": error}
    if past_exam is None:
        return {"success": False, "error": "Past exam lookup returned None"}
    if not past_exam.questions:
        return {"success": False, "error": "此 past exam 尚未有結構化題目"}

    service = _get_past_exam_service()
    if not any(question.concept_names for question in past_exam.questions):
        classified_questions, concepts = service.classify_questions(past_exam.questions)
        past_exam.questions = classified_questions
        past_exam.total_questions = len(classified_questions)
        past_exam.is_classified = True
        past_exam_repo.save_exam(past_exam)
        past_exam_repo.save_questions(past_exam.id, classified_questions)
        past_exam_repo.upsert_concepts(concepts)
    else:
        concepts = _reconstruct_concepts_from_questions(past_exam)

    blueprint = service.build_blueprint(past_exam.questions, concepts)
    top_concepts = ", ".join(item["name"] for item in blueprint["high_frequency_concepts"][:3]) or "無"
    reference_pack_summary = (
        f"{past_exam.exam_name}: 共 {blueprint['question_count']} 題，"
        f"高頻概念為 {top_concepts}，"
        f"主要題型分布為 {blueprint['pattern_distribution']}"
    )

    run_id = args.get("run_id")
    _record_phase_if_requested(
        run_id=run_id,
        phase_key="build_blueprint",
        summary="已從已分類考古題產出 blueprint_json。",
        metrics={
            "classified_question_count": len(past_exam.questions),
            "concept_count": blueprint["concept_count"],
        },
        artifacts={
            "past_exam_id": past_exam.id,
            "blueprint_json": blueprint,
            "reference_pack_summary": reference_pack_summary,
        },
        next_action="進入 publish_reference_pack",
    )

    return {
        "success": True,
        "past_exam_id": past_exam.id,
        "blueprint_json": blueprint,
        "reference_pack_summary": reference_pack_summary,
    }


def run_past_exam_extraction(args: dict) -> dict:
    """一口氣執行考古題 normalize -> classify -> blueprint。"""
    extracted = extract_past_exam_questions(args)
    if not extracted.get("success"):
        return extracted

    classified = classify_past_exam_patterns(
        {
            "past_exam_id": extracted["past_exam_id"],
            "run_id": args.get("run_id"),
        }
    )
    if not classified.get("success"):
        return classified

    blueprint = build_past_exam_blueprint(
        {
            "past_exam_id": extracted["past_exam_id"],
            "run_id": args.get("run_id"),
        }
    )
    if not blueprint.get("success"):
        return blueprint

    run_id = args.get("run_id")
    _record_phase_if_requested(
        run_id=run_id,
        phase_key="publish_reference_pack",
        summary="已完成 reference pack 發布所需的 normalize/classify/blueprint 流程。",
        metrics={"reference_question_count": extracted["extracted_question_count"]},
        artifacts={
            "past_exam_id": extracted["past_exam_id"],
            "reference_pack_summary": blueprint["reference_pack_summary"],
            "recommended_generation_rules": blueprint["blueprint_json"]["recommended_generation_rules"],
        },
    )

    return {
        "success": True,
        "past_exam_id": extracted["past_exam_id"],
        "doc_id": extracted["doc_id"],
        "exam_name": extracted["exam_name"],
        "exam_year": extracted["exam_year"],
        "extracted_question_count": extracted["extracted_question_count"],
        "concept_count": classified["concept_count"],
        "pattern_distribution": classified["pattern_distribution"],
        "blueprint_json": blueprint["blueprint_json"],
        "reference_pack_summary": blueprint["reference_pack_summary"],
    }


def get_pipeline_blueprint(args: dict) -> dict:
    """取得多階段 pipeline 藍圖。"""
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    pipeline_type = args.get("pipeline_type", "exam-generation")
    if not isinstance(pipeline_type, str):
        return {"success": False, "error": "pipeline_type 必須是字串"}
    blueprint = _build_pipeline_blueprint(pipeline_type)
    prompt_names = []
    for phase in blueprint["phases"]:
        prompt_names.extend(phase.get("recommended_prompts", []))

    return {
        "success": True,
        "blueprint": blueprint,
        "prompt_workflows": _available_prompt_workflows(sorted(set(prompt_names))),
    }


def start_pipeline_run(args: dict) -> dict:
    """建立可恢復的 pipeline run。"""
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    target_question_count = _coerce_required_positive_int(args.get("target_question_count", 10))
    if target_question_count is None or target_question_count <= 0:
        return {"success": False, "error": "target_question_count 必須大於 0"}

    source_doc_ids_raw = args.get("source_doc_ids", [])
    source_doc_ids = [str(doc_id).strip() for doc_id in source_doc_ids_raw if str(doc_id).strip()] if isinstance(source_doc_ids_raw, list) else []
    pipeline_type = args.get("pipeline_type", "exam-generation")
    if not isinstance(pipeline_type, str):
        pipeline_type = "exam-generation"
    notes = args.get("notes")
    notes = str(notes).strip() if notes is not None else None

    state = _build_pipeline_run(
        name=str(args.get("name", "未命名 pipeline")).strip() or "未命名 pipeline",
        objective=str(args.get("objective", "")),
        pipeline_type=pipeline_type.strip(),
        target_question_count=target_question_count,
        source_doc_ids=source_doc_ids,
        notes=notes,
    )
    _save_pipeline_run(state)

    return {
        "success": True,
        "run_id": state["run_id"],
        "status": state["status"],
        "current_phase": state["current_phase"],
        "pipeline_type": state["pipeline_type"],
        "phase_count": len(state["phases"]),
    }


def get_pipeline_run(args: dict) -> dict:
    """讀取 pipeline run 狀態。"""
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    run_id = args.get("run_id", "")
    state = _load_pipeline_run(run_id)
    if not state:
        return {"success": False, "error": f"Pipeline run not found: {run_id}"}

    return {
        "success": True,
        "run": state,
    }


def record_phase_result(args: dict) -> dict:
    """記錄某個 phase 的執行結果。"""
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    run_id = args.get("run_id", "")
    phase_key = args.get("phase_key", "")
    if not isinstance(run_id, str) or not str(run_id).strip():
        return {"success": False, "error": "缺少 run_id"}
    if not isinstance(phase_key, str) or not str(phase_key).strip():
        return {"success": False, "error": "缺少 phase_key"}

    state = _load_pipeline_run(run_id)
    if not state:
        return {"success": False, "error": f"Pipeline run not found: {run_id}"}

    idx = _phase_index(state["phases"], phase_key)
    if idx == -1:
        return {"success": False, "error": f"Unknown phase: {phase_key}"}

    phase = state["phases"][idx]
    now = datetime.now().isoformat()
    status = args.get("status")
    if isinstance(status, str) and status.strip():
        status = status.strip()
        if status not in _ALLOWED_PHASE_STATUSES:
            return {"success": False, "error": f"status 僅接受: {sorted(_ALLOWED_PHASE_STATUSES)}"}
        phase["status"] = status
    else:
        phase["status"] = phase["status"]
    if "summary" in args:
        phase["summary"] = args.get("summary", "")
    if isinstance(args.get("artifacts"), dict):
        phase["artifacts"].update(args["artifacts"])
    if isinstance(args.get("metrics"), dict):
        phase["metrics"].update(args["metrics"])
    phase["updated_at"] = now

    state["updated_at"] = now
    if isinstance(args.get("next_action"), str) and args.get("next_action"):
        state["next_action"] = args["next_action"]

    if phase["status"] == "completed":
        next_phase = state["phases"][idx + 1]["key"] if idx + 1 < len(state["phases"]) else None
        state["current_phase"] = next_phase
        if next_phase is None:
            state["status"] = "completed"
    elif phase["status"] in {"blocked", "failed"}:
        state["status"] = phase["status"]
        state["current_phase"] = phase_key
    else:
        state["status"] = "active"
        state["current_phase"] = phase_key

    _save_pipeline_run(state)

    return {
        "success": True,
        "run_id": run_id,
        "phase_key": phase_key,
        "phase_status": phase["status"],
        "current_phase": state["current_phase"],
        "run_status": state["status"],
    }


def validate_phase_gate(args: dict) -> dict:
    """驗證某個 phase 的 gate 是否通過。"""
    if not isinstance(args, dict):
        return {"success": False, "error": "arguments must be an object"}

    run_id = args.get("run_id", "")
    phase_key = args.get("phase_key", "")
    if not isinstance(run_id, str) or not str(run_id).strip():
        return {"success": False, "error": "缺少 run_id"}
    if not isinstance(phase_key, str) or not str(phase_key).strip():
        return {"success": False, "error": "缺少 phase_key"}
    state = _load_pipeline_run(run_id)
    if not state:
        return {"success": False, "error": f"Pipeline run not found: {run_id}"}

    result = _validate_phase_gate_state(state, phase_key)
    phase_meta = next((phase for phase in state["blueprint"]["phases"] if phase["key"] == phase_key), None)

    return {
        "success": True,
        "run_id": run_id,
        "phase_key": phase_key,
        "valid": result["valid"],
        "blockers": result["blockers"],
        "next_phase": result.get("next_phase"),
        "gate_checks": phase_meta.get("gate_checks", []) if phase_meta else [],
    }


def list_pipeline_runs(args: dict) -> dict:
    """列出已存在的 pipeline runs。"""
    if not isinstance(args, dict):
        args = {}

    status_filter = args.get("status")
    if status_filter is not None and status_filter not in _ALLOWED_PIPELINE_STATUSES:
        return {"success": False, "error": f"status 僅接受: {sorted(_ALLOWED_PIPELINE_STATUSES)}"}

    limit = _coerce_limit(args.get("limit"), default=20, min_value=1, max_value=200)
    runs = []

    for path in sorted(PIPELINE_RUNS_DIR.glob("*.json"), key=lambda item: item.stat().st_mtime, reverse=True):
        state = _load_pipeline_run(path.stem)
        if state is None:
            continue
        if status_filter and state.get("status") != status_filter:
            continue
        runs.append(
            {
                "run_id": state["run_id"],
                "name": state["name"],
                "pipeline_type": state["pipeline_type"],
                "status": state["status"],
                "current_phase": state.get("current_phase"),
                "target_question_count": state.get("target_question_count"),
                "updated_at": state.get("updated_at"),
            }
        )
        if len(runs) >= limit:
            break

    return {
        "success": True,
        "total": len(runs),
        "runs": runs,
    }


async def main():
    """啟動 MCP Server"""
    run_id = new_run_id("mcp")
    bootstrap_logging(__name__, extra_context={"run_id": run_id, "provider": "mcp"})
    logger.info("mcp_server_start", transport="stdio")
    server = create_exam_mcp_server()

    try:
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())
    except Exception as exc:
        logger.exception("mcp_server_failed", error=str(exc))
        raise
    finally:
        logger.info("mcp_server_stop")


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
