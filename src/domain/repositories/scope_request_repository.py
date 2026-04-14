"""
Scope Request Repository Interface - 出題需求儲存庫介面

定義出題需求的 CRUD 操作。
"""

from abc import ABC, abstractmethod
from typing import Optional

from src.domain.entities.scope_request import ScopeRequest, ScopeRequestStatus


class IScopeRequestRepository(ABC):
    """出題需求儲存庫介面"""

    @abstractmethod
    def save(self, request: ScopeRequest) -> str:
        """儲存需求，回傳 ID"""
        pass

    @abstractmethod
    def get_by_id(self, request_id: str) -> Optional[ScopeRequest]:
        """根據 ID 取得需求"""
        pass

    @abstractmethod
    def list_all(
        self,
        status: Optional[ScopeRequestStatus] = None,
        topic: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[ScopeRequest]:
        """列出需求（支援狀態和主題篩選）"""
        pass

    @abstractmethod
    def update_status(
        self,
        request_id: str,
        new_status: ScopeRequestStatus,
        admin_notes: Optional[str] = None,
    ) -> bool:
        """更新需求狀態"""
        pass

    @abstractmethod
    def increment_fulfilled(self, request_id: str, count: int = 1) -> bool:
        """增加已完成題數"""
        pass

    @abstractmethod
    def get_pending_requests(self) -> list[ScopeRequest]:
        """取得所有待處理 + 已核准的需求（heartbeat 用）"""
        pass

    @abstractmethod
    def get_statistics(self) -> dict:
        """取得需求統計"""
        pass
