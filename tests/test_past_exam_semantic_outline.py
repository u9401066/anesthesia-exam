import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.past_exam_extraction_service import PastExamExtractionService  # noqa: E402


def test_build_question_semantic_outline_splits_stem_and_options(tmp_path: Path) -> None:
    service = PastExamExtractionService(tmp_path)

    outline = service.build_question_semantic_outline(
        {
            "question_text": "關於 Propofol 的藥理與血流動力學影響，下列何者最正確？",
            "options": [
                "常造成低血壓",
                "一定會升高血壓",
                "與 GABA-A receptor 無關",
                "完全不影響呼吸",
            ],
            "correct_answer": "A",
            "exam_year": 114,
            "exam_name": "麻醉甄審",
            "question_number": 8,
        }
    )

    assert outline["question_group"]["group_type"] == "standalone_question"
    assert outline["question_group"]["pattern"] == "mechanism"
    assert outline["question_group"]["task_focus"] == "mechanism_reasoning"
    assert "Propofol" in outline["stem_focus"]["concept_names"]
    assert "Hemodynamic stability" in outline["question_group"]["group_concepts"]
    assert outline["correct_option"]["label"] == "A"
    assert "Hemodynamic stability" in outline["correct_option"]["concept_names"]
    assert outline["options_analysis"][0]["role"] == "correct_answer"
    assert outline["options_analysis"][1]["role"] == "distractor"
