import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.application.services.scope_request_dispatch_service import ScopeRequestDispatchService  # noqa: E402
from src.domain.entities.scope_request import ScopeRequest, ScopeRequestStatus  # noqa: E402


class _FakeScopeRepo:
    def __init__(self, request: ScopeRequest):
        self.request = request
        self.status_updates: list[tuple[ScopeRequestStatus, str | None]] = []

    def get_by_id(self, request_id: str) -> ScopeRequest | None:
        if request_id != self.request.id:
            return None
        return self.request

    def update_status(self, request_id: str, new_status: ScopeRequestStatus, admin_notes: str | None = None) -> bool:
        assert request_id == self.request.id
        self.request.status = new_status
        self.request.admin_notes = admin_notes
        self.status_updates.append((new_status, admin_notes))
        return True

    def increment_fulfilled(self, request_id: str, count: int = 1) -> bool:
        assert request_id == self.request.id
        self.request.fulfilled_count += count
        if self.request.fulfilled_count >= self.request.target_count:
            self.request.status = ScopeRequestStatus.FULFILLED
        return True


class _FakeHeartbeat:
    def build_generation_prompt(self, gap) -> str:
        return f"請補 {gap.deficit} 題：{gap.topic}"


class _FakeQuestionTool:
    def __init__(self) -> None:
        self.saved_args: list[dict] = []

    def save_question(self, args: dict) -> dict:
        self.saved_args.append(args)
        return {
            "success": True,
            "question_id": f"q-{len(self.saved_args)}",
        }


class _FakeProvider:
    name = "openclaw"

    def __init__(self, payload: dict):
        self.payload = payload
        self.prompts: list[str] = []
        self.session_keys: list[str | None] = []

    def run(self, prompt: str, session_key: str | None = None) -> str:
        self.prompts.append(prompt)
        self.session_keys.append(session_key)
        return json.dumps(self.payload, ensure_ascii=False)


def test_dispatch_auto_persists_question_payload_when_agent_skips_save_ids() -> None:
    request = ScopeRequest(
        id="req-1",
        topic="麻醉風險",
        chapter="Risk of Anesthesia",
        difficulty="medium",
        exam_track="ite",
        status=ScopeRequestStatus.APPROVED,
        target_count=1,
    )
    scope_repo = _FakeScopeRepo(request)
    question_tool = _FakeQuestionTool()
    provider = _FakeProvider(
        {
            "question_text": "根據麻醉風險研究文獻，關於麻醉相關風險的敘述，下列何者正確？",
            "options": [
                "A. 歷史研究指出麻醉相關的呼吸抑制是導致死亡和昏迷的主要原因",
                "B. 麻醉相關風險通常定義為術後 7 天內的發病率和死亡率",
                "C. 麻醉相關的心跳停止主要與手術技術問題有關",
                "D. 區域麻醉的使用增加並未改善產婦死亡率結果",
            ],
            "correct_answer": "A",
            "explanation": "歷史研究指出麻醉相關的呼吸抑制是總歸因於麻醉的死亡與昏迷主因。",
            "source_doc": "doc_27___risk_of_anesthesia_6812de",
            "source_chapter": "Chapter 27 - Risk of Anesthesia",
            "stem_source": {
                "page": 1,
                "line_start": 10,
                "line_end": 13,
                "original_text": "Historical studies of anesthesia-related risk identified anesthesia-related respiratory depression as the major cause of death and coma totally attributable to anesthesia.",
            },
            "answer_source": {
                "page": 1,
                "line_start": 10,
                "line_end": 13,
                "original_text": "Historical studies of anesthesia-related risk identified anesthesia-related respiratory depression as the major cause of death and coma totally attributable to anesthesia.",
            },
            "explanation_sources": [
                {
                    "page": 1,
                    "line_start": 10,
                    "line_end": 13,
                    "original_text": "Historical studies of anesthesia-related risk identified anesthesia-related respiratory depression as the major cause of death and coma totally attributable to anesthesia.",
                }
            ],
            "difficulty": "medium",
            "topics": ["麻醉風險", "麻醉安全"],
        }
    )
    service = ScopeRequestDispatchService(
        scope_repo=scope_repo,
        heartbeat=_FakeHeartbeat(),
        question_tool=question_tool,
    )

    result = service.dispatch(request.id, provider)

    assert result.success is True
    assert result.generated_count == 1
    assert result.applied_count == 1
    assert result.question_ids == ["q-1"]
    assert request.fulfilled_count == 1
    assert request.status == ScopeRequestStatus.FULFILLED
    assert provider.session_keys == ["agent:main:scope:req-1"]
    assert question_tool.saved_args[0]["actor_name"] == "openclaw"
    assert question_tool.saved_args[0]["source_doc"] == "doc_27___risk_of_anesthesia_6812de"
    assert "補存 1 題" in (request.admin_notes or "")
