"""
Audit Value Objects - 審計追蹤值物件

記錄題目的完整生命週期：誰建立、如何修改、來源依據。
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional
import json


class AuditAction(str, Enum):
    """審計動作類型"""
    CREATED = "created"           # 題目建立
    UPDATED = "updated"           # 題目修改
    VALIDATED = "validated"       # 驗證通過
    REJECTED = "rejected"         # 驗證失敗
    DELETED = "deleted"           # 題目刪除
    RESTORED = "restored"         # 題目還原
    SOURCE_VERIFIED = "source_verified"  # 來源已驗證


class ActorType(str, Enum):
    """操作者類型"""
    AGENT = "agent"               # AI Agent (Crush)
    SKILL = "skill"               # Claude Skill
    USER = "user"                 # 人工操作
    SYSTEM = "system"             # 系統自動


@dataclass
class AuditEntry:
    """
    單筆審計記錄
    
    記錄每一次對題目的操作，形成完整的追蹤鏈。
    """
    
    id: str                                # 審計記錄 ID
    question_id: str                       # 關聯的題目 ID
    action: AuditAction                    # 動作類型
    actor_type: ActorType                  # 操作者類型
    actor_name: str                        # 操作者名稱 (skill 名稱、agent 名稱)
    
    # 變更內容
    changes: Optional[dict] = None         # 變更的欄位 {"field": {"old": x, "new": y}}
    reason: Optional[str] = None           # 變更原因
    
    # 生成依據 (僅 CREATED 動作)
    generation_context: Optional[dict] = None  # 生成上下文
    # {
    #   "prompt": "用戶的原始請求",
    #   "source_documents": ["doc1.pdf", "doc2.pdf"],
    #   "skill_used": "mcq-generator",
    #   "temperature": 0.7,
    #   "model": "claude-3.5-sonnet"
    # }
    
    # 時間戳
    timestamp: datetime = field(default_factory=datetime.now)
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "id": self.id,
            "question_id": self.question_id,
            "action": self.action.value,
            "actor_type": self.actor_type.value,
            "actor_name": self.actor_name,
            "changes": self.changes,
            "reason": self.reason,
            "generation_context": self.generation_context,
            "timestamp": self.timestamp.isoformat(),
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> "AuditEntry":
        """從字典建立"""
        return cls(
            id=data["id"],
            question_id=data["question_id"],
            action=AuditAction(data["action"]),
            actor_type=ActorType(data["actor_type"]),
            actor_name=data["actor_name"],
            changes=data.get("changes"),
            reason=data.get("reason"),
            generation_context=data.get("generation_context"),
            timestamp=datetime.fromisoformat(data["timestamp"]) 
                      if isinstance(data.get("timestamp"), str) 
                      else data.get("timestamp", datetime.now()),
        )
    
    def to_json(self) -> str:
        """序列化為 JSON"""
        return json.dumps(self.to_dict(), ensure_ascii=False, default=str)


@dataclass
class GenerationContext:
    """
    題目生成上下文
    
    詳細記錄題目是如何被產生的，供追蹤和重現。
    """
    
    # 用戶請求
    user_prompt: str                       # 原始提示
    
    # 來源材料
    source_documents: list[str] = field(default_factory=list)  # 參考教材
    source_pages: Optional[str] = None     # 參考頁碼
    source_text: Optional[str] = None      # 參考原文 (截取)
    
    # 生成配置
    skill_used: str = "mcq-generator"      # 使用的 Skill
    model: str = "claude-3.5-sonnet"       # 使用的模型
    temperature: float = 0.7               # 溫度參數
    
    # AI 推理
    reasoning: Optional[str] = None        # AI 的推理過程
    
    # 驗證
    validation_passed: bool = False        # 是否通過驗證
    validation_notes: Optional[str] = None # 驗證備註
    
    def to_dict(self) -> dict:
        """轉換為字典"""
        return {
            "user_prompt": self.user_prompt,
            "source_documents": self.source_documents,
            "source_pages": self.source_pages,
            "source_text": self.source_text,
            "skill_used": self.skill_used,
            "model": self.model,
            "temperature": self.temperature,
            "reasoning": self.reasoning,
            "validation_passed": self.validation_passed,
            "validation_notes": self.validation_notes,
        }
