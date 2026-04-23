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


def _write_split_number_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_split_number") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Split Number Exam", "filename": "mock_split_number_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
1.
腎臟之autoregulation 的生理及病理表現，下列敘述何者為非？
(A) 可維持腎臟血流穩定
(B) Calcium channel blocker 不會抑制其作用
(C) 與尿液生成速率完全無關
(D) 糖尿病腎病變時可能消失

2.
關於propofol infusion syndrome 的臨床表現，下列敘述何者為非？
(A) Acute refractory bradycardia
(B) Metabolic acidosis
(C) Rhabdomyolysis
(D) Hypokalemia

## 答案
1. C
2. D
""",
        encoding="utf-8",
    )
    return doc_id


def _write_option_label_split_fixture_doc(
    data_dir: Path, doc_id: str = "doc_fixture_option_label_split"
) -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Option Label Split Exam", "filename": "mock_option_label_split_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
94.
你在進行胸腔手術麻醉誘導時使用 left double-lumen tube，下列何者正確？

(A)
1. Posterior wall of trachea; 2. Carina; 3. Right Upper Lobe Bronchus; 4. Bronchus intermedius
(B)
1. Bronchial Cuff; 2. Bronchus intermedius; 3. Right Upper Lobe Bronchus; 4. Carina
(C)
1. Bronchial Cuff; 2. Carina; 3. Bronchus intermedius; 4. Posterior wall of trachea
(D)
1. Posterior wall of trachea; 2. Carina; 3. Right Upper Lobe Bronchus; 4. Bronchus intermedius

95.
下一題題幹。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

## 答案
94. D
95. A
""",
        encoding="utf-8",
    )
    return doc_id


def _write_decimal_option_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_decimal_option") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Decimal Option Exam", "filename": "mock_decimal_option_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
50. 關於輸血的敘述，下列何者為非？
(A) 選項一
(B) 選項二
(C) 當病人血紅蛋白(Hb)濃度為7.2 g/dL，乳酸值2.1 mmol/L
(D) 當病人血紅蛋白(Hb)濃度為6.9 g/dL，體重51.2kg

51. 根據指引，下列何者錯誤？
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

## 答案
50. C
51. B
""",
        encoding="utf-8",
    )
    return doc_id


def _write_numeric_stem_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_numeric_stem") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Numeric Stem Exam", "filename": "mock_numeric_stem_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
10. 先前一題。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

11.33 歲女性，因頭痛至急診求診，下列何者正確？
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

## 答案
10. A
11. D
""",
        encoding="utf-8",
    )
    return doc_id


def _write_image_boundary_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_image_boundary") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Image Boundary Exam", "filename": "mock_image_boundary_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
93.圖題，選項內容在圖片中。
(A)
(B)
(C)
(D)
(E)
94.下一題必須被正確切出。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

## 答案
93. A
94. B
""",
        encoding="utf-8",
    )
    return doc_id


def _write_skipped_number_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_skipped_number") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Skipped Number Exam", "filename": "mock_skipped_number_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
1. 第一題題幹。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

3. 第三題題幹，不應被合併進第一題。
(A) 第三題選項一
(B) 第三題選項二
(C) 第三題選項三
(D) 第三題選項四

## 答案
1. A
3. C
""",
        encoding="utf-8",
    )
    return doc_id


def _write_skipped_number_with_incomplete_answer_fixture_doc(
    data_dir: Path, doc_id: str = "doc_fixture_skipped_number_incomplete_answer"
) -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Skipped Number Incomplete Answer Exam", "filename": "mock_skipped_number_incomplete_answer_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
1. 第一題題幹。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

5. 第五題題幹，即使答案區漏掉，也不應併進第一題。
(A) 第五題選項一
(B) 第五題選項二
(C) 第五題選項三
(D) 第五題選項四

