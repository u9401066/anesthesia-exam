import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.question_review_service import QuestionReviewService  # noqa: E402


def test_save_review_question_to_bank_rejects_image_based_question(monkeypatch) -> None:
    service = QuestionReviewService()
    saved = {"called": False}

    def fake_save(_question):
        saved["called"] = True
        return "question-1"

    monkeypatch.setattr(service, "question_repo", type("Repo", (), {"save": staticmethod(fake_save)})())

    with pytest.raises(ValueError, match="image_based"):
        service.save_review_question_to_bank(
            {
                "pattern": "image_based",
                "question_text": "請判讀圖形",
                "options": ["A", "B", "C", "D"],
                "correct_answer": "A",
            }
        )

    assert saved["called"] is False