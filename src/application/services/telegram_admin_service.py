"""Telegram read-only admin entrypoint for OpenClaw and site status."""

from __future__ import annotations

import json
import os
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping

from src.application.services.openclaw_session_keys import build_openclaw_session_key
from src.infrastructure.agent.provider import AgentProviderConfig, create_agent_provider
from src.infrastructure.logging import get_logger

PROJECT_DIR = Path(__file__).resolve().parents[3]
logger = get_logger(__name__)

RunCommand = Callable[[list[str], int], tuple[int, str, str]]
QuestionStatsReader = Callable[[], dict[str, Any]]


@dataclass(frozen=True)
class TelegramAdminConfig:
    """Runtime Telegram admin configuration."""

    enabled: bool = False
    bot_token: str = ""
    admin_chat_ids: frozenset[str] = frozenset()
    api_base_url: str = "https://api.telegram.org"
    timeout_seconds: int = 10
    poll_timeout_seconds: int = 30
    allow_openclaw_ask: bool = False

    @classmethod
    def from_env(cls, env: Mapping[str, str] | None = None) -> "TelegramAdminConfig":
        source = env if env is not None else os.environ
        enabled_raw = str(source.get("TELEGRAM_ENABLED") or "").strip().lower()
        enabled = enabled_raw in {"1", "true", "yes", "on"}
        token = str(source.get("TELEGRAM_BOT_TOKEN") or "").strip()
        admin_ids = frozenset(
            item.strip()
            for item in str(source.get("TELEGRAM_ADMIN_CHAT_IDS") or "").replace(";", ",").split(",")
            if item.strip()
        )
        api_base_url = str(source.get("TELEGRAM_API_BASE_URL") or cls.api_base_url).strip().rstrip("/")
        timeout_seconds = _positive_int(source.get("TELEGRAM_TIMEOUT_SECONDS"), 10)
        poll_timeout_seconds = _positive_int(source.get("TELEGRAM_POLL_TIMEOUT_SECONDS"), 30)
        ask_enabled_raw = str(source.get("TELEGRAM_OPENCLAW_ASK_ENABLED") or "").strip().lower()
        return cls(
            enabled=enabled,
            bot_token=token,
            admin_chat_ids=admin_ids,
            api_base_url=api_base_url,
            timeout_seconds=timeout_seconds,
            poll_timeout_seconds=poll_timeout_seconds,
            allow_openclaw_ask=ask_enabled_raw in {"1", "true", "yes", "on"},
        )

    @property
    def is_configured(self) -> bool:
        return self.enabled and bool(self.bot_token) and bool(self.admin_chat_ids)

    def is_admin(self, chat_id: str | int | None) -> bool:
        if chat_id is None:
            return False
        return str(chat_id).strip() in self.admin_chat_ids


@dataclass(frozen=True)
class SiteStatusSnapshot:
    """Compact status payload for Telegram rendering."""

    question_count: int = 0
    web_service: str = "unknown"
    web_http: str = "unknown"
    openclaw_version: str = "unknown"
    mcp_servers: list[str] = field(default_factory=list)
    worker_timer: str = "unknown"
    job_counts: dict[str, int] = field(default_factory=dict)
    recent_errors: list[str] = field(default_factory=list)
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat(timespec="seconds"))