## 答案
1. B
""",
        encoding="utf-8",
    )
    return doc_id


def _write_multi_answer_key_fixture_doc(data_dir: Path, doc_id: str = "doc_fixture_multi_answer_key") -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Multi Answer Key Exam", "filename": "mock_multi_answer_key_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
40. 多重正確答案題一。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四
(E) 選項五

53. 多重正確答案題二。
(A) 第二題選項一
(B) 第二題選項二
(C) 第二題選項三
(D) 第二題選項四
(E) 第二題選項五

## 答案
40=BE
53=AD
""",
        encoding="utf-8",
    )
    return doc_id


def _write_intrusive_option_marker_fixture_doc(
    data_dir: Path, doc_id: str = "doc_fixture_intrusive_option_marker"
) -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Intrusive Option Marker Exam", "filename": "mock_intrusive_option_marker_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
1. 下列有關小兒心臟麻醉，下列敘述何者錯誤？
(A) 小兒心臟麻醉誘導可使用 ketamine。
(B) 常會合併有其他先天性異常(VACTERAL association，分別指V:
vertebra，A: anal，C:cardiac，TE: Tracheoesophageal，R: renal，L:limb
等異常)
(C) 法洛氏症候群可能造成臨床上嚴重缺氧。
(D) 兒童手術的 CPB 溫度要求較低(15-20°C)且常要求 total circulatory arrest。
(E) 小兒心臟手術 CPB 建議使用 pH stat 方式管理 blood gas。

## 答案
1. D
""",
        encoding="utf-8",
    )
    return doc_id


def _write_cross_page_stem_continuation_fixture_doc(
    data_dir: Path, doc_id: str = "doc_fixture_cross_page_stem_continuation"
) -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Cross Page Stem Exam", "filename": "mock_cross_page_stem_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 15 -->
10. 一位 68 歲男性接受腹部手術，術後出現持續低血壓與心搏過速，
臨床團隊考慮敗血性休克的早期處置。
<!-- Page 16 -->
在初始復甦階段，下列何者最適當？
(A) 立即限制輸液以避免肺水腫
(B) 先等待血液培養結果再給抗生素
(C) 盡快給予廣效性抗生素並完成初始液體復甦
(D) 常規使用高劑量類固醇作為第一線治療

11. 下一題題幹。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

## 答案
10. C
11. B
""",
        encoding="utf-8",
    )
    return doc_id


