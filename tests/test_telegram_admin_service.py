from __future__ import annotations

import json
from pathlib import Path

from src.application.services.telegram_admin_service import (
    SiteStatusSnapshot,
    TelegramAdminBot,
    TelegramAdminConfig,
    TelegramAdminStatusService,
    format_status_snapshot,
    format_worker_notification,
)


class FakeTelegramClient:
    def __init__(self):
        self.sent: list[tuple[str, str]] = []

    def send_message(self, chat_id: str, text: str) -> None:
        self.sent.append((chat_id, text))


class FakeStatusService:
    def build_status_text(self) -> str:
        return "status ok"

    def build_jobs_text(self) -> str:
        return "jobs ok"

    def build_errors_text(self) -> str:
        return "errors ok"

    def build_openclaw_text(self) -> str:
        return "openclaw ok"

    def build_web_text(self) -> str:
        return "web ok"

    def build_help_text(self) -> str:
        return "help ok"


def test_config_from_env_requires_enabled_token_and_admins() -> None:
    disabled = TelegramAdminConfig.from_env({})
    assert disabled.is_configured is False

    config = TelegramAdminConfig.from_env(
        {
            "TELEGRAM_ENABLED": "true",
            "TELEGRAM_BOT_TOKEN": "123:abc",
            "TELEGRAM_ADMIN_CHAT_IDS": "111, 222",
        }
    )

    assert config.is_configured is True
    assert config.is_admin("111") is True
    assert config.is_admin(222) is True
    assert config.is_admin("333") is False


def test_status_service_counts_jobs_and_collects_component_status(tmp_path: Path) -> None:
    jobs_dir = tmp_path / "data" / "jobs"
    jobs_dir.mkdir(parents=True)
    (jobs_dir / "pending.json").write_text(json.dumps({"status": "pending", "topic": "airway"}), encoding="utf-8")
    (jobs_dir / "error.json").write_text(
        json.dumps({"status": "error", "topic": "propofol", "error": "blocked: no citation"}),
        encoding="utf-8",
    )

    def fake_run(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
        joined = " ".join(command)
        if "openclaw.sh --version" in joined:
            return 0, "OpenClaw 2026.5.22", ""
        if "openclaw.sh mcp list" in joined:
            return 0, "asset-aware\nexam-generator", ""
        if "anesthesia-exam-web.service" in joined:
            return 0, "active", ""
        if "anesthesia-exam-openclaw-worker.timer" in joined:
            return 0, "active", ""
        if "curl" in joined:
            return 0, "HTTP/1.1 200 OK", ""
        raise AssertionError(f"unexpected command: {command}")

    service = TelegramAdminStatusService(
        project_dir=tmp_path,
        run_command=fake_run,
        question_stats_reader=lambda: {"total": 7},
    )

    snapshot = service.collect_snapshot()

    assert snapshot.question_count == 7
    assert snapshot.web_service == "active"
    assert snapshot.web_http == "ok"
    assert snapshot.openclaw_version == "OpenClaw 2026.5.22"
    assert snapshot.mcp_servers == ["asset-aware", "exam-generator"]
    assert snapshot.worker_timer == "active"
    assert snapshot.job_counts == {"pending": 1, "error": 1}
    assert snapshot.recent_errors == ["propofol: blocked: no citation"]


def test_status_formatter_includes_admin_summary_fields() -> None:
    text = format_status_snapshot(
        SiteStatusSnapshot(
            question_count=24,
            web_service="active",
            web_http="ok",
            openclaw_version="OpenClaw 2026.5.22",
            mcp_servers=["asset-aware", "exam-generator"],
            worker_timer="active",
            job_counts={"pending": 5, "error": 3},
            recent_errors=["airway: blocked"],
        )
    )

    assert "Anesthesia Exam" in text
    assert "OpenClaw 2026.5.22" in text
    assert "asset-aware, exam-generator" in text
    assert "questions: 24" in text
    assert "pending=5" in text
    assert "error=3" in text
    assert "airway: blocked" in text


def test_admin_bot_ignores_unauthorized_chat() -> None:
    client = FakeTelegramClient()
    bot = TelegramAdminBot(
        config=TelegramAdminConfig(enabled=True, bot_token="123:abc", admin_chat_ids=frozenset({"111"})),
        client=client,
        status_service=FakeStatusService(),
    )

    handled = bot.handle_update({"update_id": 1, "message": {"chat": {"id": 999}, "text": "/status"}})

    assert handled is False
    assert client.sent == []


def test_admin_bot_routes_read_only_commands_for_admin() -> None:
    client = FakeTelegramClient()
    bot = TelegramAdminBot(
        config=TelegramAdminConfig(enabled=True, bot_token="123:abc", admin_chat_ids=frozenset({"111"})),
        client=client,
        status_service=FakeStatusService(),
    )

    assert bot.handle_update({"update_id": 1, "message": {"chat": {"id": 111}, "text": "/status"}}) is True
    assert bot.handle_update({"update_id": 2, "message": {"chat": {"id": 111}, "text": "/jobs"}}) is True
    assert bot.handle_update({"update_id": 3, "message": {"chat": {"id": 111}, "text": "/openclaw"}}) is True

    assert client.sent == [("111", "status ok"), ("111", "jobs ok"), ("111", "openclaw ok")]


def test_worker_notification_summarizes_errors_and_generated_questions() -> None:
    text = format_worker_notification(
        {
            "pending_jobs": 5,
            "processed_jobs": 1,
            "generated_questions": 2,
            "skipped_jobs": 4,
            "errors": ["blocked: no citation"],
            "success": False,
        }
    )

    assert "OpenClaw worker" in text
    assert "generated_questions: 2" in text
    assert "skipped_jobs: 4" in text
    assert "blocked: no citation" in text