class TelegramHttpClient:
    """Small Telegram Bot API client using the standard library."""

    def __init__(self, config: TelegramAdminConfig) -> None:
        self.config = config

    def send_message(self, chat_id: str, text: str) -> None:
        for chunk in _chunk_text(text):
            self._post(
                "sendMessage",
                {
                    "chat_id": chat_id,
                    "text": chunk,
                    "disable_web_page_preview": "true",
                },
            )

    def get_updates(self, *, offset: int | None = None, timeout_seconds: int | None = None) -> list[dict[str, Any]]:
        params: dict[str, str] = {
            "timeout": str(timeout_seconds if timeout_seconds is not None else self.config.poll_timeout_seconds),
            "allowed_updates": json.dumps(["message", "edited_message"]),
        }
        if offset is not None:
            params["offset"] = str(offset)
        payload = self._get("getUpdates", params)
        result = payload.get("result")
        return result if isinstance(result, list) else []

    def _api_url(self, method: str) -> str:
        return f"{self.config.api_base_url}/bot{self.config.bot_token}/{method}"

    def _post(self, method: str, params: dict[str, str]) -> dict[str, Any]:
        data = urllib.parse.urlencode(params).encode("utf-8")
        request = urllib.request.Request(self._api_url(method), data=data, method="POST")
        request.add_header("Content-Type", "application/x-www-form-urlencoded")
        with urllib.request.urlopen(request, timeout=self.config.timeout_seconds) as response:
            return _loads_response(response.read())

    def _get(self, method: str, params: dict[str, str]) -> dict[str, Any]:
        url = f"{self._api_url(method)}?{urllib.parse.urlencode(params)}"
        with urllib.request.urlopen(url, timeout=self.config.timeout_seconds + int(params.get("timeout", "0"))) as response:
            return _loads_response(response.read())


