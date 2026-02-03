"""
Exam MCP Server - 考題生成 MCP 工具

提供考題生成相關的 MCP 工具，供 Crush agent 調用。
"""

import json
import logging
from pathlib import Path
from datetime import datetime
from typing import Optional

from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp.types import Tool, TextContent

# 設定日誌
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# 專案根目錄
PROJECT_ROOT = Path(__file__).parent.parent.parent.parent
DATA_DIR = PROJECT_ROOT / "data"
EXAMS_DIR = DATA_DIR / "exams"
QUESTIONS_DIR = DATA_DIR / "questions"


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
    """儲存考題"""
    import uuid
    
    question_id = str(uuid.uuid4())[:8]
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"q_{timestamp}_{question_id}.json"
    
    question_data = {
        "id": question_id,
        "question_text": args.get("question_text", ""),
        "options": args.get("options", []),
        "correct_answer": args.get("correct_answer", ""),
        "explanation": args.get("explanation", ""),
        "source": {
            "document": args.get("source_doc", ""),
            "page": args.get("source_page"),
        },
        "difficulty": args.get("difficulty", "medium"),
        "topics": args.get("topics", []),
        "created_at": datetime.now().isoformat(),
    }
    
    filepath = QUESTIONS_DIR / filename
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(question_data, f, ensure_ascii=False, indent=2)
    
    return {
        "success": True,
        "question_id": question_id,
        "saved_to": str(filepath.relative_to(PROJECT_ROOT)),
    }


def list_questions(args: dict) -> dict:
    """列出考題"""
    topic_filter = args.get("topic")
    difficulty_filter = args.get("difficulty")
    limit = args.get("limit", 20)
    
    questions = []
    for filepath in QUESTIONS_DIR.glob("*.json"):
        with open(filepath, "r", encoding="utf-8") as f:
            q = json.load(f)
        
        # 套用篩選
        if topic_filter and topic_filter not in q.get("topics", []):
            continue
        if difficulty_filter and q.get("difficulty") != difficulty_filter:
            continue
        
        questions.append({
            "id": q.get("id"),
            "question_text": q.get("question_text", "")[:50] + "...",
            "difficulty": q.get("difficulty"),
            "topics": q.get("topics", []),
        })
        
        if len(questions) >= limit:
            break
    
    return {
        "total": len(questions),
        "questions": questions,
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
    """取得統計"""
    question_count = len(list(QUESTIONS_DIR.glob("*.json")))
    exam_count = len(list(EXAMS_DIR.glob("*.json")))
    
    # 統計難度分布
    difficulty_stats = {"easy": 0, "medium": 0, "hard": 0}
    topic_stats: dict[str, int] = {}
    
    for filepath in QUESTIONS_DIR.glob("*.json"):
        with open(filepath, "r", encoding="utf-8") as f:
            q = json.load(f)
        
        diff = q.get("difficulty", "medium")
        difficulty_stats[diff] = difficulty_stats.get(diff, 0) + 1
        
        for topic in q.get("topics", []):
            topic_stats[topic] = topic_stats.get(topic, 0) + 1
    
    return {
        "question_count": question_count,
        "exam_count": exam_count,
        "difficulty_distribution": difficulty_stats,
        "topic_distribution": topic_stats,
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
