"""Application adapter for exam MCP question-bank tools."""

from __future__ import annotations

import json
import random
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from src.domain.entities.question import Difficulty, Question, QuestionType, Source, SourceLocation
from src.domain.value_objects.audit import ActorType
from src.domain.value_objects.answer import coerce_question_type, normalize_answer_letters, question_allows_multiple


class ExamToolApplicationService:
    """Handle question-bank oriented MCP tool operations outside the server bootstrap."""

    def __init__(self, *, repo, project_root: Path, exams_dir: Path, questions_dir: Path):
        self.repo = repo
        self.project_root = project_root
        self.exams_dir = exams_dir
        self.questions_dir = questions_dir

    @staticmethod
    def _coerce_int(value: Any, *, default: int, min_value: int | None = None, max_value: int | None = None) -> int:
        if isinstance(value, bool):
            return default
        if isinstance(value, int):
            candidate = value
        elif isinstance(value, float):
            candidate = int(value)
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

        if min_value is not None and candidate < min_value:
            return default
        if max_value is not None and candidate > max_value:
            return default
        return candidate

    @staticmethod
    def _coerce_str(value: Any, *, default: str = "") -> str:
        if value is None:
            return default
        value = str(value).strip()
        return value if value else default

    @staticmethod
    def _coerce_str_list(value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    @staticmethod
    def _coerce_topic_list(value: Any) -> list[str]:
        return ExamToolApplicationService._coerce_str_list(value)

    @staticmethod
    def _coerce_difficulty(value: Any) -> Difficulty:
        if value is None:
            return Difficulty.MEDIUM
        try:
            return Difficulty(str(value).strip().lower())
        except ValueError:
            return Difficulty.MEDIUM

    @staticmethod
    def _coerce_question_type(value: Any, *, fallback_pattern: Any = None) -> QuestionType:
        normalized = coerce_question_type(value, fallback_pattern=fallback_pattern)
        return {
            "single_choice": QuestionType.SINGLE_CHOICE,
            "multiple_choice": QuestionType.MULTIPLE_CHOICE,
            "true_false": QuestionType.TRUE_FALSE,
            "fill_in_blank": QuestionType.FILL_IN_BLANK,
            "short_answer": QuestionType.SHORT_ANSWER,
            "essay": QuestionType.ESSAY,
            "image_based": QuestionType.IMAGE_BASED,
        }.get(normalized, QuestionType.SINGLE_CHOICE)

    @staticmethod
    def _build_source(args: dict) -> Source | None:
        source_payload = args.get("source")
        source_doc = None
        if isinstance(source_payload, dict):
            source_doc = source_payload.get("document")
        if not source_doc:
            source_doc = args.get("source_doc")

        if not source_doc:
            return None

        source_payload = source_payload if isinstance(source_payload, dict) else {}
        stem_source = ExamToolApplicationService._parse_source_location(
            source_payload.get("stem_source")
            if isinstance(source_payload, dict)
            else args.get("stem_source")
        )
        answer_source = ExamToolApplicationService._parse_source_location(
            source_payload.get("answer_source")
            if isinstance(source_payload, dict)
            else args.get("answer_source")
        )
        explanation_sources: list[SourceLocation] = []
        raw_explanation_sources = source_payload.get("explanation_sources", args.get("explanation_sources", []))
        if isinstance(raw_explanation_sources, list):
            for source_data in raw_explanation_sources:
                parsed = ExamToolApplicationService._parse_source_location(source_data)
                if parsed is not None:
                    explanation_sources.append(parsed)

        return Source(
            document=ExamToolApplicationService._coerce_str(source_doc, default=""),
            chapter=ExamToolApplicationService._coerce_str(source_payload.get("chapter") or args.get("source_chapter"), default=None),
            section=ExamToolApplicationService._coerce_str(source_payload.get("section") or args.get("source_section"), default=None),
            stem_source=stem_source,
            answer_source=answer_source,
            explanation_sources=explanation_sources,
            page=ExamToolApplicationService._coerce_int(
                source_payload.get("page") if source_payload else args.get("source_page"),
                default=0,
            )
            or None,
            lines=(
                ExamToolApplicationService._coerce_str(source_payload.get("lines"), default=None)
                or ExamToolApplicationService._coerce_str(args.get("source_lines"), default=None)
            ),
            original_text=(
                ExamToolApplicationService._coerce_str(source_payload.get("original_text"), default=None)
                or ExamToolApplicationService._coerce_str(args.get("source_text"), default=None)
            ),
        )

    def save_question(self, args: dict) -> dict:
        args = args or {}
        question_type = self._coerce_question_type(args.get("question_type"), fallback_pattern=args.get("pattern"))
        if question_type == QuestionType.IMAGE_BASED:
            return {
                "success": False,
                "error": "image_based 題目目前不可正式入庫，因正式題庫尚未支援圖資持久化；請先保留在草稿或來源題庫。",
            }

        source = self._build_source(args)
        if source is not None:
            if args.get("preview_only"):
                return {
                    "success": False,
                    "error": "preview-only 題目不可正式入庫，請先送進草稿箱。",
                }

            source_payload = args.get("source") if isinstance(args.get("source"), dict) else {}
            stem_source = self._parse_source_location(
                source_payload.get("stem_source") if source_payload else args.get("stem_source")
            )
            answer_source = self._parse_source_location(
                source_payload.get("answer_source") if source_payload else args.get("answer_source")
            )
            missing_fields: list[str] = []

            if not self._has_precise_source_location(stem_source):
                missing_fields.append("stem_source")
            if not self._has_precise_source_location(answer_source):
                missing_fields.append("answer_source")
            explanation_sources = source.explanation_sources if source else []
            if not any(self._has_precise_source_location(source_item) for source_item in explanation_sources):
                missing_fields.append("explanation_sources")
            if missing_fields:
                return {
                    "success": False,
                    "error": "教材題目正式入庫需要完整 evidence pack，缺少: " + ", ".join(missing_fields),
                }

        question_text = self._coerce_str(args.get("question_text"), default="")
        options = self._coerce_str_list(args.get("options"))
        correct_answer = self._coerce_str(args.get("correct_answer"), default="")
        explanation = self._coerce_str(args.get("explanation"), default="")
        topics = self._coerce_topic_list(args.get("topics"))
        actor_name = self._coerce_str(args.get("actor_name"), default="crush")

        validation = self.validate_question(
            {
                "question_text": question_text,
                "options": options,
                "correct_answer": correct_answer,
                "question_type": question_type.value,
                "pattern": args.get("pattern"),
            }
        )
        if not validation.get("valid"):
            return {"success": False, "error": "; ".join(validation.get("errors", []))}

        question = Question(
            question_text=question_text,
            options=options,
            correct_answer=correct_answer,
            explanation=explanation,
            source=source,
            question_type=question_type,
            difficulty=self._coerce_difficulty(args.get("difficulty")),
            topics=topics,
            created_by=actor_name,
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
            actor_name=actor_name,
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
        args = args or {}
        topic_filter = args.get("topic")
        difficulty_filter = args.get("difficulty")
        limit = self._coerce_int(args.get("limit"), default=20, min_value=1, max_value=500)

        difficulty = self._coerce_difficulty(difficulty_filter) if difficulty_filter else None
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
        args = args or {}
        exam_name = self._coerce_str(args.get("name"), default="新考卷")
        question_count = self._coerce_int(args.get("question_count"), default=10, min_value=1)
        topic_filter = args.get("topics", [])
        if not isinstance(topic_filter, list):
            topic_filter = []

        if not self.questions_dir.exists():
            return {"success": False, "error": f"題庫目錄不存在：{self.questions_dir}"}

        all_questions = []
        for filepath in self.questions_dir.glob("*.json"):
            try:
                with open(filepath, "r", encoding="utf-8") as file_handle:
                    question = json.load(file_handle)
            except (json.JSONDecodeError, OSError):
                continue

            if topic_filter and not any(topic in question.get("topics", []) for topic in topic_filter):
                continue
            all_questions.append(question)

        if not all_questions:
            return {
                "success": False,
                "error": "題庫中無可用題目，請先寫入題目後再建立考卷。",
            }

        selected = random.sample(all_questions, min(len(all_questions), question_count))
        exam_id = str(uuid.uuid4())[:8]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        exam_data = {
            "id": exam_id,
            "name": exam_name,
            "questions": selected,
            "question_count": len(selected),
            "requested_question_count": question_count,
            "available_question_count": len(all_questions),
            "created_at": datetime.now().isoformat(),
        }

        filepath = self.exams_dir / f"exam_{timestamp}_{exam_id}.json"
        filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as file_handle:
            json.dump(exam_data, file_handle, ensure_ascii=False, indent=2)

        return {
            "success": True,
            "exam_id": exam_id,
            "name": exam_name,
            "question_count": len(selected),
            "requested_question_count": question_count,
            "saved_to": str(filepath.relative_to(self.project_root)),
        }

    def get_stats(self, _args: dict | None = None) -> dict:
        stats = self.repo.get_statistics()
        return {
            "question_count": stats.get("total", 0),
            "exam_count": len(list(self.exams_dir.glob("*.json"))) if self.exams_dir.exists() else 0,
            "difficulty_distribution": stats.get("by_difficulty", {}),
            "topic_distribution": stats.get("by_topic", {}),
            "validated_count": stats.get("validated", 0),
            "deleted_count": stats.get("deleted", 0),
            "recent_7_days": stats.get("recent_7_days", 0),
        }

    def get_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        question = self.repo.get_by_id(question_id)
        if not question:
            return {"success": False, "error": f"Question not found: {question_id}"}

        audit_log = self.repo.get_audit_log(question_id, limit=self._coerce_int(args.get("limit"), default=10, min_value=1))
        generation_ctx = self.repo.get_generation_context(question_id)
        return {
            "success": True,
            "question": question.to_dict(),
            "audit_log": [entry.to_dict() for entry in audit_log],
            "generation_context": generation_ctx,
        }

    def delete_question(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        actor_name = self._coerce_str(args.get("actor_name"), default="user")
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
        args = args or {}
        errors: list[str] = []
        warnings: list[str] = []

        question_text = self._coerce_str(args.get("question_text"), default="")
        if not question_text or len(question_text) < 10:
            errors.append("題目文字過短或為空")

        question_type = coerce_question_type(
            args.get("question_type"),
            fallback_pattern=args.get("pattern"),
        )
        option_count = len(self._coerce_str_list(args.get("options")))
        options = self._coerce_str_list(args.get("options"))
        correct_answer = self._coerce_str(args.get("correct_answer"), default="")

        if question_type in {"single_choice", "multiple_choice"}:
            if option_count < 2:
                errors.append("選項數量不足（至少需要 2 個選項）")
            elif option_count < 4:
                warnings.append("建議提供 4 個選項")
        if question_type == "true_false":
            if option_count not in {0, 2}:
                warnings.append("是非題建議提供 2 個選項")

        if question_type in {"single_choice", "multiple_choice", "true_false"}:
            if not correct_answer:
                errors.append("缺少正確答案")
            normalized_answers = normalize_answer_letters(correct_answer, option_count=option_count or None)
            if option_count and not normalized_answers:
                errors.append("答案不在選項有效範圍內")
            elif question_type == "single_choice" and len(normalized_answers) != 1:
                errors.append("單選題只能有一個答案")
            elif question_type == "multiple_choice" and len(normalized_answers) < 2:
                errors.append("多選題至少需要兩個答案")
        elif question_type in {"fill_in_blank", "short_answer", "essay"}:
            if not correct_answer:
                errors.append("填空/簡答/問答題請提供答案欄位")

        if question_type in {"fill_in_blank", "short_answer", "essay"} and options:
            warnings.append(f"{question_type} 題型通常不需要選項")

        allows_multiple = question_allows_multiple(
            {"question_type": question_type, "correct_answer": correct_answer, "pattern": args.get("pattern")},
            option_count=option_count,
            correct_answer=correct_answer,
        )
        if allows_multiple and question_type == "single_choice":
            warnings.append("題型判斷為可複選，建議確認是否應為多選")
        if not allows_multiple and len(normalize_answer_letters(correct_answer, option_count=option_count or None)) > 1:
            errors.append("該題型不應有多個答案")

        if question_type not in {
            "single_choice",
            "multiple_choice",
            "true_false",
            "fill_in_blank",
            "short_answer",
            "essay",
            "image_based",
        }:
            errors.append("題目類型不可辨識")

        return {"valid": len(errors) == 0, "errors": errors, "warnings": warnings}

    def update_question(self, args: dict) -> dict:
        args = args or {}
        question_id = args.get("question_id", "")
        existing = self.repo.get_by_id(question_id)
        if not existing:
            return {"success": False, "error": f"Question not found: {question_id}"}

        if args.get("question_text") is not None:
            existing.question_text = self._coerce_str(args.get("question_text"), default=existing.question_text)
        if args.get("options") is not None:
            existing.options = self._coerce_str_list(args.get("options"))
        if args.get("correct_answer") is not None:
            existing.correct_answer = self._coerce_str(args.get("correct_answer"), default=existing.correct_answer)
        if args.get("explanation") is not None:
            existing.explanation = self._coerce_str(args.get("explanation"), default=existing.explanation)
        if args.get("difficulty") is not None:
            existing.difficulty = self._coerce_difficulty(args.get("difficulty"))
        if args.get("topics") is not None:
            existing.topics = self._coerce_topic_list(args.get("topics"))
        if args.get("question_type") is not None or args.get("pattern") is not None:
            existing.question_type = self._coerce_question_type(args.get("question_type"), fallback_pattern=args.get("pattern"))

        if existing.question_type in {QuestionType.IMAGE_BASED}:
            return {"success": False, "error": "image_based 題目目前不可正式更新入庫。"}

        validation = self.validate_question(
            {
                "question_text": existing.question_text,
                "options": existing.options,
                "correct_answer": existing.correct_answer,
                "question_type": existing.question_type.value,
                "pattern": existing.question_type.value,
            }
        )
        if not validation.get("valid"):
            return {"success": False, "error": "; ".join(validation.get("errors", []))}

        actor_name = self._coerce_str(args.get("actor_name"), default="unknown")
        success = self.repo.update(
            question=existing,
            actor_type=ActorType.SKILL,
            actor_name=actor_name,
            reason=args.get("reason"),
        )
        return {
            "success": success,
            "question_id": question_id,
            "message": "題目已更新" if success else "更新失敗",
        }

    def get_audit_log(self, args: dict) -> dict:
        question_id = args.get("question_id", "")
        limit = self._coerce_int(args.get("limit"), default=20, min_value=1)
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
        passed = bool(args.get("passed", False))
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
        args = args or {}
        keyword = self._coerce_str(args.get("keyword"), default="")
        limit = self._coerce_int(args.get("limit"), default=20, min_value=1, max_value=500)
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
        args = args or {}
        questions_data = args.get("questions", [])
        if not questions_data:
            return {"success": False, "error": "未提供任何題目"}
        if not isinstance(questions_data, list):
            return {"success": False, "error": "questions 必須是陣列"}

        results = []
        success_count = 0
        fail_count = 0
        for index, question_args in enumerate(questions_data):
            try:
                result = self.save_question(question_args if isinstance(question_args, dict) else {})
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
        if not isinstance(data, dict):
            return None

        bbox = data.get("bbox")
        parsed_bbox = None
        if isinstance(bbox, (list, tuple)) and len(bbox) >= 4:
            try:
                parsed_bbox = (
                    float(bbox[0]),
                    float(bbox[1]),
                    float(bbox[2]),
                    float(bbox[3]),
                )
            except (TypeError, ValueError):
                parsed_bbox = None

        return SourceLocation(
            page=ExamToolApplicationService._coerce_int(data.get("page"), default=0, min_value=0),
            line_start=ExamToolApplicationService._coerce_int(data.get("line_start"), default=0, min_value=0),
            line_end=ExamToolApplicationService._coerce_int(data.get("line_end"), default=0, min_value=0),
            bbox=parsed_bbox,
            original_text=ExamToolApplicationService._coerce_str(data.get("original_text"), default=""),
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
