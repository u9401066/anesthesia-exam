"""Conversation Entity - 對話管理"""

from datetime import datetime
from typing import List, Optional
from pydantic import BaseModel, Field
import uuid

from .message import Message, MessageRole


class Conversation(BaseModel):
    """對話實體 - 管理一系列訊息"""
    
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    title: str = "New Conversation"
    messages: List[Message] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    
    def add_message(self, role: MessageRole, content: str, **kwargs) -> Message:
        """新增訊息到對話"""
        message = Message(role=role, content=content, **kwargs)
        self.messages.append(message)
        self.updated_at = datetime.now()
        return message
    
    def get_messages_for_context(self, max_messages: int = 20) -> List[Message]:
        """取得用於上下文的訊息（最近 N 則）"""
        return self.messages[-max_messages:]
    
    def to_prompt_format(self) -> List[dict]:
        """轉換為 LLM prompt 格式"""
        return [
            {"role": msg.role.value, "content": msg.content}
            for msg in self.messages
        ]
    
    @property
    def message_count(self) -> int:
        return len(self.messages)
    
    @property
    def last_message(self) -> Optional[Message]:
        return self.messages[-1] if self.messages else None
