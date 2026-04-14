"""
Past Exam Entity - 考古題實體

定義歷年考古題的結構，支援年份追蹤、概念萃取和出題頻率分析。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ExamYear(str, Enum):
    """考試年度格式：民國年或西元年"""

    pass  # 使用 str 自由輸入


class QuestionPattern(str, Enum):
    """出題模式/題型模式"""

    DIRECT_RECALL = "direct_recall"  # 直接記憶題：「下列何者正確」
    CLINICAL_SCENARIO = "clinical_scenario"  # 臨床情境題：病例描述後提問
    COMPARISON = "comparison"  # 比較題：藥物/技術比較
    MECHANISM = "mechanism"  # 機轉題：病理/藥理機轉
    CALCULATION = "calculation"  # 計算題：劑量/參數計算
    IMAGE_BASED = "image_based"  # 圖片題：心電圖/影像判讀
    BEST_ANSWER = "best_answer"  # 最佳答案題：多個對但選最佳
    NEGATION = "negation"  # 否定題：「下列何者不正確」
    SEQUENCE = "sequence"  # 順序題：處理步驟排序


@dataclass
class Concept:
    """
    知識概念

    代表一個可出題的知識點，支援層級分類。
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    name: str = ""  # 概念名稱 (如 "Propofol 藥理")
    category: str = ""  # 大分類 (如 "藥理學")
    subcategory: str = ""  # 小分類 (如 "靜脈麻醉劑")
    keywords: list[str] = field(default_factory=list)  # 關鍵字 (如 ["GABA", "脂質乳劑"])
    related_concepts: list[str] = field(default_factory=list)  # 相關概念 ID

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "subcategory": self.subcategory,
            "keywords": self.keywords,
            "related_concepts": self.related_concepts,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Concept":
        return cls(
            id=data.get("id", str(uuid.uuid4())[:8]),
            name=data.get("name", ""),
            category=data.get("category", ""),
            subcategory=data.get("subcategory", ""),
            keywords=data.get("keywords", []),
            related_concepts=data.get("related_concepts", []),
        )


@dataclass
class PastExamQuestion:
    """
    考古題中的單一題目

    比一般 Question 多了：年份、題號、出題模式、概念標記。
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))

    # 關聯資訊
    past_exam_id: Optional[str] = None

    # 來源資訊
    exam_year: int = 0  # 考試年度 (如 2024 或 113)
    exam_name: str = ""  # 考試名稱 (如 "麻醉專科醫師考試")
    question_number: int = 0  # 原始題號

    # 題目內容
    question_text: str = ""
    options: list[str] = field(default_factory=list)
    correct_answer: str = ""
    explanation: str = ""

    # 分類標記 (萃取重點)
    concepts: list[str] = field(default_factory=list)  # 概念 ID 列表
    concept_names: list[str] = field(default_factory=list)  # 概念名稱 (方便顯示)
    pattern: QuestionPattern = QuestionPattern.DIRECT_RECALL  # 出題模式
    difficulty: str = "medium"
    bloom_level: int = 1  # Bloom 認知層次 (1-6)
    topics: list[str] = field(default_factory=list)  # 知識點標籤

    # 元數據
    created_at: datetime = field(default_factory=datetime.now)
    source_doc_id: Optional[str] = None  # asset-aware doc_id (OCR 後)
    source_page: Optional[int] = None  # 原始 PDF 頁碼
    raw_text: str = ""  # OCR 原始文字 (用於比對)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "past_exam_id": self.past_exam_id,
            "exam_year": self.exam_year,
            "exam_name": self.exam_name,
            "question_number": self.question_number,
            "question_text": self.question_text,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "concepts": self.concepts,
            "concept_names": self.concept_names,
            "pattern": self.pattern.value,
            "difficulty": self.difficulty,
            "bloom_level": self.bloom_level,
            "topics": self.topics,
            "created_at": self.created_at.isoformat() if isinstance(self.created_at, datetime) else self.created_at,
            "source_doc_id": self.source_doc_id,
            "source_page": self.source_page,
            "raw_text": self.raw_text,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PastExamQuestion":
        pattern = data.get("pattern", "direct_recall")
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            past_exam_id=data.get("past_exam_id"),
            exam_year=data.get("exam_year", 0),
            exam_name=data.get("exam_name", ""),
            question_number=data.get("question_number", 0),
            question_text=data.get("question_text", ""),
            options=data.get("options", []),
            correct_answer=data.get("correct_answer", ""),
            explanation=data.get("explanation", ""),
            concepts=data.get("concepts", []),
            concept_names=data.get("concept_names", []),
            pattern=QuestionPattern(pattern)
            if pattern in [p.value for p in QuestionPattern]
            else QuestionPattern.DIRECT_RECALL,
            difficulty=data.get("difficulty", "medium"),
            bloom_level=data.get("bloom_level", 1),
            topics=data.get("topics", []),
            source_doc_id=data.get("source_doc_id"),
            source_page=data.get("source_page"),
            raw_text=data.get("raw_text", ""),
        )


@dataclass
class PastExam:
    """
    一份完整的歷年考卷

    包含年度、考試類別和所有題目。
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4())[:12])
    exam_year: int = 0
    exam_name: str = ""
    total_questions: int = 0
    questions: list[PastExamQuestion] = field(default_factory=list)

    # 匯入資訊
    source_pdf: str = ""  # 原始 PDF 檔名
    source_doc_id: Optional[str] = None  # asset-aware doc_id
    imported_at: datetime = field(default_factory=datetime.now)
    imported_by: str = "agent"

    # 萃取狀態
    is_ocr_done: bool = False
    is_parsed: bool = False  # 題目已提取
    is_classified: bool = False  # 概念已分類

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "exam_year": self.exam_year,
            "exam_name": self.exam_name,
            "total_questions": self.total_questions,
            "questions": [q.to_dict() for q in self.questions],
            "source_pdf": self.source_pdf,
            "source_doc_id": self.source_doc_id,
            "imported_at": self.imported_at.isoformat() if isinstance(self.imported_at, datetime) else self.imported_at,
            "imported_by": self.imported_by,
            "is_ocr_done": self.is_ocr_done,
            "is_parsed": self.is_parsed,
            "is_classified": self.is_classified,
        }