class TelegramAdminStatusService:
    """Collect and render read-only admin status."""

    def __init__(
        self,
        *,
        project_dir: Path | None = None,
        run_command: RunCommand | None = None,
        question_stats_reader: QuestionStatsReader | None = None,
    ) -> None:
        self.project_dir = project_dir or PROJECT_DIR
        self.jobs_dir = self.project_dir / "data" / "jobs"
        self.run_command = run_command or _default_run_command
        self.question_stats_reader = question_stats_reader or self._read_question_stats

    def collect_snapshot(self) -> SiteStatusSnapshot:
        question_count = _question_count(self.question_stats_reader())
        job_counts, recent_errors = self._read_job_summary()
        web_service = self._command_summary(
            ["systemctl", "--user", "is-active", "anesthesia-exam-web.service"],
            ok_when_stdout=True,
        )
        web_http = self._web_http_status()
        openclaw_version = self._command_summary([str(self.project_dir / "scripts" / "openclaw.sh"), "--version"])
        mcp_raw = self._command_output([str(self.project_dir / "scripts" / "openclaw.sh"), "mcp", "list"])
        worker_timer = self._command_summary(
            ["systemctl", "--user", "is-active", "anesthesia-exam-openclaw-worker.timer"],
            ok_when_stdout=True,
        )
        return SiteStatusSnapshot(
            question_count=question_count,
            web_service=web_service,
            web_http=web_http,
            openclaw_version=openclaw_version,
            mcp_servers=_parse_mcp_servers(mcp_raw),
            worker_timer=worker_timer,
            job_counts=job_counts,
            recent_errors=recent_errors,
        )

    def build_status_text(self) -> str:
        return format_status_snapshot(self.collect_snapshot())

    def build_jobs_text(self) -> str:
        counts, recent_errors = self._read_job_summary()
        parts = ["OpenClaw jobs", _format_job_counts(counts)]
        if recent_errors:
            parts.append("recent errors:")
            parts.extend(f"- {error}" for error in recent_errors[:5])
        return "\n".join(parts)

    def build_errors_text(self) -> str:
        _, recent_errors = self._read_job_summary()
        if not recent_errors:
            return "Recent OpenClaw errors: none"
        return "\n".join(["Recent OpenClaw errors:", *[f"- {error}" for error in recent_errors[:10]]])

    def build_openclaw_text(self) -> str:
        version = self._command_summary([str(self.project_dir / "scripts" / "openclaw.sh"), "--version"])
        mcp_raw = self._command_output([str(self.project_dir / "scripts" / "openclaw.sh"), "mcp", "list"])
        model = self._command_summary([str(self.project_dir / "scripts" / "openclaw.sh"), "models", "status", "--plain"])
        servers = _parse_mcp_servers(mcp_raw)
        return "\n".join(
            [
                "OpenClaw",
                f"version: {version}",
                f"model: {model}",
                f"MCP: {', '.join(servers) if servers else 'none'}",
            ]
        )

    def build_web_text(self) -> str:
        service = self._command_summary(
            ["systemctl", "--user", "is-active", "anesthesia-exam-web.service"],
            ok_when_stdout=True,
        )
        http = self._web_http_status()
        return "\n".join(["Web", f"service: {service}", f"http: {http}", "url: http://127.0.0.1:8501"])

    def build_help_text(self) -> str:
        return "\n".join(
            [
                "Anesthesia Exam admin commands",
                "/status - site, OpenClaw, MCP, jobs summary",
                "/jobs - pending/error backlog summary",
                "/errors - recent worker/job errors",
                "/openclaw - OpenClaw version, model, MCP",
                "/web - web service and HTTP status",
                "/help - command list",
                "",
                "Read-only: Telegram cannot modify questions or run shell commands.",
            ]
        )

    def _read_question_stats(self) -> dict[str, Any]:
        from src.infrastructure.persistence.sqlite_question_repo import get_question_repository

        return get_question_repository().get_statistics()

    def _read_job_summary(self) -> tuple[dict[str, int], list[str]]:
        counts: dict[str, int] = {}
        errors: list[tuple[float, str]] = []
        if not self.jobs_dir.exists():
            return counts, []
        for path in sorted(self.jobs_dir.glob("*.json")):
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                counts["unreadable"] = counts.get("unreadable", 0) + 1
                continue
            status = str(payload.get("status") or "unknown").strip() or "unknown"
            counts[status] = counts.get(status, 0) + 1
            if status == "error":
                topic = str(payload.get("topic") or payload.get("job_id") or path.stem).strip()
                error = str(payload.get("error") or payload.get("error_msg") or payload.get("summary") or "").strip()
                errors.append((path.stat().st_mtime, f"{topic}: {error or 'error'}"))
        errors.sort(key=lambda item: item[0], reverse=True)
        return counts, [error for _, error in errors[:10]]

    def _command_summary(self, command: list[str], *, ok_when_stdout: bool = False) -> str:
        try:
            code, stdout, stderr = self.run_command(command, 10)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        text = (stdout or stderr or "").strip()
        if code == 0:
            if ok_when_stdout and text:
                return text.splitlines()[0].strip()
            return text.splitlines()[0].strip() if text else "ok"
        return f"error: {text or f'exit {code}'}"

    def _command_output(self, command: list[str]) -> str:
        try:
            code, stdout, stderr = self.run_command(command, 10)
        except Exception as exc:  # noqa: BLE001
            return f"error: {exc}"
        text = (stdout or stderr or "").strip()
        if code == 0:
            return text or "ok"
        return f"error: {text or f'exit {code}'}"

    def _web_http_status(self) -> str:
        code, stdout, stderr = self.run_command(
            ["curl", "-fsSI", "--max-time", "5", "http://127.0.0.1:8501"],
            8,
        )
        if code == 0:
            return "ok"
        return f"error: {(stderr or stdout or f'exit {code}').strip()}"


class TelegramNotifier:
    """Send admin notifications when Telegram is configured."""

    def __init__(self, config: TelegramAdminConfig, client: TelegramHttpClient | None = None) -> None:
        self.config = config
        self.client = client or TelegramHttpClient(config)

    @classmethod
    def from_env(cls) -> "TelegramNotifier":
        return cls(TelegramAdminConfig.from_env())

    def send_to_admins(self, text: str) -> int:
        if not self.config.is_configured:
            return 0
        sent = 0
        for chat_id in sorted(self.config.admin_chat_ids):
            try:
                self.client.send_message(chat_id, text)
                sent += 1
            except (OSError, urllib.error.URLError, TimeoutError) as exc:
                logger.warning("telegram_admin_send_failed", chat_id=chat_id, error=str(exc))
        return sent

    def send_status_report(self, status_service: TelegramAdminStatusService | None = None) -> int:
        if not self.config.is_configured:
            return 0
        service = status_service or TelegramAdminStatusService()
        return self.send_to_admins(service.build_status_text())

    def send_worker_result(self, result: Mapping[str, Any]) -> int:
        if not self.config.is_configured:
            return 0
        return self.send_to_admins(format_worker_notification(result))


