"""Past exam extraction and classification service.

This service bridges asset-aware document artifacts with the exam-generator
past-exam pipeline. It focuses on four responsibilities:

1. Load shared asset-aware artifacts by ``doc_id``.
2. Normalize numbered question blocks and answer keys into structured records.
3. Derive concept/pattern/difficulty tags using deterministic heuristics.
4. Aggregate extracted questions into a reusable blueprint/reference summary.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from src.domain.entities.past_exam import Concept, PastExam, PastExamQuestion, QuestionPattern
from src.domain.repositories.past_exam_repository import IPastExamRepository

PAGE_MARKER_RE = re.compile(r"<!--\s*Page\s+(\d+)\s*-->")
QUESTION_START_RE = re.compile(r"^\s*(\d{1,3})\s*[\.、\)）:：]\s*(.+?)\s*$")
ANSWER_HEADING_RE = re.compile(
    r"^\s{0,3}(?:#+\s*)?(?:答案|解答|參考答案|answer(?:\s+key)?|answers)\s*$",
    re.IGNORECASE,
)
INLINE_ANSWER_RE = re.compile(
    r"(?:答案|正確答案|answer(?:\s+key)?|correct\s+answer)\s*[:：]?\s*([A-E])",
    re.IGNORECASE,
)
OPTION_START_RE = re.compile(r"(?<![A-Z0-9])([A-E])[\.、\)）:：]\s*")
OPTION_RE = re.compile(
    r"(?<![A-Z0-9])([A-E])[\.、\)）:：]\s*(.+?)(?=(?<![A-Z0-9])[A-E][\.、\)）:：]\s*|$)",
    re.IGNORECASE,
)
ANSWER_PAIR_RE = re.compile(r"(\d{1,3})\s*[\.、\)）:：-]?\s*([A-E])(?:\b|$)", re.IGNORECASE)
EXPLANATION_RE = re.compile(r"(?:解析|詳解|說明|explanation)\s*[:：]\s*(.+)$", re.IGNORECASE)

ENGLISH_STOPWORDS = {
    "about",
    "according",
    "following",
    "which",
    "what",
    "when",
    "where",
    "during",
    "under",
    "after",
    "before",
    "patient",
    "patients",
    "study",
    "group",
    "question",
    "choice",
    "answer",
    "true",
    "false",
}

CONCEPT_RULES = [
    {
        "pattern": re.compile(r"\bpropofol\b|丙泊酚", re.IGNORECASE),
        "name": "Propofol",
        "category": "藥理學",
        "subcategory": "靜脈麻醉劑",
    },
    {
        "pattern": re.compile(r"\bremimazolam\b|瑞馬唑侖|雷米唑仑", re.IGNORECASE),
        "name": "Remimazolam",
        "category": "藥理學",
        "subcategory": "鎮靜藥物",
    },
    {
        "pattern": re.compile(r"\bmidazolam\b|咪達唑侖", re.IGNORECASE),
        "name": "Midazolam",
        "category": "藥理學",
        "subcategory": "鎮靜藥物",
    },
    {
        "pattern": re.compile(r"\bketamine\b|氯胺酮", re.IGNORECASE),
        "name": "Ketamine",
        "category": "藥理學",
        "subcategory": "靜脈麻醉劑",
    },
    {
        "pattern": re.compile(r"\betomidate\b|依托咪酯", re.IGNORECASE),
        "name": "Etomidate",
        "category": "藥理學",
        "subcategory": "靜脈麻醉劑",
    },
    {
        "pattern": re.compile(r"\bdexmedetomidine\b|右美托咪定", re.IGNORECASE),
        "name": "Dexmedetomidine",
        "category": "藥理學",
        "subcategory": "鎮靜藥物",
    },
    {
        "pattern": re.compile(r"\bfentanyl\b|芬太尼", re.IGNORECASE),
        "name": "Fentanyl",
        "category": "藥理學",
        "subcategory": "鴉片類止痛藥",
    },
    {
        "pattern": re.compile(r"\bremifentanil\b|瑞芬太尼", re.IGNORECASE),
        "name": "Remifentanil",
        "category": "藥理學",
        "subcategory": "鴉片類止痛藥",
    },
    {
        "pattern": re.compile(r"\brocuronium\b|羅庫溴銨", re.IGNORECASE),
        "name": "Rocuronium",
        "category": "藥理學",
        "subcategory": "肌肉鬆弛劑",
    },
    {
        "pattern": re.compile(r"succinylcholine|suxamethonium|琥珀膽鹼", re.IGNORECASE),
        "name": "Succinylcholine",
        "category": "藥理學",
        "subcategory": "肌肉鬆弛劑",
    },
    {
        "pattern": re.compile(r"\blidocaine\b|利多卡因", re.IGNORECASE),
        "name": "Lidocaine",
        "category": "藥理學",
        "subcategory": "局部麻醉藥",
    },
    {
        "pattern": re.compile(r"\bbupivacaine\b|布比卡因", re.IGNORECASE),
        "name": "Bupivacaine",
        "category": "藥理學",
        "subcategory": "局部麻醉藥",
    },
    {
        "pattern": re.compile(r"\bsevoflurane\b|七氟醚", re.IGNORECASE),
        "name": "Sevoflurane",
        "category": "藥理學",
        "subcategory": "吸入麻醉劑",
    },
    {
        "pattern": re.compile(r"\bdesflurane\b|地氟醚", re.IGNORECASE),
        "name": "Desflurane",
        "category": "藥理學",
        "subcategory": "吸入麻醉劑",
    },
    {
        "pattern": re.compile(r"\bisoflurane\b|異氟醚", re.IGNORECASE),
        "name": "Isoflurane",
        "category": "藥理學",
        "subcategory": "吸入麻醉劑",
    },
    {
        "pattern": re.compile(r"gaba[-\s]?a|gaba_a|gaba 受體|gaba-a 受體", re.IGNORECASE),
        "name": "GABA-A receptor",
        "category": "機轉",
        "subcategory": "受體藥理",
    },
    {
        "pattern": re.compile(r"\bnmda\b|nmda 受體", re.IGNORECASE),
        "name": "NMDA receptor",
        "category": "機轉",
        "subcategory": "受體藥理",
    },
    {
        "pattern": re.compile(r"氣道|airway|插管|laryng|intubat", re.IGNORECASE),
        "name": "Airway management",
        "category": "臨床麻醉",
        "subcategory": "氣道管理",
    },
    {
        "pattern": re.compile(r"脊髓麻醉|spinal anesthesia|蛛網膜下腔", re.IGNORECASE),
        "name": "Spinal anesthesia",
        "category": "區域麻醉",
        "subcategory": "脊髓麻醉",
    },
    {
        "pattern": re.compile(r"硬膜外|epidural", re.IGNORECASE),
        "name": "Epidural anesthesia",
        "category": "區域麻醉",
        "subcategory": "硬膜外麻醉",
    },
    {
        "pattern": re.compile(r"惡性高熱|malignant hyperthermia", re.IGNORECASE),
        "name": "Malignant hyperthermia",
        "category": "危急症",
        "subcategory": "麻醉併發症",
    },
    {
        "pattern": re.compile(r"局麻藥中毒|local anesthetic systemic toxicity|last", re.IGNORECASE),
        "name": "LAST",
        "category": "危急症",
        "subcategory": "局部麻醉併發症",
    },
    {
        "pattern": re.compile(r"血壓|心輸出量|血流動力學|hemodynamic|map|cardiac output", re.IGNORECASE),
        "name": "Hemodynamic stability",
        "category": "生理學",
        "subcategory": "循環生理",
    },
]


@dataclass(slots=True)
class AssetAwareDocument:
    """A normalized view of asset-aware document artifacts."""

    doc_id: str
    title: str
    manifest: dict
    markdown: str
    markdown_path: Path


@dataclass(slots=True)
class ExtractionResult:
    """Structured output for a normalized past exam document."""

    exam_name: str
    exam_year: int
    doc_id: str
    questions: list[PastExamQuestion]
    answer_map: dict[int, str]


def _slugify(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")
    return normalized or "concept"


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if not value or value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return deduped


def _clean_inline_text(value: str) -> str:
    value = re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip()
    value = re.sub(r"^[\-•·]+\s*", "", value)
    return value


class PastExamExtractionService:
    """Parse asset-aware markdown into past-exam artifacts."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir

    def run_end_to_end(
        self,
        doc_id: str,
        exam_name: str | None = None,
        exam_year: int = 0,
        repo: IPastExamRepository | None = None,
    ) -> dict:
        """Execute the full past-exam extraction flow for an ingested doc_id."""
        document = self.load_asset_document(doc_id)
        extraction = self.extract_questions(document, exam_name=exam_name, exam_year=exam_year)

        past_exam = self._build_past_exam_aggregate(document, extraction, repo)
        if repo is not None:
            repo.save_exam(past_exam)
            repo.save_questions(past_exam.id, extraction.questions)

        classified_questions, concepts = self.classify_questions(extraction.questions)
        blueprint = self.build_blueprint(classified_questions, concepts)

        past_exam.questions = classified_questions
        past_exam.total_questions = len(classified_questions)
        past_exam.is_classified = True
        if repo is not None:
            repo.save_exam(past_exam)
            repo.save_questions(past_exam.id, classified_questions)
            repo.upsert_concepts(concepts)

        return {
            "past_exam_id": past_exam.id,
            "doc_id": doc_id,
            "exam_name": past_exam.exam_name,
            "exam_year": past_exam.exam_year,
            "question_count": len(classified_questions),
            "answer_key_count": len(extraction.answer_map),
            "concept_count": len(concepts),
            "questions": classified_questions,
            "concepts": concepts,
            "blueprint": blueprint,
        }

    def load_asset_document(self, doc_id: str) -> AssetAwareDocument:
        """Load manifest + markdown produced by asset-aware for a given doc_id."""
        doc_dir = self.data_dir / doc_id
        if not doc_dir.exists():
            raise FileNotFoundError(f"找不到 doc_id 目錄: {doc_id}")

        manifest_path = doc_dir / f"{doc_id}_manifest.json"
        markdown_path = doc_dir / f"{doc_id}_full.md"
        if not manifest_path.exists():
            raise FileNotFoundError(f"找不到 manifest: {manifest_path}")
        if not markdown_path.exists():
            raise FileNotFoundError(f"找不到 markdown: {markdown_path}")

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        markdown = markdown_path.read_text(encoding="utf-8")
        return AssetAwareDocument(
            doc_id=doc_id,
            title=manifest.get("title") or manifest.get("filename") or doc_id,
            manifest=manifest,
            markdown=markdown,
            markdown_path=markdown_path,
        )

    def extract_questions(
        self,
        document: AssetAwareDocument,
        exam_name: str | None = None,
        exam_year: int = 0,
    ) -> ExtractionResult:
        """Normalize numbered questions and answer keys from a markdown artifact."""
        lines_with_pages = self._markdown_lines_with_pages(document.markdown)
        answer_heading_index = self._find_answer_heading(lines_with_pages)
        answer_region = lines_with_pages[answer_heading_index:] if answer_heading_index is not None else []
        question_region = (
            lines_with_pages[:answer_heading_index] if answer_heading_index is not None else lines_with_pages
        )
        answer_map = self._parse_answer_map(answer_region)

        questions: list[PastExamQuestion] = []
        current_number: int | None = None
        current_lines: list[str] = []
        current_pages: list[int] = []

        for line, page in question_region:
            match = QUESTION_START_RE.match(line)
            if match:
                if current_number is not None:
                    question = self._build_question(
                        question_number=current_number,
                        block_lines=current_lines,
                        block_pages=current_pages,
                        answer_map=answer_map,
                        exam_name=exam_name or document.title,
                        exam_year=exam_year,
                        doc_id=document.doc_id,
                    )
                    if question is not None:
                        questions.append(question)
                current_number = int(match.group(1))
                current_lines = [match.group(2)]
                current_pages = [page]
                continue

            if current_number is None:
                continue

            if ANSWER_HEADING_RE.match(line):
                break

            current_lines.append(line)
            current_pages.append(page)

        if current_number is not None:
            question = self._build_question(
                question_number=current_number,
                block_lines=current_lines,
                block_pages=current_pages,
                answer_map=answer_map,
                exam_name=exam_name or document.title,
                exam_year=exam_year,
                doc_id=document.doc_id,
            )
            if question is not None:
                questions.append(question)

        return ExtractionResult(
            exam_name=exam_name or document.title,
            exam_year=exam_year,
            doc_id=document.doc_id,
            questions=questions,
            answer_map=answer_map,
        )

    def classify_questions(
        self,
        questions: list[PastExamQuestion],
    ) -> tuple[list[PastExamQuestion], list[Concept]]:
        """Derive concept, pattern and difficulty tags from normalized questions."""
        concepts_by_name: dict[str, Concept] = {}

        for question in questions:
            combined_text = " ".join([question.question_text, *question.options, question.explanation]).strip()
            pattern = self._detect_pattern(combined_text)
            matched_concepts = self._detect_concepts(combined_text)
            if not matched_concepts:
                matched_concepts = self._fallback_concepts(combined_text)

            for concept in matched_concepts:
                concepts_by_name.setdefault(concept.name, concept)

            question.pattern = pattern
            question.concept_names = [concept.name for concept in matched_concepts]
            question.concepts = [concept.id for concept in matched_concepts]
            question.topics = _dedupe_preserve_order(
                [concept.category for concept in matched_concepts]
                + [concept.subcategory for concept in matched_concepts if concept.subcategory]
                + question.concept_names
            )
            question.difficulty = self._detect_difficulty(question, pattern, matched_concepts)
            question.bloom_level = self._detect_bloom_level(pattern, question.difficulty)

        return questions, list(concepts_by_name.values())

    def build_blueprint(self, questions: list[PastExamQuestion], concepts: list[Concept]) -> dict:
        """Aggregate extracted questions into a reusable reference blueprint."""
        pattern_counts = Counter(question.pattern.value for question in questions)
        difficulty_counts = Counter(question.difficulty for question in questions)
        concept_counts = Counter(name for question in questions for name in question.concept_names)
        topic_counts = Counter(topic for question in questions for topic in question.topics)
        year_counts = Counter(question.exam_year for question in questions if question.exam_year)

        top_patterns = [name for name, _count in pattern_counts.most_common(3)]
        top_concepts = [{"name": name, "count": count} for name, count in concept_counts.most_common(10)]

        recommended_rules = [
            "先沿用高頻概念，但避免直接重寫同一題幹。",
            "若考古題以 negation 或 comparison 為主，新增題目時應改寫成正向判斷或臨床應用題。",
        ]
        if top_patterns:
            recommended_rules.append(f"優先保留高頻題型骨架：{', '.join(top_patterns)}。")

        return {
            "question_count": len(questions),
            "concept_count": len(concepts),
            "pattern_distribution": dict(pattern_counts),
            "difficulty_distribution": dict(difficulty_counts),
            "topic_distribution": dict(topic_counts.most_common(15)),
            "year_distribution": dict(year_counts),
            "high_frequency_concepts": top_concepts,
            "recommended_generation_rules": recommended_rules,
            "sample_questions": [
                {
                    "question_number": question.question_number,
                    "pattern": question.pattern.value,
                    "concept_names": question.concept_names,
                    "difficulty": question.difficulty,
                }
                for question in questions[:5]
            ],
        }

    def _build_past_exam_aggregate(
        self,
        document: AssetAwareDocument,
        extraction: ExtractionResult,
        repo: IPastExamRepository | None,
    ) -> PastExam:
        existing_exam = repo.get_exam_by_doc_id(document.doc_id) if repo is not None else None
        return PastExam(
            id=existing_exam.id if existing_exam is not None else PastExam().id,
            exam_year=extraction.exam_year,
            exam_name=extraction.exam_name,
            total_questions=len(extraction.questions),
            questions=extraction.questions,
            source_pdf=document.manifest.get("filename", ""),
            source_doc_id=document.doc_id,
            imported_at=existing_exam.imported_at if existing_exam is not None else datetime.now(),
            imported_by=existing_exam.imported_by if existing_exam is not None else "agent",
            is_ocr_done=True,
            is_parsed=True,
            is_classified=False,
        )

    def _markdown_lines_with_pages(self, markdown: str) -> list[tuple[str, int]]:
        current_page = 1
        lines_with_pages: list[tuple[str, int]] = []
        for raw_line in markdown.splitlines():
            page_match = PAGE_MARKER_RE.match(raw_line)
            if page_match:
                current_page = int(page_match.group(1))
                continue
            lines_with_pages.append((raw_line.rstrip(), current_page))
        return lines_with_pages

    def _find_answer_heading(self, lines_with_pages: list[tuple[str, int]]) -> int | None:
        for index, (line, _page) in enumerate(lines_with_pages):
            if ANSWER_HEADING_RE.match(line):
                return index
        return None

    def _parse_answer_map(self, answer_region: list[tuple[str, int]]) -> dict[int, str]:
        answer_map: dict[int, str] = {}
        for line, _page in answer_region:
            for number_text, answer_text in ANSWER_PAIR_RE.findall(line):
                answer_map[int(number_text)] = answer_text.upper()
        return answer_map

    def _build_question(
        self,
        question_number: int,
        block_lines: list[str],
        block_pages: list[int],
        answer_map: dict[int, str],
        exam_name: str,
        exam_year: int,
        doc_id: str,
    ) -> PastExamQuestion | None:
        filtered_lines = [line.strip() for line in block_lines if line.strip() and not line.strip().startswith("Page ")]
        if not filtered_lines:
            return None

        block_text = "\n".join(filtered_lines)
        inline_answer = INLINE_ANSWER_RE.search(block_text)
        explanation_match = EXPLANATION_RE.search(block_text)
        explanation = explanation_match.group(1).strip() if explanation_match else ""

        cleaned_block = []
        for line in filtered_lines:
            if ANSWER_HEADING_RE.match(line):
                continue
            if INLINE_ANSWER_RE.search(line) or EXPLANATION_RE.search(line):
                continue
            cleaned_block.append(line)

        stem, options = self._extract_stem_and_options(" ".join(cleaned_block))
        if not stem or len(options) < 2:
            return None

        return PastExamQuestion(
            id=f"{doc_id}__q{question_number:03d}",
            exam_year=exam_year,
            exam_name=exam_name,
            question_number=question_number,
            question_text=stem,
            options=options,
            correct_answer=(inline_answer.group(1).upper() if inline_answer else answer_map.get(question_number, "")),
            explanation=explanation,
            source_doc_id=doc_id,
            source_page=block_pages[0] if block_pages else None,
            raw_text=block_text,
        )

    def _extract_stem_and_options(self, block_text: str) -> tuple[str, list[str]]:
        block_text = _clean_inline_text(block_text)
        first_option = OPTION_START_RE.search(block_text)
        if not first_option:
            return block_text, []

        stem = _clean_inline_text(block_text[: first_option.start()])
        options_text = block_text[first_option.start() :]
        options = [_clean_inline_text(match.group(2)) for match in OPTION_RE.finditer(options_text)]
        return stem, options

    def _detect_pattern(self, combined_text: str) -> QuestionPattern:
        text = combined_text.lower()
        if any(keyword in text for keyword in ["何者不", "下列何者非", "錯誤", "not correct", "except"]):
            return QuestionPattern.NEGATION
        if any(keyword in text for keyword in ["病例", "患者", "個案", "病人", "history", "undergo", "gastroscopy"]):
            return QuestionPattern.CLINICAL_SCENARIO
        if any(keyword in text for keyword in ["比較", "相較", "差異", "compared", "versus", "vs."]):
            return QuestionPattern.COMPARISON
        if any(keyword in text for keyword in ["機轉", "作用機轉", "受體", "mechanism", "receptor"]):
            return QuestionPattern.MECHANISM
        if any(keyword in text for keyword in ["劑量", "計算", "ml/kg", "mg/kg", "calculate"]):
            return QuestionPattern.CALCULATION
        if any(keyword in text for keyword in ["圖", "影像", "心電圖", "ecg", "x-ray", "ultrasound"]):
            return QuestionPattern.IMAGE_BASED
        if any(keyword in text for keyword in ["最佳", "最適當", "best answer", "most appropriate"]):
            return QuestionPattern.BEST_ANSWER
        if any(keyword in text for keyword in ["順序", "步驟", "先後", "sequence"]):
            return QuestionPattern.SEQUENCE
        return QuestionPattern.DIRECT_RECALL

    def _detect_concepts(self, combined_text: str) -> list[Concept]:
        concepts: list[Concept] = []
        for rule in CONCEPT_RULES:
            if rule["pattern"].search(combined_text):
                concepts.append(
                    Concept(
                        id=f"concept_{_slugify(rule['name'])}",
                        name=rule["name"],
                        category=rule["category"],
                        subcategory=rule["subcategory"],
                        keywords=[rule["name"]],
                    )
                )
        return concepts

    def _fallback_concepts(self, combined_text: str) -> list[Concept]:
        tokens = []
        for token in re.findall(r"\b[A-Za-z][A-Za-z\-]{3,}\b", combined_text):
            normalized = token.lower()
            if normalized in ENGLISH_STOPWORDS:
                continue
            tokens.append(token.title())
        concepts = []
        for token in _dedupe_preserve_order(tokens)[:2]:
            concepts.append(
                Concept(
                    id=f"concept_{_slugify(token)}",
                    name=token,
                    category="未分類",
                    subcategory="候選概念",
                    keywords=[token],
                )
            )
        return concepts

    def _detect_difficulty(
        self,
        question: PastExamQuestion,
        pattern: QuestionPattern,
        concepts: list[Concept],
    ) -> str:
        concept_count = len(concepts)
        stem_length = len(question.question_text)
        if pattern in {QuestionPattern.CLINICAL_SCENARIO, QuestionPattern.CALCULATION, QuestionPattern.SEQUENCE}:
            return "hard"
        if pattern in {QuestionPattern.COMPARISON, QuestionPattern.NEGATION, QuestionPattern.BEST_ANSWER}:
            return "hard" if concept_count >= 2 else "medium"
        if pattern == QuestionPattern.MECHANISM:
            return "medium" if stem_length < 90 else "hard"
        if concept_count <= 1 and stem_length < 60:
            return "easy"
        return "medium"

    def _detect_bloom_level(self, pattern: QuestionPattern, difficulty: str) -> int:
        if pattern in {QuestionPattern.CLINICAL_SCENARIO, QuestionPattern.SEQUENCE, QuestionPattern.CALCULATION}:
            return 4
        if difficulty == "hard":
            return 3
        if difficulty == "medium":
            return 2
        return 1
