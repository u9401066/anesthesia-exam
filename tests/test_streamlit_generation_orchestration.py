import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.presentation.streamlit.generation.orchestration import (  # noqa: E402
    build_generation_prompt,
    extract_questions_from_response,
)


def test_build_generation_prompt_includes_formal_source_tracking_steps() -> None:
    prompt = build_generation_prompt(
        num_questions=3,
        question_type="單選題",
        difficulty="中等",
        topics=["Propofol", "血流動力學"],
        source_doc="Miller Chapter 79",
        selected_doc_ids=["doc_formal_001"],
        preview_only_mode=False,
        selected_section_details=[
            {"id": "sec_79", "title": "Therapy and Outcomes", "page": 12, "doc_id": "doc_formal_001"}
        ],
        additional_instructions="請偏重比較題",
        prompt_preset="標準臨床題",
        prompt_presets={"標準臨床題": "請優先出臨床情境導向題。"},
        prompt_context="Shock therapy context",
        source_mode="使用既有已拆解教材",
        template_context=None,
    )

    assert "正式來源追蹤流程" in prompt
    assert 'search_source_location(doc_id="doc_formal_001"' in prompt
    assert "教材內容上下文" in prompt
    assert "結構化出題要求" in prompt
    assert '"semantic_structure"' not in prompt
    assert "`semantic_structure`" in prompt
    assert "preset: 標準臨床題" in prompt
    assert '"source_doc": "Miller Chapter 79"' in prompt
    assert "不得呼叫 `exam_save_question`、`exam_bulk_save`" in prompt
    assert "UI 會把結果先送入待審草稿" in prompt


def test_build_generation_prompt_uses_preview_only_mode_for_indexed_docs_without_precise_sources() -> None:
    prompt = build_generation_prompt(
        num_questions=2,
        question_type="單選題",
        difficulty="簡單",
        topics=["Remimazolam"],
        source_doc="Indexed but preview only",
        selected_doc_ids=["doc_preview_001", "doc_preview_002"],
        preview_only_mode=True,
        selected_section_details=[],
        additional_instructions="",
        prompt_preset="無",
        prompt_presets={},
        prompt_context="",
        source_mode="使用既有已拆解教材",
        template_context=None,
    )

    assert "Preview 草稿模式" in prompt
    assert "不得呼叫 `exam_save_question` 或 `exam_bulk_save` 正式入庫" in prompt
    assert "正式來源追蹤流程" not in prompt


def test_build_generation_prompt_supports_template_rewrite_mode() -> None:
    prompt = build_generation_prompt(
        num_questions=2,
        question_type="單選題",
        difficulty="中等",
        topics=[],
        source_doc="",
        selected_doc_ids=[],
        preview_only_mode=True,
        selected_section_details=[],
        additional_instructions="請改成臨床情境題",
        prompt_preset="無",
        prompt_presets={},
        prompt_context="",
        source_mode="直接拿考古題模板改寫",
        template_context={
            "label": "臨床情境骨架",
            "pattern_label": "臨床情境",
            "source_exam_year": 2020,
            "source_exam_name": "ITE",
            "source_question_number": 17,
            "reference_question_text": "原始考古題題幹",
            "stem_scaffold": "一名與困難插管相關的臨床個案接受麻醉處置時，下列何者最適當？",
            "topics": ["困難插管", "氣道管理"],
            "difficulty": "medium",
            "bloom_level": 3,
            "blueprint": {
                "recommended_rules": [
                    "保留歷史題型骨架，但改寫題幹與選項，不直接重寫原題。",
                    "正式入庫前應檢查答案、解析與來源是否彼此對齊。",
                ],
                "sample_source_refs": ["2020 ITE 第 17 題"],
            },
        },
    )

    assert "歷史題型模板改寫模式" in prompt
    assert "來源模式: 直接拿考古題模板改寫" in prompt
    assert "臨床情境骨架" in prompt
    assert "原始考古題題幹" in prompt
    assert "不得直接複製原題幹、原選項或原答案文字" in prompt
    assert "結果只需輸出 JSON；UI 會自動把這批結果送入待審草稿" in prompt
    assert "anchor_topics" in prompt
    assert '["困難插管", "氣道管理"]' in prompt


def test_extract_questions_from_response_deduplicates_and_normalizes_options() -> None:
    response = '''
先說明一下。

```json
{
  "question_text": "下列何者是 propofol 常見副作用？",
  "options": ["A. 低血壓", "B. 高血壓", "C. 支氣管擴張", "D. 高血糖"],
  "correct_answer": "A",
  "explanation": "Propofol 常造成低血壓。",
  "semantic_structure": {
    "question_group": {"pattern": "direct_recall"},
    "stem_focus": {"tested_topics": ["藥理學"]},
    "options_analysis": [{"label": "A", "role": "correct_answer"}]
  },
  "source_doc": "Miller",
  "source_chapter": "Chapter 25"
}
```

然後我再貼一次同一題：
{
  "question_text": "下列何者是 propofol 常見副作用？",
  "options": ["A. 低血壓", "B. 高血壓", "C. 支氣管擴張", "D. 高血糖"],
  "correct_answer": "A",
  "explanation": "Propofol 常造成低血壓。",
  "source_doc": "Miller",
  "source_chapter": "Chapter 25"
}
'''

    questions = extract_questions_from_response(response)

    assert len(questions) == 1
    assert questions[0]["options"] == ["低血壓", "高血壓", "支氣管擴張", "高血糖"]
    assert questions[0]["semantic_structure"]["question_group"]["pattern"] == "direct_recall"
    assert questions[0]["source"]["document"] == "Miller"
    assert questions[0]["source"]["chapter"] == "Chapter 25"
