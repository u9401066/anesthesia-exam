import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.mcp import exam_server  # noqa: E402
from src.infrastructure.persistence.sqlite_past_exam_repo import SQLitePastExamRepository  # noqa: E402


def _configure_tmp_environment(tmp_path: Path, monkeypatch) -> Path:
    data_dir = tmp_path / "data"
    data_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(exam_server, "DATA_DIR", data_dir)
    monkeypatch.setattr(exam_server, "PIPELINE_RUNS_DIR", data_dir / "pipeline_runs")
    monkeypatch.setattr(exam_server, "EXAMS_DIR", data_dir / "exams")
    monkeypatch.setattr(exam_server, "QUESTIONS_DIR", data_dir / "questions")
    monkeypatch.setattr(exam_server, "past_exam_repo", SQLitePastExamRepository(db_path=data_dir / "past_exam.db"))
    return data_dir


def _write_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_past_exam") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Past Exam", "filename": "mock_past_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
1. 關於 Remimazolam 的作用機轉，下列何者正確？
A. 阻斷 NMDA 受體
B. 活化 GABA-A 受體
C. 活化 opioid 受體
D. 抑制 sodium channel

2. 一位接受無痛胃鏡的病人使用 remimazolam 與 propofol，比較何者正確？
A. Remimazolam 較容易低血壓
B. Propofol 注射痛較常見
C. 兩者鎮靜成功率差很多
D. Remimazolam 無法被拮抗

## 答案
1. B
2. B
""",
        encoding="utf-8",
    )
    return doc_id


def test_extract_past_exam_questions_is_idempotent(tmp_path: Path, monkeypatch) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_fixture_doc(data_dir)

    first = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "113年麻醉科考題", "exam_year": 2024}
    )
    second = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "113年麻醉科考題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": first["past_exam_id"]})

    assert first["success"] is True
    assert second["success"] is True
    assert first["extracted_question_count"] == 2
    assert len(loaded["past_exam"]["questions"]) == 2
    assert [q["correct_answer"] for q in loaded["past_exam"]["questions"]] == ["B", "B"]


def test_classify_and_build_blueprint_from_past_exam(tmp_path: Path, monkeypatch) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_fixture_doc(data_dir)

    extracted = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "Mock Past Exam", "exam_year": 2024}
    )
    classified = exam_server.classify_past_exam_patterns({"past_exam_id": extracted["past_exam_id"]})
    blueprint = exam_server.build_past_exam_blueprint({"past_exam_id": extracted["past_exam_id"]})

    assert classified["success"] is True
    assert classified["pattern_distribution"] == {"mechanism": 1, "clinical_scenario": 1}
    assert classified["concept_count"] >= 3
    assert blueprint["success"] is True
    assert blueprint["blueprint_json"]["question_count"] == 2
    assert blueprint["blueprint_json"]["high_frequency_concepts"]


def test_run_past_exam_extraction_completes_pipeline_run(tmp_path: Path, monkeypatch) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_fixture_doc(data_dir)

    started = exam_server.start_pipeline_run(
        {
            "name": "Mock past exam run",
            "objective": "抽出並分類 mock 考古題",
            "pipeline_type": "past-exam-extraction",
            "target_question_count": 2,
            "source_doc_ids": [doc_id],
        }
    )
    run_result = exam_server.run_past_exam_extraction(
        {
            "doc_id": doc_id,
            "exam_name": "Mock Past Exam",
            "exam_year": 2024,
            "run_id": started["run_id"],
        }
    )
    fetched = exam_server.get_pipeline_run({"run_id": started["run_id"]})
    phase_status = {phase["key"]: phase["status"] for phase in fetched["run"]["phases"]}

    assert run_result["success"] is True
    assert fetched["run"]["status"] == "completed"
    assert phase_status["ingest_past_exams"] == "completed"
    assert phase_status["normalize_questions"] == "completed"
    assert phase_status["classify_patterns"] == "completed"
    assert phase_status["build_blueprint"] == "completed"
    assert phase_status["publish_reference_pack"] == "completed"