def _write_question_number_reset_fixture_doc(
    data_dir: Path, doc_id: str = "doc_fixture_question_number_reset"
) -> str:
    doc_dir = data_dir / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    (doc_dir / f"{doc_id}_manifest.json").write_text(
        '{"title": "Mock Question Number Reset Exam", "filename": "mock_question_number_reset_exam.pdf"}',
        encoding="utf-8",
    )
    (doc_dir / f"{doc_id}_full.md").write_text(
        """<!-- Page 1 -->
49. 第一部分第四十九題。
(A) 選項一
(B) 選項二
(C) 選項三
(D) 選項四

50. 第一部分第五十題。
(A) 第五十題選項一
(B) 第五十題選項二
(C) 第五十題選項三
(D) 第五十題選項四

<!-- Page 2 -->
1. 第二部分第一題，題號重置後不應併進第五十題。
(A) 第二部分選項一
(B) 第二部分選項二
(C) 第二部分選項三
(D) 第二部分選項四

2. 第二部分第二題。
(A) 第二部分第二題選項一
(B) 第二部分第二題選項二
(C) 第二部分第二題選項三
(D) 第二部分第二題選項四

## 答案
49. A
50. B
1. C
2. D
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


def test_extract_past_exam_questions_supports_number_only_line(tmp_path: Path, monkeypatch) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_split_number_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "109年麻醉科考題", "exam_year": 2020}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert result["answer_key_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [1, 2]
    assert loaded["past_exam"]["questions"][0]["question_text"].startswith("腎臟之autoregulation")
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "C"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "D"


def test_extract_past_exam_questions_supports_option_labels_on_separate_lines(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_option_label_split_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "圖題考古題", "exam_year": 2020}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [94, 95]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "D"
    assert len(loaded["past_exam"]["questions"][0]["options"]) == 4


def test_extract_past_exam_questions_ignores_decimal_like_option_prefixes(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_decimal_option_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "數值選項考題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [50, 51]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "C"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "B"


def test_extract_past_exam_questions_supports_numeric_stem_immediately_after_number(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_numeric_stem_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "數字開頭題幹", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [10, 11]
    assert loaded["past_exam"]["questions"][1]["question_text"].startswith("33 歲女性")
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "D"


def test_extract_past_exam_questions_splits_after_label_only_image_options(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_image_boundary_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "圖題邊界考題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [93, 94]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "A"
    assert loaded["past_exam"]["questions"][0]["options"] == [
        "圖像選項 A",
        "圖像選項 B",
        "圖像選項 C",
        "圖像選項 D",
        "圖像選項 E",
    ]
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "B"


def test_extract_past_exam_questions_does_not_split_on_inline_a_colon_or_degree_c(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_intrusive_option_marker_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "行內字樣誤切考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 1
    assert len(loaded["past_exam"]["questions"][0]["options"]) == 5
    assert "A: anal" in loaded["past_exam"]["questions"][0]["options"][1]
    assert "C:cardiac" in loaded["past_exam"]["questions"][0]["options"][1]
    assert "15-20°C" in loaded["past_exam"]["questions"][0]["options"][3]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "D"


def test_extract_past_exam_questions_supports_skipped_question_numbers(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_skipped_number_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "跳號考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [1, 3]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "A"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "C"
    assert loaded["past_exam"]["questions"][1]["question_text"].startswith("第三題題幹")


def test_extract_past_exam_questions_supports_skipped_numbers_even_when_answer_map_is_incomplete(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_skipped_number_with_incomplete_answer_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "跳號且答案不完整考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [1, 5]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "B"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == ""
    assert loaded["past_exam"]["questions"][1]["question_text"].startswith("第五題題幹")


def test_extract_past_exam_questions_supports_multi_letter_answer_keys_with_equals_format(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_multi_answer_key_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "多重答案考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [40, 53]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "BE"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "AD"


def test_extract_past_exam_questions_preserves_cross_page_stem_continuation(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_cross_page_stem_continuation_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "跨頁題幹考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 2
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [10, 11]
    assert "術後出現持續低血壓與心搏過速" in loaded["past_exam"]["questions"][0]["question_text"]
    assert "在初始復甦階段" in loaded["past_exam"]["questions"][0]["question_text"]
    assert loaded["past_exam"]["questions"][0]["source_page"] == 15
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "C"


def test_extract_past_exam_questions_supports_question_number_reset_on_new_page(
    tmp_path: Path, monkeypatch
) -> None:
    data_dir = _configure_tmp_environment(tmp_path, monkeypatch)
    doc_id = _write_question_number_reset_fixture_doc(data_dir)

    result = exam_server.extract_past_exam_questions(
        {"doc_id": doc_id, "exam_name": "題號重置考古題", "exam_year": 2024}
    )
    loaded = exam_server.get_past_exam({"past_exam_id": result["past_exam_id"]})

    assert result["success"] is True
    assert result["extracted_question_count"] == 4
    assert [q["question_number"] for q in loaded["past_exam"]["questions"]] == [49, 50, 1, 2]
    assert loaded["past_exam"]["questions"][0]["correct_answer"] == "A"
    assert loaded["past_exam"]["questions"][1]["correct_answer"] == "B"
    assert loaded["past_exam"]["questions"][2]["correct_answer"] == "C"
    assert loaded["past_exam"]["questions"][2]["source_page"] == 2
    assert loaded["past_exam"]["questions"][2]["question_text"].startswith("第二部分第一題")
    assert loaded["past_exam"]["questions"][3]["correct_answer"] == "D"