class TelegramAdminBot:
    """Read-only Telegram command router for admin chats."""

    def __init__(
        self,
        *,
        config: TelegramAdminConfig,
        client: TelegramHttpClient,
        status_service: TelegramAdminStatusService,
    ) -> None:
        self.config = config
        self.client = client
        self.status_service = status_service
        self._current_chat_id: str | None = None

    @classmethod
    def from_env(cls) -> "TelegramAdminBot":
        config = TelegramAdminConfig.from_env()
        return cls(
            config=config,
            client=TelegramHttpClient(config),
            status_service=TelegramAdminStatusService(),
        )

    def handle_update(self, update: Mapping[str, Any]) -> bool:
        message = update.get("message") or update.get("edited_message")
        if not isinstance(message, Mapping):
            return False
        chat = message.get("chat")
        if not isinstance(chat, Mapping):
            return False
        chat_id = chat.get("id")
        if not self.config.is_admin(chat_id):
            logger.warning("telegram_admin_unauthorized_chat", chat_id=str(chat_id))
            return False
        text = str(message.get("text") or "").strip()
        if not text:
            return False
        previous_chat_id = self._current_chat_id
        self._current_chat_id = str(chat_id)
        try:
            response = self._route(text)
        finally:
            self._current_chat_id = previous_chat_id
        self.client.send_message(str(chat_id), response)
        return True

    def poll_once(self, *, offset: int | None = None) -> int | None:
        if not self.config.is_configured:
            logger.info("telegram_admin_bot_disabled")
            return offset
        next_offset = offset
        for update in self.client.get_updates(offset=offset, timeout_seconds=self.config.poll_timeout_seconds):
            update_id = update.get("update_id")
            if isinstance(update_id, int):
                next_offset = update_id + 1
            self.handle_update(update)
        return next_offset

    def poll_forever(self, *, offset: int | None = None, sleep_seconds: float = 2.0) -> None:
        next_offset = offset
        while True:
            try:
                next_offset = self.poll_once(offset=next_offset)
            except Exception as exc:  # noqa: BLE001
                logger.warning("telegram_admin_bot_poll_failed", error=str(exc))
                time.sleep(sleep_seconds)

    def _route(self, text: str) -> str:
        command = text.split()[0].split("@", 1)[0].lower()
        if command == "/ask":
            return self._ask_openclaw(text, chat_id=str(self._current_chat_id or "admin"))
        routes: dict[str, Callable[[], str]] = {
            "/status": self.status_service.build_status_text,
            "/jobs": self.status_service.build_jobs_text,
            "/errors": self.status_service.build_errors_text,
            "/openclaw": self.status_service.build_openclaw_text,
            "/web": self.status_service.build_web_text,
            "/help": self.status_service.build_help_text,
            "/start": self.status_service.build_help_text,
        }
        return routes.get(command, self.status_service.build_help_text)()

    def _ask_openclaw(self, text: str, *, chat_id: str) -> str:
        if not self.config.allow_openclaw_ask:
            return "OpenClaw Telegram ask is disabled. Set TELEGRAM_OPENCLAW_ASK_ENABLED=true to enable read-only admin asks."
        question = text.partition(" ")[2].strip()
        if not question:
            return "Usage: /ask <read-only admin question>"
        prompt = "\n".join(
            [
                "你是 anesthesia-exam 網站的 OpenClaw 考題管理員。",
                "這是 Telegram 管理員的 read-only 詢問；不得新增、修改、刪除題庫資料，不得執行 destructive command。",
                "請根據你可見的網站、OpenClaw、MCP 與題庫管理上下文回答。",
                "",
                f"管理員問題: {question}",
            ]
        )
        config = AgentProviderConfig.load(
            project_dir=PROJECT_DIR,
            crush_config_path=PROJECT_DIR / "crush.json",
            provider_override="openclaw",
        )
        provider = create_agent_provider(config)
        return provider.run(prompt, session_key=build_openclaw_session_key("telegram", chat_id))


