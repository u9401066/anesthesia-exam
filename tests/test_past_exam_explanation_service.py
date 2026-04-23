import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

import src.application.services.past_exam_explanation_service as explanation_module  # noqa: E402
from src.application.services.past_exam_explanation_service import PastExamExplanationService  # noqa: E402
from src.domain.entities.past_exam import PastExam, PastExamQuestion, QuestionPattern  # noqa: E402
from src.infrastructure.persistence.sqlite_past_exam_repo import SQLitePastExamRepository  # noqa: E402
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository  # noqa: E402


class _FakeProvider:
    name = "fake"

    def __init__(self):
        self.prompts: list[str] = []

    def run(self, prompt: str) -> str:
        self.prompts.append(prompt)
        return (
            "<think>internal reasoning</think>"
            '{"explanation":"Propofol 常造成血壓下降，因此 A 正確；其餘選項與典型藥理表現不符。"}'
        )


def _write_doc(
    tmp_path: Path,
    *,
    doc_id: str,
    title: str,
    filename: str,
    markdown: str,
    blocks: list[dict],
) -> Path:
    doc_dir = tmp_path / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        json.dumps(
            {
                "doc_id": doc_id,
                "title": title,
                "filename": filename,
                "assets": {"sections": []},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(markdown, encoding="utf-8")
    (doc_dir / "blocks.json").write_text(json.dumps(blocks, ensure_ascii=False), encoding="utf-8")
    return doc_dir


def _seed_past_exam(repo: SQLitePastExamRepository, exam_year: int, exam_name: str, questions: list[PastExamQuestion]) -> str:
    exam = PastExam(
        exam_year=exam_year,
        exam_name=exam_name,
        total_questions=len(questions),
        source_pdf=f"{exam_year}.pdf",
        imported_by="pytest",
        is_parsed=True,
        is_classified=True,
    )
    repo.save_exam(exam)
    repo.save_questions(exam.id, questions)
    return exam.id


def test_generate_and_save_explanation_uses_repo_context_and_persists(tmp_path: Path) -> None:
    db_path = tmp_path / "questions.db"
    past_exam_repo = SQLitePastExamRepository(db_path=db_path)
    question_repo = SQLiteQuestionRepository(db_path=db_path)
    _write_doc(
        tmp_path,
        doc_id="doc_2020_miller_s_anesthesia_9th_7481c2",
        title="Pediatric and Neonatal Critical Care",
        filename="2020 Miller's Anesthesia 9th.pdf",
        markdown="""# Pediatric and Neonatal Critical Care

## Therapy and Outcomes

Propofol commonly causes hypotension because it decreases systemic vascular resistance and myocardial contractility.
Propofol can also suppress respiration and is pharmacologically linked to GABA-A receptor activity.
""",
        blocks=[
            {
                "block_id": "blk_0001",
                "block_type": "Text",
                "page": 12,
                "text": "Propofol commonly causes hypotension because it decreases systemic vascular resistance and myocardial contractility.",
                "bbox": [1, 2, 3, 4],
                "section_hierarchy": {"1": "Pediatric and Neonatal Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 10, "line_end": 10},
            },
            {
                "block_id": "blk_0002",
                "block_type": "Text",
                "page": 12,
                "text": "Propofol can also suppress respiration and is pharmacologically linked to GABA-A receptor activity.",
                "bbox": [2, 3, 4, 5],
                "section_hierarchy": {"1": "Pediatric and Neonatal Critical Care", "2": "Therapy and Outcomes"},
                "metadata": {"line_start": 11, "line_end": 11},
            },
        ],
    )

    reference_question = PastExamQuestion(
        id="ref-q-1",
        exam_year=106,
        exam_name="106 麻醉專科",
        question_number=3,
        question_text="關於 Propofol 的敘述何者正確？",
        options=["會升高血壓", "常造成低血壓", "不影響呼吸", "主要經腎臟原型排出"],
        correct_answer="B",
        explanation="Propofol 常造成血壓下降，且可抑制呼吸。",
        topics=["藥理學", "Propofol"],
        concept_names=["Propofol"],
        pattern=QuestionPattern.DIRECT_RECALL,
    )
    target_question = PastExamQuestion(
        id="target-q-1",
        exam_year=114,
        exam_name="114 麻醉甄審",
        question_number=8,
        question_text="關於 Propofol 的藥理，下列何者最正確？",
        options=["常造成低血壓", "一定導致高血壓", "完全不會抑制呼吸", "與 GABA 無關"],
        correct_answer="A",
        explanation="",
        topics=["藥理學", "Propofol"],
        concept_names=["Propofol"],
        pattern=QuestionPattern.DIRECT_RECALL,
    )

    _seed_past_exam(past_exam_repo, 106, "106 麻醉專科", [reference_question])
    target_exam_id = _seed_past_exam(past_exam_repo, 114, "114 麻醉甄審", [target_question])

    service = PastExamExplanationService(
        past_exam_repo=past_exam_repo,
        question_repo=question_repo,
        data_dir=tmp_path,
        opencode_config_path=tmp_path / "missing-opencode.json",
    )

    references = service.find_reference_matches(target_question.to_dict(), limit=3)
    assert references
    assert references[0]["source_type"] == "past_exam"
    assert "Propofol" in references[0]["question_text"]
    textbook_evidence = service.find_textbook_evidence(target_question.to_dict())
    assert textbook_evidence["source_ready"] is True
    assert textbook_evidence["matched_doc_id"] == "doc_2020_miller_s_anesthesia_9th_7481c2"
    assert textbook_evidence["source"]["chapter"] == "Pediatric and Neonatal Critical Care"
    assert textbook_evidence["source"]["section"] == "Therapy and Outcomes"

    provider = _FakeProvider()
    result = service.generate_and_save_explanation(target_question.to_dict(), provider=provider)

    assert result["saved"] is True
    assert result["explanation"].startswith("Propofol")
    assert result["semantic_outline"]["question_group"]["pattern"] == "direct_recall"
    assert "Propofol" in result["semantic_outline"]["stem_focus"]["concept_names"]
    assert result["textbook_evidence"]["source_ready"] is True
    assert provider.prompts
    assert "題目結構骨架（請先依這份結構拆解，再撰寫詳解）" in provider.prompts[0]
    assert "options_analysis" in provider.prompts[0]
    assert "教材證據（優先依此撰寫，不得捏造引用）" in provider.prompts[0]
    assert "Therapy and Outcomes" in provider.prompts[0]
    assert "可參考的題庫脈絡" in provider.prompts[0]

    reloaded_exam = past_exam_repo.get_exam(target_exam_id)
    assert reloaded_exam is not None
    assert reloaded_exam.questions[0].explanation.startswith("Propofol")


def test_find_textbook_evidence_returns_safe_fallback_when_textbook_lookup_fails(tmp_path: Path) -> None:
    class _FailingTextbookGenerationService:
        def build_evidence_pack_for_question(self, *args, **kwargs):  # noqa: ANN001, ARG002
            raise RuntimeError("boom")

    service = PastExamExplanationService(
        textbook_generation_service=_FailingTextbookGenerationService(),
        opencode_config_path=tmp_path / "missing-opencode.json",
    )
    service._cached_textbook_doc_catalog = [{"doc_id": "doc-ready"}]

    evidence = service.find_textbook_evidence({"id": "q-1", "question_text": "test"})

    assert evidence["source_ready"] is False
    assert evidence["source"] == {}
    assert evidence["matched_doc_id"] is None
    assert any("教材證據解析失敗" in reason for reason in evidence["gate_reasons"])


def test_safe_find_textbook_evidence_delegates_to_primary_lookup(tmp_path: Path) -> None:
    service = PastExamExplanationService(
        opencode_config_path=tmp_path / "missing-opencode.json",
    )
    service._cached_textbook_doc_catalog = []

    evidence = service.safe_find_textbook_evidence({"id": "q-1", "question_text": "test"})

    assert evidence["source_ready"] is False
    assert evidence["matched_doc_id"] is None
    assert evidence["source"] == {}


def test_resolve_direct_llm_config_reads_custom_provider_from_opencode_config(tmp_path: Path) -> None:
    db_path = tmp_path / "questions.db"
    opencode_config_path = tmp_path / "opencode.json"
    opencode_config_path.write_text(
        json.dumps(
            {
                "provider": {
                    "gb10": {
                        "options": {
                            "baseURL": "http://192.168.1.145:8081/v1",
                        },
                        "models": {
                            "Qwen.gguf": {"name": "GB10 Qwen"},
                        },
                    }
                },
                "model": "gb10/Qwen.gguf",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    service = PastExamExplanationService(
        past_exam_repo=SQLitePastExamRepository(db_path=db_path),
        question_repo=SQLiteQuestionRepository(db_path=db_path),
        opencode_config_path=opencode_config_path,
    )

    resolved = service.resolve_direct_llm_config()

    assert resolved["base_url"] == "http://192.168.1.145:8081/v1"
    assert resolved["model_id"] == "Qwen.gguf"
    assert resolved["source"] == "opencode:gb10"


def test_resolve_direct_llm_config_reads_openai_env_vars(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXAM_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("EXAM_CODEX_MODEL", "gpt-5.3-codex")
    monkeypatch.setenv("EXAM_OPENAI_API_KEY", "test-openai-key")
    monkeypatch.setenv("EXAM_OPENAI_PROJECT", "proj_test_123")

    service = PastExamExplanationService(
        opencode_config_path=tmp_path / "missing-opencode.json",
    )

    resolved = service.resolve_direct_llm_config()

    assert resolved["base_url"] == "https://api.openai.com/v1"
    assert resolved["model_id"] == "gpt-5.3-codex"
    assert resolved["api_key"] == "test-openai-key"
    assert resolved["headers"]["OpenAI-Project"] == "proj_test_123"
    assert resolved["source"] == "env"


def test_extract_completion_text_supports_responses_payload(tmp_path: Path) -> None:
    service = PastExamExplanationService(
        opencode_config_path=tmp_path / "missing-opencode.json",
    )

    payload = {
        "output": [
            {
                "type": "message",
                "content": [
                    {
                        "type": "output_text",
                        "text": "這是來自 Responses API 的詳解。",
                    }
                ],
            }
        ]
    }

    assert service._extract_completion_text(payload, mode="responses") == "這是來自 Responses API 的詳解。"


def test_get_past_exam_explanation_service_recreates_stale_singleton(monkeypatch) -> None:
    class _LegacyService:
        pass

    monkeypatch.setattr(explanation_module, "_service", _LegacyService())

    service = explanation_module.get_past_exam_explanation_service()

    assert isinstance(service, PastExamExplanationService)
    assert hasattr(service, "find_textbook_evidence")
    assert hasattr(service, "safe_find_textbook_evidence")
