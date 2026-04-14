"""Message Entity - 對話訊息"""

import uuid
from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class MessageRole(str, Enum):
    """訊息角色"""

    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class Message(BaseModel):
    """對話訊息實體"""

    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    role: MessageRole
    content: str
    timestamp: datetime = Field(default_factory=datetime.now)

    # 可選的元數據
    model: Optional[str] = None
    tokens_used: Optional[int] = None

    class Config:
        frozen = True  # Immutable
