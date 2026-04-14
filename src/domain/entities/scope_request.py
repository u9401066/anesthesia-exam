"""
Scope Request Entity - 出題需求實體

使用者可提交希望增加出題範圍的需求，
後台 heartbeat agent 會讀取待處理需求並自動補題。
"""

import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class ScopeRequestStatus(str, Enum):
    """需求狀態"""

    PENDING = "pending"  # 待處理
    APPROVED = "approved"  # 已核准（等待補題）
    IN_PROGRESS = "in_progress"  # 補題中
    FULFILLED = "fulfilled"  # 已完成
    REJECTED = "rejected"  # 已駁回


@dataclass
class ScopeRequest:
    """
    出題需求

    使用者或管理者可以提交一筆「希望增補題目」的需求，
    指定主題、章節、難度、考試類型和目標題數。
    """

    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    topic: str = ""  # 主題 / 知識點
    chapter: Optional[str] = None  # 章節範圍
    difficulty: Optional[str] = None  # 期望難度
    exam_track: Optional[str] = None  # 考試類型
    reason: str = ""  # 需求原因
    requested_by: str = "user"  # 提出者
    status: ScopeRequestStatus = ScopeRequestStatus.PENDING
    target_count: int = 5  # 目標題數
    fulfilled_count: int = 0  # 已完成題數
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: Optional[datetime] = None
    fulfilled_at: Optional[datetime] = None
    admin_notes: Optional[str] = None  # 管理者備註

    @property
    def is_complete(self) -> bool:
        return self.fulfilled_count >= self.target_count

    @property
    def progress_pct(self) -> float:
        if self.target_count <= 0:
            return 100.0
        return min(100.0, (self.fulfilled_count / self.target_count) * 100)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "topic": self.topic,
            "chapter": self.chapter,
            "difficulty": self.difficulty,
            "exam_track": self.exam_track,
            "reason": self.reason,
            "requested_by": self.requested_by,
            "status": self.status.value,
            "target_count": self.target_count,
            "fulfilled_count": self.fulfilled_count,
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "fulfilled_at": self.fulfilled_at.isoformat() if self.fulfilled_at else None,
            "admin_notes": self.admin_notes,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ScopeRequest":
        return cls(
            id=data.get("id", str(uuid.uuid4())),
            topic=data.get("topic", ""),
            chapter=data.get("chapter"),
            difficulty=data.get("difficulty"),
            exam_track=data.get("exam_track"),
            reason=data.get("reason", ""),
            requested_by=data.get("requested_by", "user"),
            status=ScopeRequestStatus(data.get("status", "pending")),
            target_count=data.get("target_count", 5),
            fulfilled_count=data.get("fulfilled_count", 0),
            created_at=datetime.fromisoformat(data["created_at"]) if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"]) if data.get("updated_at") else None,
            fulfilled_at=datetime.fromisoformat(data["fulfilled_at"]) if data.get("fulfilled_at") else None,
            admin_notes=data.get("admin_notes"),
        )
