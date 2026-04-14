# Repository interfaces

from .past_exam_repository import IPastExamRepository
from .question_repository import IQuestionRepository

__all__ = ["IQuestionRepository", "IPastExamRepository"]
