"""
Exam Entity - 考卷實體

定義考卷結構，包含多個考題的組合和配置。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import uuid
import json
from pathlib import Path

from .question import Question, Difficulty


class ExamStatus(str, Enum):
    """考卷狀態"""
    DRAFT = "draft"           # 草稿
    GENERATING = "generating" # 生成中
    READY = "ready"           # 可用
    ARCHIVED = "archived"     # 已封存


@dataclass
class ExamConfig:
    """考卷配置"""
    total_questions: int = 80           # 總題數
    single_choice_count: int = 60       # 單選題數
    multiple_choice_count: int = 20     # 多選題數
    time_limit_minutes: int = 0         # 時間限制 (0=不限)
    passing_score: int = 60             # 及格分數
    difficulty_distribution: dict = field(default_factory=lambda: {
        "easy": 0.3,
        "medium": 0.5,
        "hard": 0.2,
    })
    topic_scope: list[str] = field(default_factory=list)  # 範圍限定


@dataclass
class Exam:
    """
    考卷實體
    
    包含多個考題的集合，支援配置和序列化。
    """
    
    # 識別
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    name: str = ""
    description: str = ""
    
    # 題目
    questions: list[Question] = field(default_factory=list)
    
    # 配置
    config: ExamConfig = field(default_factory=ExamConfig)
    status: ExamStatus = ExamStatus.DRAFT
    
    # 元數據
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)
    created_by: str = "agent"
    
    @property
    def total_points(self) -> int:
        """總分"""
        return sum(q.points for q in self.questions)
    
    @property
    def question_count(self) -> int:
        """題數"""
        return len(self.questions)
    
    @property
    def difficulty_stats(self) -> dict[str, int]:
        """難度統計"""
        stats = {d.value: 0 for d in Difficulty}
        for q in self.questions:
            stats[q.difficulty.value] += 1
        return stats
    
    def add_question(self, question: Question) -> None:
        """新增題目"""
        self.questions.append(question)
        self.updated_at = datetime.now()
    
    def remove_question(self, question_id: str) -> bool:
        """移除題目"""
        for i, q in enumerate(self.questions):
            if q.id == question_id:
                self.questions.pop(i)
                self.updated_at = datetime.now()
                return True
        return False
    
    def to_dict(self) -> dict:
        """轉換為字典格式"""
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "questions": [q.to_dict() for q in self.questions],
            "config": {
                "total_questions": self.config.total_questions,
                "single_choice_count": self.config.single_choice_count,
                "multiple_choice_count": self.config.multiple_choice_count,
                "time_limit_minutes": self.config.time_limit_minutes,
                "passing_score": self.config.passing_score,
                "difficulty_distribution": self.config.difficulty_distribution,
                "topic_scope": self.config.topic_scope,
            },
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            "created_by": self.created_by,
            "total_points": self.total_points,
            "question_count": self.question_count,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "Exam":
        """從字典建立實體"""
        config_data = data.get("config", {})
        config = ExamConfig(
            total_questions=config_data.get("total_questions", 80),
            single_choice_count=config_data.get("single_choice_count", 60),
            multiple_choice_count=config_data.get("multiple_choice_count", 20),
            time_limit_minutes=config_data.get("time_limit_minutes", 0),
            passing_score=config_data.get("passing_score", 60),
            difficulty_distribution=config_data.get(
                "difficulty_distribution",
                {"easy": 0.3, "medium": 0.5, "hard": 0.2}
            ),
            topic_scope=config_data.get("topic_scope", []),
        )
        
        questions = [
            Question.from_dict(q) for q in data.get("questions", [])
        ]
        
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            name=data.get("name", ""),
            description=data.get("description", ""),
            questions=questions,
            config=config,
            status=ExamStatus(data.get("status", "draft")),
            created_by=data.get("created_by", "agent"),
        )
    
    def save_to_file(self, path: Path) -> None:
        """儲存到檔案"""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
    
    @classmethod
    def load_from_file(cls, path: Path) -> "Exam":
        """從檔案載入"""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls.from_dict(data)
    
    def generate_summary(self) -> str:
        """生成考卷摘要"""
        lines = [
            f"# {self.name or '未命名考卷'}",
            "",
            f"- **題數:** {self.question_count}",
            f"- **總分:** {self.total_points}",
            f"- **狀態:** {self.status.value}",
            "",
            "## 難度分布",
        ]
        
        for diff, count in self.difficulty_stats.items():
            if count > 0:
                lines.append(f"- {diff}: {count} 題")
        
        return "\n".join(lines)
