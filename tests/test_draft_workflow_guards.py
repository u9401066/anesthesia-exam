import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.question_draft_service import QuestionDraftService  # noqa: E402
from src.domain.entities.question import Difficulty, Question  # noqa: E402
from src.domain.entities.question_draft import QuestionDraft, QuestionDraftStatus  # noqa: E402
from src.infrastructure.persistence.sqlite_question_draft_repo import SQLiteQuestionDraftRepository  # noqa: E402
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository  # noqa: E402


def _build_repositories(tmp_path: Path) -> tuple[SQLiteQuestionDraftRepository, SQLiteQuestionRepository]:
    db_path = tmp_path / "draft-workflow.db"
    return SQLiteQuestionDraftRepository(db_path=db_path), SQLiteQuestionRepository(db_path=db_path)


def test_bulk_update_rejects_invalid_difficulty_without_partial_write(tmp_path: Path) -> None:
    draft_repo, _question_repo = _build_repositories(tmp_path)
    draft = QuestionDraft(
        question=Question(
            question_text="bulk update guard",
            options=["A", "B", "C", "D"],
            correct_answer="A",
        )
    )
    draft_repo.save(draft, actor_name="pytest", reason="seed", action="created")

    with pytest.raises(ValueError, match="Unsupported draft difficulty"):
        draft_repo.bulk_update([draft.id], difficulty="veryhard", is_starred=True)

    reloaded = draft_repo.get_by_id(draft.id)
    assert reloaded is not None
    assert reloaded.question.difficulty is Difficulty.MEDIUM
    assert reloaded.is_starred is False

    history = draft_repo.get_history(draft.id)
    assert [entry.action for entry in history] == ["created"]


def test_promote_drafts_rolls_back_question_when_mark_promoted_fails(tmp_path: Path, monkeypatch) -> None:
    draft_repo, question_repo = _build_repositories(tmp_path)
    service = QuestionDraftService()
    service.draft_repo = draft_repo
    service.question_repo = question_repo

    draft = QuestionDraft(
        question=Question(
            question_text="promote rollback guard",
            options=["A", "B", "C", "D"],
            correct_answer="A",
        )
    )
    draft_repo.save(draft, actor_name="pytest", reason="seed", action="created")

    def fail_mark_promoted(*_args, **_kwargs):
        raise RuntimeError("forced mark_promoted failure")

    monkeypatch.setattr(draft_repo, "mark_promoted_with_connection", fail_mark_promoted)

    result = service.promote_drafts([draft.id], actor_name="pytest-user")

    assert result == {"promoted": 0, "failed": [draft.id]}
    assert question_repo.get_by_id(draft.question.id) is None

    reloaded_draft = draft_repo.get_by_id(draft.id)
    assert reloaded_draft is not None
    assert reloaded_draft.status is QuestionDraftStatus.DRAFT


def test_promote_drafts_marks_draft_and_persists_question_atomically(tmp_path: Path) -> None:
    draft_repo, question_repo = _build_repositories(tmp_path)
    service = QuestionDraftService()
    service.draft_repo = draft_repo
    service.question_repo = question_repo

    draft = QuestionDraft(
        question=Question(
            question_text="promote happy path",
            options=["A", "B", "C", "D"],
            correct_answer="A",
        )
    )
    draft_repo.save(draft, actor_name="pytest", reason="seed", action="created")

    result = service.promote_drafts([draft.id], actor_name="pytest-user")

    assert result == {"promoted": 1, "failed": []}

    saved_question = question_repo.get_by_id(draft.question.id)
    assert saved_question is not None
    assert saved_question.question_text == draft.question.question_text

    reloaded_draft = draft_repo.get_by_id(draft.id)
    assert reloaded_draft is not None
    assert reloaded_draft.status is QuestionDraftStatus.PROMOTED
    assert reloaded_draft.promoted_question_id == draft.question.id


def test_promote_drafts_keeps_successful_items_when_later_draft_fails(tmp_path: Path, monkeypatch) -> None:
    draft_repo, question_repo = _build_repositories(tmp_path)
    service = QuestionDraftService()
    service.draft_repo = draft_repo
    service.question_repo = question_repo

    successful_draft = QuestionDraft(
        question=Question(
            question_text="batch promote success",
            options=["A", "B", "C", "D"],
            correct_answer="A",
        )
    )
    failing_draft = QuestionDraft(
        question=Question(
            question_text="batch promote failure",
            options=["A", "B", "C", "D"],
            correct_answer="B",
        )
    )
    draft_repo.save(successful_draft, actor_name="pytest", reason="seed", action="created")
    draft_repo.save(failing_draft, actor_name="pytest", reason="seed", action="created")

    original_mark_promoted = draft_repo.mark_promoted_with_connection

    def fail_only_second(conn, draft_id: str, question_id: str, **kwargs):
        if draft_id == failing_draft.id:
            raise RuntimeError("forced second draft promote failure")
        return original_mark_promoted(conn, draft_id, question_id, **kwargs)

    monkeypatch.setattr(draft_repo, "mark_promoted_with_connection", fail_only_second)

    result = service.promote_drafts([successful_draft.id, failing_draft.id], actor_name="pytest-user")

    assert result == {"promoted": 1, "failed": [failing_draft.id]}

    saved_success_question = question_repo.get_by_id(successful_draft.question.id)
    assert saved_success_question is not None

    saved_failure_question = question_repo.get_by_id(failing_draft.question.id)
    assert saved_failure_question is None

    reloaded_success = draft_repo.get_by_id(successful_draft.id)
    assert reloaded_success is not None
    assert reloaded_success.status is QuestionDraftStatus.PROMOTED
    assert reloaded_success.promoted_question_id == successful_draft.question.id

    reloaded_failure = draft_repo.get_by_id(failing_draft.id)
    assert reloaded_failure is not None
    assert reloaded_failure.status is QuestionDraftStatus.DRAFT
    assert reloaded_failure.promoted_question_id is None


def test_concurrent_save_keeps_draft_version_numbers_unique(tmp_path: Path) -> None:
    draft_repo, _question_repo = _build_repositories(tmp_path)
    draft = QuestionDraft(
        question=Question(
            question_text="concurrent version guard",
            options=["A", "B", "C", "D"],
            correct_answer="A",
        )
    )
    draft_repo.save(draft, actor_name="pytest", reason="seed", action="created")

    def save_note(note: str) -> None:
        local_draft = draft_repo.get_by_id(draft.id)
        assert local_draft is not None
        local_draft.notes = note
        draft_repo.save(local_draft, actor_name=note, reason=note, action="updated")

    with ThreadPoolExecutor(max_workers=2) as pool:
        list(pool.map(save_note, ["worker-1", "worker-2"]))

    history = draft_repo.get_history(draft.id, limit=10)
    version_numbers = [entry.version_number for entry in history]

    assert len(history) == 3
    assert len(set(version_numbers)) == 3
    assert sorted(version_numbers) == [1, 2, 3]
