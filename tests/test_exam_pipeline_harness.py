import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.mcp import exam_server  # noqa: E402


def test_exam_generation_pipeline_blueprint_exposes_expected_phases() -> None:
    result = exam_server.get_pipeline_blueprint({"pipeline_type": "exam-generation"})

    assert result["success"] is True
    phases = result["blueprint"]["phases"]
    assert [phase["key"] for phase in phases] == [
        "define_blueprint",
        "retrieve_evidence",
        "draft_questions",
        "validate_candidates",
        "persist_questions",
        "review_and_iterate",
    ]


def test_pipeline_run_roundtrip_and_gate_progression(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(exam_server, "PIPELINE_RUNS_DIR", tmp_path / "pipeline_runs")

    started = exam_server.start_pipeline_run(
        {
            "name": "Propofol blueprint",
            "objective": "根據教材產出 5 題 propofol 題目",
            "pipeline_type": "exam-generation",
            "target_question_count": 5,
            "source_doc_ids": ["doc_001"],
        }
    )

    assert started["success"] is True
    run_id = started["run_id"]

    blocked = exam_server.validate_phase_gate({"run_id": run_id, "phase_key": "retrieve_evidence"})
    assert blocked["valid"] is False
    assert any("target_concepts" in blocker for blocker in blocked["blockers"])

    phase_record = exam_server.record_phase_result(
        {
            "run_id": run_id,
            "phase_key": "define_blueprint",
            "status": "completed",
            "summary": "已定義 target concepts",
            "artifacts": {
                "target_concepts": ["Propofol", "靜脈麻醉劑"],
                "target_difficulty": "medium",
                "blueprint_json": {"patterns": ["機轉題", "比較題"]},
            },
            "metrics": {"target_question_count": 5},
        }
    )

    assert phase_record["success"] is True
    assert phase_record["current_phase"] == "retrieve_evidence"

    allowed = exam_server.validate_phase_gate({"run_id": run_id, "phase_key": "retrieve_evidence"})
    assert allowed["valid"] is True

    listed = exam_server.list_pipeline_runs({"status": "active", "limit": 10})
    assert listed["success"] is True
    assert any(run["run_id"] == run_id for run in listed["runs"])

    fetched = exam_server.get_pipeline_run({"run_id": run_id})
    assert fetched["success"] is True
    assert fetched["run"]["phases"][0]["artifacts"]["target_concepts"] == ["Propofol", "靜脈麻醉劑"]


def test_past_exam_pipeline_requires_normalization_before_classification(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(exam_server, "PIPELINE_RUNS_DIR", tmp_path / "pipeline_runs")

    started = exam_server.start_pipeline_run(
        {
            "name": "Past exam extraction",
            "objective": "從 10 年考古題抽出高頻概念",
            "pipeline_type": "past-exam-extraction",
            "target_question_count": 500,
            "source_doc_ids": ["doc_past_001"],
        }
    )
    run_id = started["run_id"]

    ingest = exam_server.record_phase_result(
        {
            "run_id": run_id,
            "phase_key": "ingest_past_exams",
            "status": "completed",
            "metrics": {"doc_count": 10},
            "artifacts": {"doc_ids": ["doc_past_001"]},
        }
    )
    assert ingest["success"] is True

    blocked = exam_server.validate_phase_gate({"run_id": run_id, "phase_key": "classify_patterns"})
    assert blocked["valid"] is False
    assert any("extracted_question_count" in blocker for blocker in blocked["blockers"])


def test_draft_questions_requires_source_ready_for_precise_source_mode(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(exam_server, "PIPELINE_RUNS_DIR", tmp_path / "pipeline_runs")

    started = exam_server.start_pipeline_run(
        {
            "name": "Remimazolam generation",
            "objective": "根據教材產出 1 題完整附詳解題目",
            "pipeline_type": "exam-generation",
            "target_question_count": 1,
            "source_doc_ids": ["doc_trial_001"],
        }
    )
    run_id = started["run_id"]

    exam_server.record_phase_result(
        {
            "run_id": run_id,
            "phase_key": "define_blueprint",
            "status": "completed",
            "artifacts": {
                "target_concepts": ["Remimazolam", "血流動力學穩定性"],
                "target_difficulty": "medium",
                "blueprint_json": {"patterns": ["比較題"]},
            },
            "metrics": {"target_question_count": 1},
        }
    )
    exam_server.record_phase_result(
        {
            "run_id": run_id,
            "phase_key": "retrieve_evidence",
            "status": "completed",
            "artifacts": {
                "source_ready": False,
                "blocker_reason": "document missing marker blocks",
            },
            "metrics": {"evidence_refs_count": 2},
        }
    )

    blocked = exam_server.validate_phase_gate({"run_id": run_id, "phase_key": "draft_questions"})

    assert blocked["valid"] is False
    assert any("source_ready" in blocker for blocker in blocked["blockers"])

    exam_server.record_phase_result(
        {
            "run_id": run_id,
            "phase_key": "retrieve_evidence",
            "status": "completed",
            "artifacts": {
                "source_ready": True,
                "kg_query_status": "failed",
                "kg_fallback_used": True,
            },
            "metrics": {"evidence_refs_count": 2},
        }
    )

    allowed = exam_server.validate_phase_gate({"run_id": run_id, "phase_key": "draft_questions"})

    assert allowed["valid"] is True
