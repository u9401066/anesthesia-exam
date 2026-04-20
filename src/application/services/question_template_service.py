"""Historical-question-backed template service for the draft authoring workflow."""

from __future__ import annotations

from collections import Counter, defaultdict

from src.domain.entities.past_exam import PastExamQuestion, QuestionPattern
from src.domain.entities.question import Difficulty, Question, QuestionType
from src.domain.entities.question_draft import (
    DraftBlueprint,
    DraftQAMetadata,
    DraftTemplateReference,
    QuestionDraft,
)
from src.infrastructure.persistence.sqlite_past_exam_repo import get_past_exam_repository

PATTERN_LABELS = {
    QuestionPattern.DIRECT_RECALL.value: "直接記憶",
    QuestionPattern.CLINICAL_SCENARIO.value: "臨床情境",
    QuestionPattern.COMPARISON.value: "比較判讀",
    QuestionPattern.MECHANISM.value: "機轉理解",
    QuestionPattern.CALCULATION.value: "計算應用",
    QuestionPattern.IMAGE_BASED.value: "圖像判讀",
    QuestionPattern.BEST_ANSWER.value: "最佳答案",
    QuestionPattern.NEGATION.value: "否定判讀",
    QuestionPattern.SEQUENCE.value: "流程順序",
}


