"""
Exam MCP Server - 考題生成 MCP 工具

提供考題生成相關的 MCP 工具，供 Crush agent 調用。
使用 SQLite Repository 作為持久層，支援完整 CRUD + 審計追蹤。
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

from src.domain.entities.question import Question, Difficulty, QuestionType, Source
from src.domain.value_objects.audit import ActorType
from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXAMS_DIR = DATA_DIR / "exams"
QUESTIONS_DIR = DATA_DIR / "questions"

# 取得 Repository
repo = get_question_repository()


def create_exam_mcp_server() -> Server:
    """建立並配置 MCP Server"""
    
    server = Server("exam-generator")
    
    # 確保資料目錄存在
    EXAMS_DIR.mkdir(parents=True, exist_ok=True)
    QUESTIONS_DIR.mkdir(parents=True, exist_ok=True)
    
    @server.list_tools()
    async def list_tools() -> list[Tool]:
        """列出可用的工具"""
        return [
            Tool(
                name="exam_save_question",
                description="儲存生成的考題到題庫",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_text": {
                            "type": "string",
                            "description": "題目文字"
                        },
                        "options": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "選項列表 (A, B, C, D...)"
                        },
                        "correct_answer": {
                            "type": "string",
                            "description": "正確答案 (如 'A' 或 'B, D')"
                        },
                        "explanation": {
                            "type": "string",
                            "description": "詳解說明"
                        },
                        "source_doc": {
                            "type": "string",
                            "description": "來源文件名稱"
                        },
                        "source_page": {
                            "type": "integer",
                            "description": "來源頁碼"
                        },
                        "difficulty": {
                            "type": "string",
                            "enum": ["easy", "medium", "hard"],
                            "description": "難度等級"
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "知識點標籤"
                        }
                    },
                    "required": ["question_text", "options", "correct_answer"]
                }
            ),
            Tool(
                name="exam_list_questions",
                description="列出題庫中的考題",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "topic": {
                            "type": "string",
                            "description": "篩選特定知識點"
                        },
                        "difficulty": {
                            "type": "string",
                            "enum": ["easy", "medium", "hard"],
                            "description": "篩選難度"
                        },
                        "limit": {
                            "type": "integer",
                            "description": "最大返回數量"
                        }
                    }
                }
            ),
            Tool(
                name="exam_create_exam",
                description="建立一份考卷（從題庫選題）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "考卷名稱"
                        },
                        "question_count": {
                            "type": "integer",
                            "description": "題數"
                        },
                        "topics": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "範圍限定"
                        }
                    },
                    "required": ["name", "question_count"]
                }
            ),
            Tool(
                name="exam_get_stats",
                description="取得題庫統計資訊",
                inputSchema={
                    "type": "object",
                    "properties": {}
                }
            ),
            Tool(
                name="exam_get_question",
                description="取得單一題目詳情",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {
                            "type": "string",
                            "description": "題目 ID"
                        }
                    },
                    "required": ["question_id"]
                }
            ),
            Tool(
                name="exam_delete_question",
                description="刪除題目",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {
                            "type": "string",
                            "description": "題目 ID"
                        }
                    },
                    "required": ["question_id"]
                }
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
                        "question_type": {
                            "type": "string",
                            "enum": ["single_choice", "multiple_choice", "true_false"]
                        }
                    },
                    "required": ["question_text", "options", "correct_answer"]
                }
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
                        "reason": {"type": "string", "description": "修改原因"}
                    },
                    "required": ["question_id"]
                }
            ),
            Tool(
                name="exam_get_audit_log",
                description="取得題目的修改歷史記錄",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"},
                        "limit": {"type": "integer", "description": "最大筆數", "default": 20}
                    },
                    "required": ["question_id"]
                }
            ),
            Tool(
                name="exam_mark_validated",
                description="標記題目驗證結果",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"},
                        "passed": {"type": "boolean", "description": "是否通過驗證"},
                        "notes": {"type": "string", "description": "驗證備註"}
                    },
                    "required": ["question_id", "passed"]
                }
            ),
            Tool(
                name="exam_search",
                description="搜尋題目（全文檢索）",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "keyword": {"type": "string", "description": "搜尋關鍵字"},
                        "limit": {"type": "integer", "description": "最大筆數", "default": 20}
                    },
                    "required": ["keyword"]
                }
            ),
            Tool(
                name="exam_restore_question",
                description="還原已刪除的題目",
                inputSchema={
                    "type": "object",
                    "properties": {
                        "question_id": {"type": "string", "description": "題目 ID"}
                    },
                    "required": ["question_id"]
                }
            ),
        ]
    
    @server.call_tool()
    async def call_tool(name: str, arguments: dict) -> list[TextContent]:
        """處理工具調用"""
        
        logger.info(f"Tool called: {name} with args: {arguments}")
        
        try:
            if name == "exam_save_question":
                result = save_question(arguments)
            elif name == "exam_list_questions":
                result = list_questions(arguments)
            elif name == "exam_create_exam":
                result = create_exam(arguments)
            elif name == "exam_get_stats":
                result = get_stats()
            elif name == "exam_get_question":
                result = get_question(arguments)
            elif name == "exam_delete_question":
                result = delete_question(arguments)
            elif name == "exam_validate_question":
                result = validate_question(arguments)
            elif name == "exam_update_question":
                result = update_question(arguments)
            elif name == "exam_get_audit_log":
                result = get_audit_log(arguments)
            elif name == "exam_mark_validated":
                result = mark_validated(arguments)
            elif name == "exam_search":
                result = search_questions(arguments)
            elif name == "exam_restore_question":
                result = restore_question(arguments)
            else:
                result = {"error": f"Unknown tool: {name}"}
            
            return [TextContent(
                type="text",
                text=json.dumps(result, ensure_ascii=False, indent=2)
            )]
        except Exception as e:
            logger.error(f"Tool error: {e}")
            return [TextContent(
                type="text",
                text=json.dumps({"error": str(e)}, ensure_ascii=False)
            )]
    
    return server


def save_question(args: dict) -> dict:
    """儲存考題到 SQLite"""
    
    # 建立來源
    source = None
    if args.get("source_doc"):
        source = Source(
            document=args.get("source_doc", ""),
            page=args.get("source_page"),
            lines=args.get("source_lines"),
            original_text=args.get("source_text"),
        )
    
    # 建立 Question 實體
    question = Question(
        question_text=args.get("question_text", ""),
        options=args.get("options", []),
        correct_answer=args.get("correct_answer", ""),
        explanation=args.get("explanation", ""),
        source=source,
        difficulty=Difficulty(args.get("difficulty", "medium")),
        topics=args.get("topics", []),
        created_by=args.get("actor_name", "crush"),
    )
    
    # 生成上下文（記錄題目如何產生）
    generation_context = {
        "user_prompt": args.get("user_prompt"),
        "source_documents": [args.get("source_doc")] if args.get("source_doc") else [],
        "skill_used": args.get("skill_used", "mcq-generator"),
        "reasoning": args.get("reasoning"),
    }
    
    # 儲存到 Repository
    question_id = repo.save(
        question=question,
        actor_type=ActorType.AGENT,
        actor_name=args.get("actor_name", "crush"),
        generation_context=generation_context if any(generation_context.values()) else None,
    )
    
    return {
        "success": True,
        "question_id": question_id,
        "message": f"題目已儲存到 SQLite 資料庫",
    }


def list_questions(args: dict) -> dict:
    """列出考題 (使用 Repository)"""
    topic_filter = args.get("topic")
    difficulty_filter = args.get("difficulty")
    limit = args.get("limit", 20)
    
    # 從 Repository 取得
    difficulty = Difficulty(difficulty_filter) if difficulty_filter else None
    questions = repo.list_all(
        limit=limit,
        difficulty=difficulty,
        topic=topic_filter,
    )
    
    return {
        "total": len(questions),
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text[:50] + "..." if len(q.question_text) > 50 else q.question_text,
                "difficulty": q.difficulty.value,
                "topics": q.topics,
                "created_at": q.created_at.isoformat() if q.created_at else None,
            }
            for q in questions
        ],
    }


def create_exam(args: dict) -> dict:
    """建立考卷"""
    import uuid
    import random
    
    exam_name = args.get("name", "新考卷")
    question_count = args.get("question_count", 10)
    topic_filter = args.get("topics", [])
    
    # 讀取所有題目
    all_questions = []
    for filepath in QUESTIONS_DIR.glob("*.json"):
        with open(filepath, "r", encoding="utf-8") as f:
            q = json.load(f)
        
        # 套用篩選
        if topic_filter:
            if not any(t in q.get("topics", []) for t in topic_filter):
                continue
        
        all_questions.append(q)
    
    # 隨機選題
    if len(all_questions) < question_count:
        selected = all_questions
    else:
        selected = random.sample(all_questions, question_count)
    
    # 建立考卷
    exam_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    exam_data = {
        "id": exam_id,
        "name": exam_name,
        "questions": selected,
        "question_count": len(selected),
        "created_at": datetime.now().isoformat(),
    }
    
    filepath = EXAMS_DIR / f"exam_{timestamp}_{exam_id}.json"
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(exam_data, f, ensure_ascii=False, indent=2)
    
    return {
        "success": True,
        "exam_id": exam_id,
        "name": exam_name,
        "question_count": len(selected),
        "saved_to": str(filepath.relative_to(PROJECT_ROOT)),
    }


def get_stats() -> dict:
    """取得統計 (使用 Repository)"""
    stats = repo.get_statistics()
    
    return {
        "question_count": stats["total"],
        "exam_count": len(list(EXAMS_DIR.glob("*.json"))) if EXAMS_DIR.exists() else 0,
        "difficulty_distribution": stats["by_difficulty"],
        "topic_distribution": stats["by_topic"],
        "validated_count": stats["validated"],
        "deleted_count": stats["deleted"],
        "recent_7_days": stats["recent_7_days"],
    }


def get_question(args: dict) -> dict:
    """取得單一題目 (使用 Repository)"""
    question_id = args.get("question_id", "")
    
    question = repo.get_by_id(question_id)
    if question:
        # 同時取得審計日誌
        audit_log = repo.get_audit_log(question_id, limit=10)
        generation_ctx = repo.get_generation_context(question_id)
        
        return {
            "success": True,
            "question": question.to_dict(),
            "audit_log": [a.to_dict() for a in audit_log],
            "generation_context": generation_ctx,
        }
    
    return {
        "success": False,
        "error": f"Question not found: {question_id}",
    }


def delete_question(args: dict) -> dict:
    """刪除題目 (使用 Repository，軟刪除)"""
    question_id = args.get("question_id", "")
    actor_name = args.get("actor_name", "user")
    reason = args.get("reason")
    
    success = repo.delete(
        question_id=question_id,
        actor_type=ActorType.USER,
        actor_name=actor_name,
        reason=reason,
        soft_delete=True,
    )
    
    if success:
        return {
            "success": True,
            "deleted_id": question_id,
            "message": "題目已標記為刪除（可還原）",
        }
    
    return {
        "success": False,
        "error": f"Question not found: {question_id}",
    }


def validate_question(args: dict) -> dict:
    """驗證題目格式"""
    errors = []
    warnings = []
    
    # 必要欄位檢查
    question_text = args.get("question_text", "")
    if not question_text or len(question_text) < 10:
        errors.append("題目文字過短或為空")
    
    options = args.get("options", [])
    if len(options) < 2:
        errors.append("選項數量不足（至少需要 2 個選項）")
    elif len(options) < 4:
        warnings.append("建議提供 4 個選項")
    
    correct_answer = args.get("correct_answer", "")
    if not correct_answer:
        errors.append("缺少正確答案")
    else:
        # 檢查答案是否在選項範圍內
        valid_answers = [chr(65 + i) for i in range(len(options))]  # A, B, C, D...
        for ans in correct_answer.replace(",", "").replace(" ", ""):
            if ans.upper() not in valid_answers:
                errors.append(f"答案 '{ans}' 不在選項範圍內")
    
    question_type = args.get("question_type", "single_choice")
    if question_type == "single_choice" and "," in correct_answer:
        errors.append("單選題不應有多個答案")
    
    return {
        "valid": len(errors) == 0,
        "errors": errors,
        "warnings": warnings,
    }


def update_question(args: dict) -> dict:
    """更新已存在的題目"""
    question_id = args.get("question_id", "")
    
    # 先取得現有題目
    existing = repo.get_by_id(question_id)
    if not existing:
        return {
            "success": False,
            "error": f"Question not found: {question_id}",
        }
    
    # 更新欄位（只更新有提供的）
    if args.get("question_text"):
        existing.question_text = args["question_text"]
    if args.get("options"):
        existing.options = args["options"]
    if args.get("correct_answer"):
        existing.correct_answer = args["correct_answer"]
    if args.get("explanation"):
        existing.explanation = args["explanation"]
    if args.get("difficulty"):
        existing.difficulty = Difficulty(args["difficulty"])
    if args.get("topics"):
        existing.topics = args["topics"]
    
    # 儲存更新
    success = repo.update(
        question=existing,
        actor_type=ActorType.SKILL,
        actor_name=args.get("actor_name", "unknown"),
        reason=args.get("reason"),
    )
    
    return {
        "success": success,
        "question_id": question_id,
        "message": "題目已更新" if success else "更新失敗",
    }


def get_audit_log(args: dict) -> dict:
    """取得題目的審計日誌"""
    question_id = args.get("question_id", "")
    limit = args.get("limit", 20)
    
    entries = repo.get_audit_log(question_id, limit=limit)
    
    return {
        "question_id": question_id,
        "total": len(entries),
        "entries": [
            {
                "action": e.action.value,
                "actor": f"{e.actor_type.value}:{e.actor_name}",
                "timestamp": e.timestamp.isoformat() if e.timestamp else None,
                "changes": e.changes,
                "reason": e.reason,
            }
            for e in entries
        ],
    }


def mark_validated(args: dict) -> dict:
    """標記題目驗證結果"""
    question_id = args.get("question_id", "")
    passed = args.get("passed", False)
    notes = args.get("notes")
    
    success = repo.mark_validated(
        question_id=question_id,
        passed=passed,
        actor_name="question-validator",
        notes=notes,
    )
    
    return {
        "success": success,
        "question_id": question_id,
        "validated": passed,
        "message": "驗證結果已記錄" if success else "題目不存在",
    }


def search_questions(args: dict) -> dict:
    """搜尋題目"""
    keyword = args.get("keyword", "")
    limit = args.get("limit", 20)
    
    questions = repo.search(keyword, limit=limit)
    
    return {
        "keyword": keyword,
        "total": len(questions),
        "questions": [
            {
                "id": q.id,
                "question_text": q.question_text[:80] + "..." if len(q.question_text) > 80 else q.question_text,
                "difficulty": q.difficulty.value,
                "topics": q.topics,
            }
            for q in questions
        ],
    }


def restore_question(args: dict) -> dict:
    """還原已刪除的題目"""
    question_id = args.get("question_id", "")
    
    success = repo.restore(
        question_id=question_id,
        actor_type=ActorType.USER,
        actor_name="user",
    )
    
    return {
        "success": success,
        "question_id": question_id,
        "message": "題目已還原" if success else "題目不存在或未被刪除",
    }


async def main():
    """啟動 MCP Server"""
    server = create_exam_mcp_server()
    
    async with stdio_server() as (read_stream, write_stream):
        await server.run(
            read_stream,
            write_stream,
            server.create_initialization_options()
        )


if __name__ == "__main__":
    import asyncio
    asyncio.run(main())
