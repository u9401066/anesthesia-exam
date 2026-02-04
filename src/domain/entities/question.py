"""
Question Entity - 考題實體

定義單一考題的結構，包含題目、選項、答案、詳解和來源追蹤。
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional
from datetime import datetime
import uuid


class QuestionType(str, Enum):
    """題型枚舉"""
    SINGLE_CHOICE = "single_choice"      # 單選題
    MULTIPLE_CHOICE = "multiple_choice"  # 多選題
    TRUE_FALSE = "true_false"            # 是非題
    FILL_IN_BLANK = "fill_in_blank"      # 填空題
    SHORT_ANSWER = "short_answer"        # 簡答題
    ESSAY = "essay"                      # 問答題
    IMAGE_BASED = "image_based"          # 圖片題


class Difficulty(str, Enum):
    """難度枚舉"""
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


@dataclass
class SourceLocation:
    """
    精確來源位置
    
    支援多層級來源追蹤：
    - 題幹來源（整題概念來自哪裡）
    - 正確選項來源（正確答案的依據）
    - 詳解來源（解釋的參考）
    """
    page: int                            # 頁碼 (1-based)
    line_start: int                      # 起始行號 (1-based)
    line_end: int                        # 結束行號 (1-based)
    bbox: Optional[tuple[float, float, float, float]] = None  # 位置 (x0, y0, x1, y1)
    original_text: str = ""              # 原文引用
    
    def to_dict(self) -> dict:
        return {
            "page": self.page,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "bbox": list(self.bbox) if self.bbox else None,
            "original_text": self.original_text,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "SourceLocation":
        return cls(
            page=data.get("page", 0),
            line_start=data.get("line_start", 0),
            line_end=data.get("line_end", 0),
            bbox=tuple(data["bbox"]) if data.get("bbox") else None,
            original_text=data.get("original_text", ""),
        )


@dataclass
class Source:
    """
    來源追蹤 - 支援精確的教材引用
    
    設計理念：
    - document: 教材名稱（如 "Miller's Anesthesia 9th"）
    - chapter: 章節編號（如 "Ch.15"）
    - section: 小節標題（如 "Pharmacokinetics"）
    - stem_source: 題幹概念來源（主要知識點）
    - answer_source: 正確選項來源（答案依據）
    - explanation_sources: 詳解參考來源（可多個）
    
    ⚠️ 重要：這些欄位必須由 PDF 解析工具填充，不可 AI 編造！
    """
    document: str                        # 教材名稱
    chapter: Optional[str] = None        # 章節編號
    section: Optional[str] = None        # 小節標題
    
    # 精確來源位置
    stem_source: Optional[SourceLocation] = None    # 題幹概念來源
    answer_source: Optional[SourceLocation] = None  # 正確選項來源
    explanation_sources: list["SourceLocation"] = field(default_factory=list)  # 詳解參考
    
    # 圖片來源（如果是圖片題）
    figure_id: Optional[str] = None      # 圖片 ID
    figure_caption: Optional[str] = None # 圖說
    figure_page: Optional[int] = None    # 圖片所在頁碼
    
    # 舊版相容欄位（已棄用，保留向後相容）
    page: Optional[int] = None           # [DEPRECATED] 使用 stem_source.page
    lines: Optional[str] = None          # [DEPRECATED] 使用 stem_source.line_start/end
    original_text: Optional[str] = None  # [DEPRECATED] 使用 stem_source.original_text
    
    # 來源驗證狀態
    is_verified: bool = False            # 是否經過人工驗證
    pdf_hash: Optional[str] = None       # PDF 檔案 hash（確保來源一致性）
    
    def to_dict(self) -> dict:
        return {
            "document": self.document,
            "chapter": self.chapter,
            "section": self.section,
            "stem_source": self.stem_source.to_dict() if self.stem_source else None,
            "answer_source": self.answer_source.to_dict() if self.answer_source else None,
            "explanation_sources": [s.to_dict() for s in self.explanation_sources],
            "figure_id": self.figure_id,
            "figure_caption": self.figure_caption,
            "figure_page": self.figure_page,
            "is_verified": self.is_verified,
            "pdf_hash": self.pdf_hash,
            # 向後相容
            "page": self.page or (self.stem_source.page if self.stem_source else None),
            "lines": self.lines or (
                f"{self.stem_source.line_start}-{self.stem_source.line_end}" 
                if self.stem_source else None
            ),
            "original_text": self.original_text or (
                self.stem_source.original_text if self.stem_source else None
            ),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Source":
        stem = None
        if data.get("stem_source"):
            stem = SourceLocation.from_dict(data["stem_source"])
        
        answer = None
        if data.get("answer_source"):
            answer = SourceLocation.from_dict(data["answer_source"])
        
        explanations = [
            SourceLocation.from_dict(s) 
            for s in data.get("explanation_sources", [])
        ]
        
        return cls(
            document=data.get("document", ""),
            chapter=data.get("chapter"),
            section=data.get("section"),
            stem_source=stem,
            answer_source=answer,
            explanation_sources=explanations,
            figure_id=data.get("figure_id"),
            figure_caption=data.get("figure_caption"),
            figure_page=data.get("figure_page"),
            is_verified=data.get("is_verified", False),
            pdf_hash=data.get("pdf_hash"),
            # 向後相容
            page=data.get("page"),
            lines=data.get("lines"),
            original_text=data.get("original_text"),
        )


@dataclass
class Question:
    """
    考題實體
    
    核心不變量：
    - 單選題必須有且只有一個正確答案
    - 多選題至少有一個正確答案
    - 每題必須有題目文字
    """
    
    # 識別
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    # 內容
    question_text: str = ""               # 題目
    options: list[str] = field(default_factory=list)  # 選項 (A, B, C, D...)
    correct_answer: str = ""              # 正確答案
    
    # 詳解
    explanation: str = ""                 # 解題思路
    source: Optional[Source] = None       # 來源追蹤
    
    # 分類
    question_type: QuestionType = QuestionType.SINGLE_CHOICE
    difficulty: Difficulty = Difficulty.MEDIUM
    topics: list[str] = field(default_factory=list)  # 知識點標籤
    
    # 配置
    points: int = 1                       # 配分
    image_path: Optional[str] = None      # 圖片路徑
    
    # 元數據
    created_at: datetime = field(default_factory=datetime.now)
    created_by: str = "agent"             # 生成者
    
    def to_dict(self) -> dict:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "question_text": self.question_text,
            "options": self.options,
            "correct_answer": self.correct_answer,
            "explanation": self.explanation,
            "source": {
                "document": self.source.document,
                "page": self.source.page,
                "lines": self.source.lines,
                "original_text": self.source.original_text,
            } if self.source else None,
            "question_type": self.question_type.value,
            "difficulty": self.difficulty.value,
            "topics": self.topics,
            "points": self.points,
            "image_path": self.image_path,
            "created_at": self.created_at.isoformat(),
            "created_by": self.created_by,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Question":
        """從字典建立實體"""
        source = None
        if data.get("source"):
            source = Source(
                document=data["source"].get("document", ""),
                page=data["source"].get("page"),
                lines=data["source"].get("lines"),
                original_text=data["source"].get("original_text"),
            )
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            question_text=data.get("question_text", data.get("question", "")),
            options=data.get("options", []),
            correct_answer=data.get("correct_answer", data.get("answer", "")),
            explanation=data.get("explanation", ""),
            source=source,
            question_type=QuestionType(data.get("question_type", "single_choice")),
            difficulty=Difficulty(data.get("difficulty", "medium")),
            topics=data.get("topics", []),
            points=data.get("points", 1),
            image_path=data.get("image_path"),
            created_by=data.get("created_by", "agent"),
        )
    
    def format_display(self) -> str:
        """格式化顯示用"""
        lines = [f"**{self.question_text}**", ""]
        
        for i, opt in enumerate(self.options):
            prefix = chr(65 + i)  # A, B, C, D...
            lines.append(f"{prefix}. {opt}")
        
        return "\n".join(lines)
    
    def format_with_answer(self) -> str:
        """格式化顯示（含答案）"""
        display = self.format_display()
        display += f"\n\n**答案:** {self.correct_answer}"
        
        if self.explanation:
            display += f"\n\n**解析:** {self.explanation}"
        
        if self.source:
            display += f"\n\n**來源:** {self.source.document}"
            if self.source.chapter:
                display += f" ({self.source.chapter}"
                if self.source.section:
                    display += f" - {self.source.section}"
                display += ")"
            
            # 顯示精確來源
            if self.source.stem_source:
                src = self.source.stem_source
                display += f"\n  - 題幹: P.{src.page}, 第 {src.line_start}-{src.line_end} 行"
                if src.original_text:
                    text = src.original_text[:100] + "..." if len(src.original_text) > 100 else src.original_text
                    display += f"\n    > \"{text}\""
            
            if self.source.answer_source:
                src = self.source.answer_source
                display += f"\n  - 答案依據: P.{src.page}, 第 {src.line_start}-{src.line_end} 行"
            
            # 向後相容舊格式
            elif self.source.page:
                display += f" (P.{self.source.page}"
                if self.source.lines:
                    display += f", 第 {self.source.lines} 行"
                display += ")"
        
        return display