class QuestionTemplateService:
    """Build reusable authoring templates from normalized past exam questions."""

    def __init__(self):
        self.repo = get_past_exam_repository()
        self._template_cache: list[dict] | None = None

    def list_templates(self, limit: int = 8) -> list[dict]:
        if self._template_cache is None:
            self._template_cache = self._build_template_catalog()
        return self._template_cache[:limit]

    def get_template(self, template_id: str) -> dict | None:
        for template in self.list_templates(limit=24):
            if template.get("template_id") == template_id:
                return template
        return None

    def build_draft_from_template(self, template_id: str) -> QuestionDraft | None:
        template = self.get_template(template_id)
        if template is None:
            return None

        option_count = max(int(template.get("option_count", 4) or 4), 4)
        difficulty_value = template.get("difficulty", Difficulty.MEDIUM.value)
        difficulty = Difficulty(difficulty_value) if difficulty_value in {d.value for d in Difficulty} else Difficulty.MEDIUM

        question = Question(
            question_text=template.get("stem_scaffold", ""),
            options=[f"選項 {chr(65 + index)}（待編修）" for index in range(option_count)],
            correct_answer="",
            explanation="",
            question_type=QuestionType.SINGLE_CHOICE,
            difficulty=difficulty,
            topics=list(template.get("topics", [])),
            is_validated=False,
            created_by="historical-template",
        )

        return QuestionDraft(
            question=question,
            origin="historical_template",
            template_data=DraftTemplateReference.from_dict(template),
            blueprint_data=DraftBlueprint.from_dict(template.get("blueprint")),
            qa_metadata=DraftQAMetadata(),
        )

    def _build_template_catalog(self) -> list[dict]:
        questions = self._load_historical_questions(limit=20)
        if not questions:
            return []

        by_pattern: dict[str, list[PastExamQuestion]] = defaultdict(list)
        pattern_counts = Counter()
        for question in questions:
            pattern = question.pattern.value if hasattr(question.pattern, "value") else str(question.pattern)
            by_pattern[pattern].append(question)
            pattern_counts[pattern] += 1

        for group in by_pattern.values():
            group.sort(key=lambda item: (-int(item.exam_year or 0), int(item.question_number or 0), item.id))

        ordered_patterns = [pattern for pattern, _count in pattern_counts.most_common()]
        positions = {pattern: 0 for pattern in ordered_patterns}
        templates: list[dict] = []

        while len(templates) < 12:
            added = False
            for pattern in ordered_patterns:
                group = by_pattern.get(pattern, [])
                cursor = positions.get(pattern, 0)
                if cursor >= len(group):
                    continue
                exemplar = group[cursor]
                positions[pattern] = cursor + 1
                templates.append(self._build_template(exemplar, group, pattern_counts))
                added = True
                if len(templates) >= 12:
                    break
            if not added:
                break

        return templates

    def _build_template(
        self,
        exemplar: PastExamQuestion,
        sibling_questions: list[PastExamQuestion],
        pattern_counts: Counter,
    ) -> dict:
        pattern = exemplar.pattern.value if hasattr(exemplar.pattern, "value") else str(exemplar.pattern)
        topics = self._top_values(topic for question in sibling_questions for topic in question.topics if topic)
        concepts = self._top_values(
            concept for question in sibling_questions for concept in question.concept_names if concept
        )
        source_refs = [self._format_source_ref(question) for question in sibling_questions[:3]]
        blueprint = {
            "pattern": pattern,
            "pattern_label": PATTERN_LABELS.get(pattern, pattern),
            "difficulty": exemplar.difficulty or Difficulty.MEDIUM.value,
            "bloom_level": int(exemplar.bloom_level or 1),
            "target_topics": topics,
            "reference_concepts": concepts,
            "recommended_rules": self._recommended_rules(pattern, exemplar, topics),
            "sample_source_refs": source_refs,
            "historical_pattern_distribution": dict(pattern_counts),
            "source_exam_years": sorted(
                {int(question.exam_year) for question in sibling_questions if question.exam_year},
                reverse=True,
            )[:6],
        }

        return {
            "template_id": f"{pattern}:{exemplar.exam_year}:{exemplar.question_number}:{exemplar.id[:8]}",
            "label": f"{PATTERN_LABELS.get(pattern, pattern)}骨架",
            "pattern": pattern,
            "pattern_label": PATTERN_LABELS.get(pattern, pattern),
            "source_exam_id": exemplar.past_exam_id,
            "source_question_id": exemplar.id,
            "source_exam_name": exemplar.exam_name,
            "source_exam_year": int(exemplar.exam_year or 0),
            "source_question_number": int(exemplar.question_number or 0),
            "option_count": max(len(exemplar.options), 4),
            "reference_question_text": exemplar.question_text,
            "stem_scaffold": self._build_stem_scaffold(exemplar, topics, concepts),
            "topics": topics or exemplar.topics[:3],
            "difficulty": exemplar.difficulty or Difficulty.MEDIUM.value,
            "bloom_level": int(exemplar.bloom_level or 1),
            "blueprint": blueprint,
        }

    def _load_historical_questions(self, limit: int = 20) -> list[PastExamQuestion]:
        exam_catalog = self.repo.list_exam_catalog(limit=limit)
        questions: list[PastExamQuestion] = []
        for exam in exam_catalog:
            questions.extend(self.repo.list_questions(exam["id"]))
        return questions

    def _build_stem_scaffold(
        self,
        exemplar: PastExamQuestion,
        topics: list[str],
        concepts: list[str],
    ) -> str:
        anchor = (concepts[:1] or topics[:1] or ["核心主題"])[0]
        pattern = exemplar.pattern.value if hasattr(exemplar.pattern, "value") else str(exemplar.pattern)

        if pattern == QuestionPattern.NEGATION.value:
            return f"關於 {anchor}，下列敘述何者錯誤？"
        if pattern == QuestionPattern.CLINICAL_SCENARIO.value:
            return f"一名與 {anchor} 相關的臨床個案接受麻醉處置時，下列何者最適當？"
        if pattern == QuestionPattern.COMPARISON.value:
            return f"比較 {anchor} 的兩種常見策略時，下列敘述何者最適當？"
        if pattern == QuestionPattern.MECHANISM.value:
            return f"關於 {anchor} 的機轉與生理影響，下列敘述何者最適當？"
        if pattern == QuestionPattern.CALCULATION.value:
            return f"依據 {anchor} 的臨床參數估算，下列哪一個答案最合理？"
        if pattern == QuestionPattern.IMAGE_BASED.value:
            return f"根據與 {anchor} 相關的圖像或監測畫面，下列判讀何者最適當？"
        if pattern == QuestionPattern.SEQUENCE.value:
            return f"處理 {anchor} 的臨床流程時，下列步驟順序何者最適當？"
        if pattern == QuestionPattern.BEST_ANSWER.value:
            return f"關於 {anchor} 的處置選項，下列何者為最佳答案？"
        return f"關於 {anchor}，下列敘述何者最適當？"

    def _recommended_rules(self, pattern: str, exemplar: PastExamQuestion, topics: list[str]) -> list[str]:
        anchor = (topics[:1] or exemplar.topics[:1] or exemplar.concept_names[:1] or ["核心概念"])[0]
        rules = [
            "保留歷史題型骨架，但改寫題幹與選項，不直接重寫原題。",
            f"本模板參考 {int(exemplar.exam_year or 0)} 年第 {int(exemplar.question_number or 0)} 題，主題聚焦於 {anchor}。",
        ]
        if pattern == QuestionPattern.NEGATION.value:
            rules.append("若沿用否定句型，需額外檢查選項可判別性，避免雙重否定。")
        elif pattern == QuestionPattern.CLINICAL_SCENARIO.value:
            rules.append("情境題需補齊病人條件、手術背景與決策關鍵資訊。")
        else:
            rules.append("正式入庫前應檢查答案、解析與來源是否彼此對齊。")
        return rules

    def _format_source_ref(self, question: PastExamQuestion) -> str:
        return f"{int(question.exam_year or 0)} {question.exam_name} 第 {int(question.question_number or 0)} 題"

    def _top_values(self, values) -> list[str]:
        counter = Counter(value for value in values if value)
        return [name for name, _count in counter.most_common(5)]


_service: QuestionTemplateService | None = None


def get_question_template_service() -> QuestionTemplateService:
    """Return singleton historical template service."""
    global _service
    if _service is None:
        _service = QuestionTemplateService()
    return _service