def format_status_snapshot(snapshot: SiteStatusSnapshot) -> str:
    servers = ", ".join(snapshot.mcp_servers) if snapshot.mcp_servers else "none"
    errors = "\n".join(f"- {error}" for error in snapshot.recent_errors[:5]) if snapshot.recent_errors else "- none"
    return "\n".join(
        [
            "Anesthesia Exam admin status",
            f"time: {snapshot.timestamp}",
            f"web_service: {snapshot.web_service}",
            f"web_http: {snapshot.web_http}",
            f"openclaw: {snapshot.openclaw_version}",
            f"MCP: {servers}",
            f"worker_timer: {snapshot.worker_timer}",
            f"questions: {snapshot.question_count}",
            f"jobs: {_format_job_counts(snapshot.job_counts)}",
            "recent_errors:",
            errors,
        ]
    )


def format_worker_notification(result: Mapping[str, Any]) -> str:
    errors = result.get("errors")
    if not isinstance(errors, list):
        errors = []
    error_text = "\n".join(f"- {str(error)}" for error in errors[:5]) if errors else "- none"
    return "\n".join(
        [
            "OpenClaw worker report",
            f"success: {bool(result.get('success', not errors))}",
            f"pending_jobs: {int(result.get('pending_jobs') or 0)}",
            f"processed_jobs: {int(result.get('processed_jobs') or 0)}",
            f"generated_questions: {int(result.get('generated_questions') or 0)}",
            f"skipped_jobs: {int(result.get('skipped_jobs') or 0)}",
            "errors:",
            error_text,
        ]
    )


def _default_run_command(command: list[str], timeout_seconds: int) -> tuple[int, str, str]:
    completed = subprocess.run(
        command,
        cwd=PROJECT_DIR,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        check=False,
    )
    return completed.returncode, completed.stdout, completed.stderr


def _question_count(stats: Mapping[str, Any]) -> int:
    for key in ("total", "question_count", "total_questions", "count"):
        value = stats.get(key)
        if isinstance(value, int):
            return max(0, value)
        if isinstance(value, str) and value.strip().isdigit():
            return max(0, int(value.strip()))
    return 0


def _parse_mcp_servers(raw: str) -> list[str]:
    servers: list[str] = []
    for line in raw.splitlines():
        cleaned = line.strip()
        if not cleaned or cleaned.lower().startswith("error:"):
            continue
        if cleaned.startswith("-"):
            cleaned = cleaned[1:].strip()
        name = cleaned.split()[0].strip(",:")
        if name and name not in servers:
            servers.append(name)
    return servers


def _format_job_counts(counts: Mapping[str, int]) -> str:
    if not counts:
        return "none"
    preferred = ["pending", "picked", "done", "error", "unreadable", "unknown"]
    keys = [key for key in preferred if key in counts] + sorted(key for key in counts if key not in preferred)
    return " ".join(f"{key}={counts[key]}" for key in keys)


def _positive_int(value: object, default: int) -> int:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _chunk_text(text: str, limit: int = 3900) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current = text
    while len(current) > limit:
        split_at = current.rfind("\n", 0, limit)
        if split_at < 1:
            split_at = limit
        chunks.append(current[:split_at])
        current = current[split_at:].lstrip()
    if current:
        chunks.append(current)
    return chunks


def _loads_response(raw: bytes) -> dict[str, Any]:
    payload = json.loads(raw.decode("utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Telegram API returned non-object JSON")
    if payload.get("ok") is False:
        raise RuntimeError(str(payload.get("description") or "Telegram API error"))
    return payload
