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
class Source:
    """來源追蹤"""
    document: str                        # 教材名稱
    page: Optional[int] = None           # 頁碼
    lines: Optional[str] = None          # 行號範圍 (如 "15-23")
    original_text: Optional[str] = None  # 原文引用
    figure_caption: Optional[str] = None # 圖說


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
            if self.source.page:
                display += f" (P.{self.source.page}"
                if self.source.lines:
                    display += f", 第 {self.source.lines} 行"
                display += ")"
        
        return display
