import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT_PATH = PROJECT_ROOT / "scripts" / "import_written_past_exams.py"


def _load_script_module():
    spec = importlib.util.spec_from_file_location("import_written_past_exams_for_test", SCRIPT_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_prepare_109_exam_uses_verified_answers(monkeypatch):
    module = _load_script_module()
    dummy_document = module.AssetAwareDocument(
        doc_id=module.ASSET_DOC_IDS[109],
        title="109年麻醉科專科醫師甄審筆試試卷",
        manifest={},
        markdown="1. 題目\n(A) 選項一\n(B) 選項二\n(C) 選項三\n(D) 選項四",
        markdown_path=SCRIPT_PATH,
    )
    monkeypatch.setattr(module.EXTRACTION_SERVICE, "load_asset_document", lambda doc_id: dummy_document)

    prepared = module.prepare_109_exam()

    assert prepared.answer_overrides == {}
    assert "## 答案" in prepared.document.markdown
    assert "1. B" in prepared.document.markdown
    assert "40. A" in prepared.document.markdown
    assert "71. D" in prepared.document.markdown
    assert "100. C" in prepared.document.markdown
    assert "BONUS" not in prepared.document.markdown
    assert prepared.notes == ["109 年筆試答案已依官方答案表影像逐題校對後匯入。"]
