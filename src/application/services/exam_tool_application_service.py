"""Application adapter for exam MCP question-bank tools."""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime
from pathlib import Path

from src.domain.entities.question import Difficulty, Question, Source, SourceLocation
from src.domain.value_objects.audit import ActorType


class ExamToolApplicationService:
    """Handle question-bank oriented MCP tool operations outside the server bootstrap."""

    def __init__(self, *, repo, project_root: Path, exams_dir: Path, questions_dir: Path):
        self.repo = repo
        self.project_root = project_root
        self.exams_dir = exams_dir
        self.questions_dir = questions_dir

    def save_question(self, args: dict) -> dict:
        if str(args.get("pattern") or "").strip().lower() == "image_based":
            return {
                "success": False,
                "error": "image_based 題目目前不可正式入庫，因正式題庫尚未支援圖資持久化；請先保留在草稿或來源題庫。",
            }

        source = None
        if args.get("source_doc"):
            stem_source = self._parse_source_location(args.get("stem_source"))
            answer_source = self._parse_source_location(args.get("answer_source"))
            explanation_sources = [
                parsed for source_data in args.get("explanation_sources", []) if source_data and (parsed := self._parse_source_location(source_data))
            ]

            if args.get("preview_only"):
                return {
                    "success": False,
                    "error": "preview-only 題目不可正式入庫，請先送進草稿箱。",
                }

            missing_fields = []
            if not self._has_precise_source_location(stem_source):
                missing_fields.append("stem_source")
            if not self._has_precise_source_location(answer_source):
                missing_fields.append("answer_source")
            if not any(self._has_precise_source_location(source_item) for source_item in explanation_sources):
                missing_fields.append("explanation_sources")
            if missing_fields:
                return {
                    "success": False,
                    "error": "教材題目正式入庫需要完整 evidence pack，缺少: " + ", ".join(missing_fields),
                }

            source = Source(
                document=args.get("source_doc", ""),
                chapter=args.get("source_chapter"),
                section=args.get("source_section"),
                stem_source=stem_source,
                answer_source=answer_source,
                explanation_sources=explanation_sources,
                page=args.get("source_page") if not stem_source else None,
                lines=args.get("source_lines") if not stem_source else None,
                original_text=args.get("source_text") if not stem_source else None,
            )

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

        generation_context = {
            "user_prompt": args.get("user_prompt"),
            "source_documents": [args.get("source_doc")] if args.get("source_doc") else [],
            "skill_used": args.get("skill_used", "mcq-generator"),
            "reasoning": args.get("reasoning"),
        }
        question_id = self.repo.save(
            question=question,
            actor_type=ActorType.AGENT,
            actor_name=args.get("actor_name", "crush"),
            generation_context=generation_context if any(generation_context.values()) else None,
        )

        source_completeness = "none"
        if source:
            if source.stem_source and source.stem_source.original_text:
                source_completeness = "full"
            elif source.page:
                source_completeness = "partial"
            else:
                source_completeness = "doc_only"

        return {
            "success": True,
            "question_id": question_id,
            "message": "題目已儲存到 SQLite 資料庫",
            "source_completeness": source_completeness,
        }

    def list_questions(self, args: dict) -> dict:
        topic_filter = args.get("topic")
        difficulty_filter = args.get("difficulty")
        limit = args.get("limit", 20)

        difficulty = Difficulty(difficulty_filter) if difficulty_filter else None
        questions = self.repo.list_all(limit=limit, difficulty=difficulty, topic=topic_filter)
        return {
            "total": len(questions),
            "questions": [
                {
                    "id": question.id,
                    "question_text": question.question_text[:50] + "..."
                    if len(question.question_text) > 50
                    else question.question_text,
                    "difficulty": question.difficulty.value,
                    "topics": question.topics,
                    "created_at": question.created_at.isoformat() if question.created_at else None,
                }
                for question in questions
            ],
        }

    def create_exam(self, args: dict) -> dict:
        exam_name = args.get("name", "新考卷")
        question_count = args.get("question_count", 10)
        topic_filter = args.get("topics", [])

        all_questions = []
        for filepath in self.questions_dir.glob("*.json"):
            with open(filepath, "r", encoding="utf-8") as file_handle:
                question = json.load(file_handle)

            if topic_filter and not any(topic in question.get("topics", []) for topic in topic_filter):
                continue
            all_questions.append(question)

        selected = all_questions if len(all_questions) < question_count else random.sample(all_questions, question_count)
        exam_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exam_data = {
            "id": exam_id,
            "name": exam_name,
            "questions": selected,
            "question_count": len(selected),
            "created_at": datetime.now().isoformat(),
        }

        filepath = self.exams_dir / f"exam_{timestamp}_{exam_id}.json"
        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(exam_data, file_handle, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "exam_id": exam_id,
            "name": exam_name,
            "question_count": len(selected),
            "saved_to": str(filepath.relative_to(self.project_root)),
        }

    def get_stats(self, _args: dict | None = None) -> dict:
        stats = self.repo.get_statistics()
        return {
            "question_count": stats["total"],
            "exam_count": len(list(self.exams_dir.glob("*.json"))) if self.exams_dir.exists() else 0,
            "difficulty_distribution": stats["by_difficulty"],
            "topic_distribution": stats["by_topic"],
            "validated_count": stats["validated"],
            "deleted_count": stats["deleted"],
            "recent_7_days": stats["recent_7_days"],
        }

    def get_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        question = self.repo.get_by_id(question_id)
        if not question:
            return {"success": False, "error": f"Question not found: {question_id}"}

        audit_log = self.repo.get_audit_log(question_id, limit=10)
        generation_ctx = self.repo.get_generation_context(question_id)
        return {
            "success": True,
            "question": question.to_dict(),
            "audit_log": [entry.to_dict() for entry in audit_log],
            "generation_context": generation_ctx,
        }

    def delete_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        actor_name = args.get("actor_name", "user")
        reason = args.get("reason")
        success = self.repo.delete(
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
        return {"success": False, "error": f"Question not found: {question_id}"}

    def validate_question(self, args: dict) -> dict:
        errors = []
        warnings = []

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
            valid_answers = [chr(65 + index) for index in range(len(options))]
            for answer in correct_answer.replace(",", "").replace(" ", ""):
                if answer.upper() not in valid_answers:
                    errors.append(f"答案 '{answer}' 不在選項範圍內")

        question_type = args.get("question_type", "single_choice")
        if question_type == "single_choice" and "," in correct_answer:
            errors.append("單選題不應有多個答案")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def update_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        existing = self.repo.get_by_id(question_id)
        if not existing:
            return {"success": False, "error": f"Question not found: {question_id}"}

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

        success = self.repo.update(
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

    def get_audit_log(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        limit = args.get("limit", 20)
        entries = self.repo.get_audit_log(question_id, limit=limit)
        return {
            "question_id": question_id,
            "total": len(entries),
            "entries": [
                {
                    "action": entry.action.value,
                    "actor": f"{entry.actor_type.value}:{entry.actor_name}",
                    "timestamp": entry.timestamp.isoformat() if entry.timestamp else None,
                    "changes": entry.changes,
                    "reason": entry.reason,
                }
                for entry in entries
            ],
        }

    def mark_validated(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        passed = args.get("passed", False)
        notes = args.get("notes")
        success = self.repo.mark_validated(
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

    def search_questions(self, args: dict) -> dict:
        keyword = args.get("keyword", "")
        limit = args.get("limit", 20)
        questions = self.repo.search(keyword, limit=limit)
        return {
            "keyword": keyword,
            "total": len(questions),
            "questions": [
                {
                    "id": question.id,
                    "question_text": question.question_text[:80] + "..."
                    if len(question.question_text) > 80
                    else question.question_text,
                    "difficulty": question.difficulty.value,
                    "topics": question.topics,
                }
                for question in questions
            ],
        }

    def restore_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        success = self.repo.restore(
            question_id=question_id,
            actor_type=ActorType.USER,
            actor_name="user",
        )
        return {
            "success": success,
            "question_id": question_id,
            "message": "題目已還原" if success else "題目不存在或未被刪除",
        }

    def bulk_save(self, args: dict) -> dict:
        questions_data = args.get("questions", [])
        if not questions_data:
            return {"success": False, "error": "未提供任何題目"}

        results = []
        success_count = 0
        fail_count = 0
        for index, question_args in enumerate(questions_data):
            try:
                result = self.save_question(question_args)
            except Exception as exc:  # noqa: BLE001
                fail_count += 1
                results.append({"index": index, "success": False, "error": str(exc)})
                continue

            if result.get("success"):
                success_count += 1
                results.append({"index": index, "success": True, "question_id": result["question_id"]})
            else:
                fail_count += 1
                results.append({"index": index, "success": False, "error": result.get("error", "未知錯誤")})

        return {
            "success": fail_count == 0,
            "total": len(questions_data),
            "saved": success_count,
            "failed": fail_count,
            "results": results,
        }

    @staticmethod
    def _parse_source_location(data: dict | None) -> SourceLocation | None:
        if not data:
            return None
        return SourceLocation(
            page=data.get("page", 0),
            line_start=data.get("line_start", 0),
            line_end=data.get("line_end", 0),
            bbox=tuple(data["bbox"]) if data.get("bbox") else None,
            original_text=data.get("original_text", ""),
        )

    @staticmethod
    def _has_precise_source_location(location: SourceLocation | None) -> bool:
        return bool(
            location
            and location.page > 0
            and location.line_start > 0
            and location.line_end >= location.line_start
            and location.original_text.strip()
        )