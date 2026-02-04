"""
Question Repository Interface - 題目儲存庫介面

定義題目 CRUD 操作的抽象介面，遵循 DDD Repository Pattern。
Infrastructure 層必須實作此介面。
"""

from abc import ABC, abstractmethod
from typing import Optional
from datetime import datetime

from src.domain.entities.question import Question, Difficulty, QuestionType
from src.domain.value_objects.audit import AuditEntry, AuditAction, ActorType


class IQuestionRepository(ABC):
    """
    題目儲存庫介面
    
    提供完整 CRUD + 審計追蹤功能。
    所有操作都會自動記錄審計日誌。
    """
    
    # ==================== Create ====================
    
    @abstractmethod
    def save(
        self,
        question: Question,
        actor_type: ActorType = ActorType.AGENT,
        actor_name: str = "crush",
        generation_context: Optional[dict] = None,
    ) -> str:
        """
        儲存題目（新增或更新）
        
        Args:
            question: 題目實體
            actor_type: 操作者類型
            actor_name: 操作者名稱
            generation_context: 生成上下文（新增時使用）
            
        Returns:
            題目 ID
        """
        pass
    
    # ==================== Read ====================
    
    @abstractmethod
    def get_by_id(self, question_id: str) -> Optional[Question]:
        """
        根據 ID 取得題目
        
        Args:
            question_id: 題目 ID
            
        Returns:
            題目實體，不存在則返回 None
        """
        pass
    
    @abstractmethod
    def list_all(
        self,
        limit: int = 100,
        offset: int = 0,
        difficulty: Optional[Difficulty] = None,
        question_type: Optional[QuestionType] = None,
        topic: Optional[str] = None,
        created_after: Optional[datetime] = None,
        created_by: Optional[str] = None,
    ) -> list[Question]:
        """
        列出題目（支援篩選）
        
        Args:
            limit: 最大筆數
            offset: 偏移量
            difficulty: 難度篩選
            question_type: 題型篩選
            topic: 主題篩選
            created_after: 建立時間篩選
            created_by: 建立者篩選
            
        Returns:
            題目列表
        """
        pass
    
    @abstractmethod
    def count(
        self,
        difficulty: Optional[Difficulty] = None,
        question_type: Optional[QuestionType] = None,
    ) -> int:
        """
        統計題目數量
        
        Args:
            difficulty: 難度篩選
            question_type: 題型篩選
            
        Returns:
            符合條件的題目數量
        """
        pass
    
    @abstractmethod
    def search(
        self,
        keyword: str,
        limit: int = 20,
    ) -> list[Question]:
        """
        搜尋題目
        
        Args:
            keyword: 關鍵字（搜尋題目文字、選項、解析）
            limit: 最大筆數
            
        Returns:
            符合的題目列表
        """
        pass
    
    # ==================== Update ====================
    
    @abstractmethod
    def update(
        self,
        question: Question,
        actor_type: ActorType = ActorType.SKILL,
        actor_name: str = "unknown",
        reason: Optional[str] = None,
    ) -> bool:
        """
        更新題目
        
        Args:
            question: 更新後的題目實體
            actor_type: 操作者類型
            actor_name: 操作者名稱（如 skill 名稱）
            reason: 修改原因
            
        Returns:
            是否成功
        """
        pass
    
    # ==================== Delete ====================
    
    @abstractmethod
    def delete(
        self,
        question_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_name: str = "unknown",
        reason: Optional[str] = None,
        soft_delete: bool = True,
    ) -> bool:
        """
        刪除題目
        
        Args:
            question_id: 題目 ID
            actor_type: 操作者類型
            actor_name: 操作者名稱
            reason: 刪除原因
            soft_delete: 是否軟刪除（保留記錄）
            
        Returns:
            是否成功
        """
        pass
    
    @abstractmethod
    def restore(
        self,
        question_id: str,
        actor_type: ActorType = ActorType.USER,
        actor_name: str = "unknown",
    ) -> bool:
        """
        還原已刪除的題目
        
        Args:
            question_id: 題目 ID
            actor_type: 操作者類型
            actor_name: 操作者名稱
            
        Returns:
            是否成功
        """
        pass
    
    # ==================== Audit ====================
    
    @abstractmethod
    def get_audit_log(
        self,
        question_id: str,
        limit: int = 50,
    ) -> list[AuditEntry]:
        """
        取得題目的審計日誌
        
        Args:
            question_id: 題目 ID
            limit: 最大筆數
            
        Returns:
            審計記錄列表（時間倒序）
        """
        pass
    
    @abstractmethod
    def get_generation_context(self, question_id: str) -> Optional[dict]:
        """
        取得題目的生成上下文
        
        Args:
            question_id: 題目 ID
            
        Returns:
            生成上下文字典，不存在則返回 None
        """
        pass
    
    # ==================== Validation ====================
    
    @abstractmethod
    def mark_validated(
        self,
        question_id: str,
        passed: bool,
        actor_name: str = "question-validator",
        notes: Optional[str] = None,
    ) -> bool:
        """
        標記題目驗證結果
        
        Args:
            question_id: 題目 ID
            passed: 是否通過驗證
            actor_name: 驗證者名稱
            notes: 驗證備註
            
        Returns:
            是否成功
        """
        pass
    
    # ==================== Statistics ====================
    
    @abstractmethod
    def get_statistics(self) -> dict:
        """
        取得題庫統計
        
        Returns:
            統計資訊字典：
            {
                "total": 總題數,
                "by_difficulty": {"easy": n, "medium": n, "hard": n},
                "by_type": {"single_choice": n, ...},
                "by_topic": {"topic1": n, ...},
                "validated": 已驗證數,
                "deleted": 已刪除數,
                "recent_7_days": 近7天新增數,
            }
        """
        pass
