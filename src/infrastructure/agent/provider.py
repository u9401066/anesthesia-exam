"""Agent Provider 抽象層

目的：讓上層（Streamlit）不再綁定單一 Agent（如 Crush）。
可透過設定切換底層 provider：
- crush: 本地 Crush CLI
- opencode: OpenCode CLI + opencode.json（Ollama/自訂 LLM）
- copilot-sdk: HTTP API（由 EXAM_COPILOT_SDK_ENDPOINT 指定）
- codex: OpenAI API（Codex / GPT-5 family）
- openclaw: Repo-local OpenClaw CLI + OpenAI-compatible custom models
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from src.application.services.openclaw_session_keys import build_openclaw_session_key
from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


def _safe_int(value: object, default: int, min_value: Optional[int] = None, max_value: Optional[int] = None) -> int:
    """Parse an environment integer safely and clamp to an optional range."""
    if isinstance(value, int) and not isinstance(value, bool):
        candidate = value
    elif isinstance(value, float) and not isinstance(value, bool):
        candidate = int(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return default
        try:
            candidate = int(stripped)
        except ValueError:
            return default
    else:
        return default

    if min_value is not None and candidate < min_value:
        return min_value
    if max_value is not None and candidate > max_value:
        return max_value
    return candidate


def _resolve_crush_executable_path() -> str:
    explicit = os.getenv("EXAM_CRUSH_PATH")
    if explicit:
        return explicit.strip()

    exe = shutil.which("crush")
    if exe:
        return exe

    repo_root = Path(__file__).resolve().parents[3]
    bundled = repo_root / "crush" / ("crush.exe" if os.name == "nt" else "crush")
    if bundled.exists():
        return str(bundled)

    return "crush"


def _terminate_process(process: subprocess.Popen[str], *, timeout: float = 2.0) -> None:
    """Terminate a process safely and force-kill on timeout."""
    if process.poll() is not None:
        return
    try:
        process.terminate()
        process.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        try:
            process.kill()
            process.wait(timeout=timeout)
        except Exception:
            pass
    except Exception:
        pass


def _iter_process_lines(process: subprocess.Popen[str], timeout_sec: int) -> Iterator[str]:
    watchdog = None
    if timeout_sec > 0:
        watchdog = threading.Timer(timeout_sec, _terminate_process, args=(process,))
        watchdog.daemon = True
        watchdog.start()

    try:
        assert process.stdout is not None
        for line in iter(process.stdout.readline, ""):
            if not line:
                break
            yield line
    finally:
        if watchdog is not None and watchdog.is_alive():
            watchdog.cancel()


def _dedupe_strings(values: list[str]) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = str(value or "").strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


def collect_opencode_available_models(config: dict) -> list[str]:
    """Return all provider/model refs from an OpenCode config."""
    available_models: list[str] = []
    providers = config.get("provider", {}) or {}

    for provider_id, provider_cfg in providers.items():
        raw_models = (provider_cfg or {}).get("models") or {}
        if isinstance(raw_models, dict):
            items = raw_models.items()
        elif isinstance(raw_models, list):
            items = [
                (str(model.get("id") or "").strip(), model)
                for model in raw_models
                if isinstance(model, dict)
            ]
        else:
            items = []

        for model_id, _model_cfg in items:
            model_id = str(model_id or "").strip()
            if not model_id:
                continue
            available_models.append(f"{provider_id}/{model_id}")

    return _dedupe_strings(available_models)


def resolve_opencode_default_model(config: dict) -> str | None:
    """Resolve the top-level default model or fall back to the first configured one."""
    explicit_model = str(config.get("model") or "").strip()
    if explicit_model:
        return explicit_model

    available_models = collect_opencode_available_models(config)
    return available_models[0] if available_models else None


def collect_openclaw_available_models(config: dict) -> list[str]:
    """Return all provider/model refs from an OpenClaw config."""
    available_models: list[str] = []
    model_config = config.get("models") or {}
    providers = model_config.get("providers") or {}

    for provider_id, provider_cfg in providers.items():
        raw_models = (provider_cfg or {}).get("models") or {}
        if isinstance(raw_models, dict):
            items = raw_models.items()
        elif isinstance(raw_models, list):
            items = [
                (str(model.get("id") or "").strip(), model)
                for model in raw_models
                if isinstance(model, dict)
            ]
        else:
            items = []

        for model_id, _model_cfg in items:
            model_id = str(model_id or "").strip()
            if not model_id:
                continue
            available_models.append(f"{provider_id}/{model_id}")

    return _dedupe_strings(available_models)


def resolve_openclaw_default_model(config: dict) -> str | None:
    """Resolve the OpenClaw primary model or fall back to the first configured one."""
    agents = config.get("agents") or {}
    defaults = agents.get("defaults") or {}
    default_model = defaults.get("model") or {}
    if isinstance(default_model, dict):
        primary_model = str(default_model.get("primary") or "").strip()
        if primary_model:
            return primary_model

    available_models = collect_openclaw_available_models(config)
    return available_models[0] if available_models else None


def extract_openclaw_text(payload: dict) -> str:
    """Extract model text from an OpenClaw JSON response."""
    nested_result = payload.get("result")
    if isinstance(nested_result, dict):
        nested_text = extract_openclaw_text(nested_result)
        if nested_text:
            return nested_text

    meta = payload.get("meta") or {}
    for key in ("finalAssistantVisibleText", "finalAssistantRawText"):
        final_text = meta.get(key)
        if isinstance(final_text, str) and final_text.strip():
            return final_text.strip()

    outputs = payload.get("payloads") or payload.get("outputs") or []
    parts: list[str] = []

    for output in outputs:
        if not isinstance(output, dict):
            continue
        if output.get("isError") or output.get("isReasoning"):
            continue
        text = output.get("text")
        if isinstance(text, str) and text.strip():
            parts.append(text.strip())

    if parts:
        return "\n\n".join(parts).strip()

    fallback_text = payload.get("text")
    if isinstance(fallback_text, str):
        return fallback_text.strip()

    return ""


def extract_last_json_object(raw_text: str) -> dict | None:
    """Extract the last JSON object from mixed stdout/stderr text."""
    decoder = json.JSONDecoder()
    index = 0
    last_object: dict | None = None

    while index < len(raw_text):
        start = raw_text.find("{", index)
        if start < 0:
            break
        try:
            payload, end = decoder.raw_decode(raw_text[start:])
        except json.JSONDecodeError:
            index = start + 1
            continue

        if isinstance(payload, dict):
            last_object = payload
        index = start + max(end, 1)

    return last_object


def extract_openai_text_content(payload: object) -> str:
    """Extract text from string or structured OpenAI content arrays."""
    if isinstance(payload, str):
        return payload

    if not isinstance(payload, list):
        return ""

    parts: list[str] = []
    for item in payload:
        if isinstance(item, str):
            parts.append(item)
            continue
        if not isinstance(item, dict):
            continue
        part_type = str(item.get("type") or "").strip().lower()
        if part_type in {"text", "output_text", "input_text"}:
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts)


def extract_responses_api_text(payload: dict) -> str:
    """Extract assistant text from a Responses API payload."""
    output_text = payload.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text

    parts: list[str] = []
    for item in payload.get("output") or []:
        if not isinstance(item, dict):
            continue
        item_type = str(item.get("type") or "").strip().lower()
        if item_type == "message":
            text = extract_openai_text_content(item.get("content"))
            if text:
                parts.append(text)
            continue
        if item_type in {"output_text", "text"}:
            text = item.get("text")
            if isinstance(text, str) and text:
                parts.append(text)
    return "".join(parts).strip()


def extract_chat_completion_text(payload: dict) -> str:
    """Extract assistant text from a Chat Completions payload."""
    choices = payload.get("choices") or []
    if not choices:
        return ""

    first_choice = choices[0] or {}
    message = first_choice.get("message") or {}
    content = message.get("content")
    text = extract_openai_text_content(content)
    if text:
        return text
    if isinstance(content, str):
        return content
    return str(message.get("reasoning_content") or "")


def iter_sse_data_messages(response) -> Iterator[str]:
    """Yield complete SSE data payloads from a streaming HTTP response."""
    data_lines: list[str] = []

    for raw_line in response:
        if isinstance(raw_line, bytes):
            line = raw_line.decode("utf-8", errors="replace")
        else:
            line = str(raw_line)
        stripped = line.rstrip("\r\n")

        if not stripped:
            if data_lines:
                yield "\n".join(data_lines)
                data_lines = []
            continue

        if stripped.startswith("data:"):
            data_lines.append(stripped[5:].lstrip())

    if data_lines:
        yield "\n".join(data_lines)


class IAgentProvider(Protocol):
    """Agent provider 介面"""

    name: str

    def is_available(self) -> tuple[bool, str]: ...

    def run(self, prompt: str, session_key: Optional[str] = None) -> str: ...

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]: ...


@dataclass
class AgentProviderConfig:
    """Provider 設定"""

    provider: str
    working_dir: Path
    model: Optional[str] = None
    timeout: int = 120

    crush_executable: Optional[str] = None
    opencode_executable: Optional[str] = None
    opencode_model: Optional[str] = None
    copilot_sdk_endpoint: Optional[str] = None
    copilot_sdk_token: Optional[str] = None
    codex_model: Optional[str] = None
    openclaw_executable: Optional[str] = None
    openclaw_model: Optional[str] = None
    openclaw_config_path: Optional[Path] = None
    openclaw_mode: Optional[str] = None
    openclaw_agent_id: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_api_key: Optional[str] = None
    openai_organization: Optional[str] = None
    openai_project: Optional[str] = None

    @classmethod
    def load(
        cls,
        project_dir: Path,
        crush_config_path: Path,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> "AgentProviderConfig":
        provider = (provider_override or os.getenv("EXAM_AGENT_PROVIDER", "crush")).strip().lower()
        if provider == "openclaw":
            timeout = _safe_int(
                os.getenv("EXAM_OPENCLAW_TIMEOUT") or os.getenv("EXAM_AGENT_TIMEOUT"),
                default=300,
                min_value=1,
                max_value=3600,
            )
        else:
            timeout = _safe_int(os.getenv("EXAM_AGENT_TIMEOUT"), default=120, min_value=1, max_value=3600)

        model = (model_override or os.getenv("EXAM_AGENT_MODEL") or "").strip() or None
        if model is None and crush_config_path.exists():
            try:
                with open(crush_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                model = data.get("agents", {}).get("coder", {}).get("model")
            except Exception:
                model = None

        crush_executable = _resolve_crush_executable_path()

        # OpenCode: 從 opencode.json 讀取模型設定
        opencode_executable = os.getenv("EXAM_OPENCODE_PATH") or shutil.which("opencode")
        opencode_model = model_override or os.getenv("EXAM_OPENCODE_MODEL")
        if not opencode_model:
            opencode_json = project_dir / "opencode.json"
            if opencode_json.exists():
                try:
                    with open(opencode_json, "r", encoding="utf-8") as f:
                        oc_data = json.load(f)
                    opencode_model = resolve_opencode_default_model(oc_data)
                except Exception:
                    pass

        default_openclaw_config_path = project_dir / "vendor" / "openclaw-state" / "openclaw.json"
        openclaw_config_path = (
            os.getenv("EXAM_OPENCLAW_CONFIG_PATH")
            or os.getenv("OPENCLAW_CONFIG_PATH")
            or str(default_openclaw_config_path)
        ).strip()
        openclaw_executable = (
            os.getenv("EXAM_OPENCLAW_PATH")
            or str(project_dir / "scripts" / "openclaw.sh")
        ).strip()
        openclaw_model = (
            model_override
            or os.getenv("EXAM_OPENCLAW_MODEL")
            or os.getenv("EXAM_AGENT_MODEL")
            or ""
        ).strip()
        if not openclaw_model:
            try:
                openclaw_path = Path(openclaw_config_path)
                if openclaw_path.exists():
                    with open(openclaw_path, "r", encoding="utf-8") as f:
                        openclaw_data = json.load(f)
                    openclaw_model = resolve_openclaw_default_model(openclaw_data) or ""
            except Exception:
                pass
        openclaw_mode = (os.getenv("EXAM_OPENCLAW_MODE") or "agent").strip().lower() or "agent"
        if openclaw_mode not in {"agent", "infer"}:
            openclaw_mode = "agent"
        openclaw_agent_id = (os.getenv("EXAM_OPENCLAW_AGENT_ID") or "main").strip() or "main"

        codex_model = (
            model_override
            or os.getenv("EXAM_CODEX_MODEL")
            or os.getenv("EXAM_OPENAI_MODEL")
            or os.getenv("EXAM_AGENT_MODEL")
            or "gpt-5.3-codex"
        ).strip()
        openai_base_url = (
            os.getenv("EXAM_OPENAI_BASE_URL")
            or os.getenv("OPENAI_BASE_URL")
            or "https://api.openai.com/v1"
        ).strip()
        openai_api_key = (os.getenv("EXAM_OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip()
        openai_organization = (
            os.getenv("EXAM_OPENAI_ORGANIZATION")
            or os.getenv("OPENAI_ORGANIZATION")
            or ""
        ).strip()
        openai_project = (os.getenv("EXAM_OPENAI_PROJECT") or os.getenv("OPENAI_PROJECT") or "").strip()

        return cls(
            provider=provider,
            working_dir=project_dir,
            model=model,
            timeout=timeout,
            crush_executable=crush_executable,
            opencode_executable=opencode_executable,
            opencode_model=opencode_model,
            copilot_sdk_endpoint=os.getenv("EXAM_COPILOT_SDK_ENDPOINT"),
            copilot_sdk_token=os.getenv("EXAM_COPILOT_SDK_TOKEN"),
            codex_model=codex_model or None,
            openclaw_executable=openclaw_executable or None,
            openclaw_model=openclaw_model or None,
            openclaw_config_path=Path(openclaw_config_path) if openclaw_config_path else None,
            openclaw_mode=openclaw_mode,
            openclaw_agent_id=openclaw_agent_id,
            openai_base_url=openai_base_url or None,
            openai_api_key=openai_api_key or None,
            openai_organization=openai_organization or None,
            openai_project=openai_project or None,
        )


class CrushAgentProvider:
    """Crush CLI provider"""

    name = "crush"

    def __init__(self, config: AgentProviderConfig):
        self.config = config

    def _build_command(self, prompt: str) -> list[str]:
        cmd = [str(self.config.crush_executable), "run", "--cwd", str(self.config.working_dir)]
        if self.config.model:
            cmd.extend(["--model", self.config.model])
        cmd.append(prompt)
        return cmd

    def is_available(self) -> tuple[bool, str]:
        executable = self.config.crush_executable
        if not executable:
            return False, "找不到 Crush 可執行檔"

        if not Path(executable).exists() and shutil.which(executable) is None:
            return False, f"Crush 不存在：{executable}"

        try:
            result = subprocess.run(
                [str(executable), "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                return True, "可用"
            return False, "Crush 啟動失敗"
        except Exception as e:
            return False, f"Crush 檢查失敗：{e}"

    def run(self, prompt: str, session_key: Optional[str] = None) -> str:
        _ = session_key
        log = logger.bind(provider="crush", model=self.config.model)
        log.info("agent_run_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        result = subprocess.run(
            self._build_command(prompt),
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
            cwd=str(self.config.working_dir),
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            log.error("agent_run_error", returncode=result.returncode, duration_ms=elapsed_ms)
            raise RuntimeError(result.stderr or "Crush 執行失敗")
        log.info("agent_run_done", duration_ms=elapsed_ms, output_len=len(result.stdout))
        return result.stdout.strip()

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]:
        _ = session_key
        log = logger.bind(provider="crush", model=self.config.model)
        log.info("agent_stream_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        total_chars = 0

        process = subprocess.Popen(
            self._build_command(prompt),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(self.config.working_dir),
            encoding="utf-8",
            errors="replace",
        )

        try:
            for line in _iter_process_lines(process, self.config.timeout):
                if line:
                    total_chars += len(line)
                    yield line

            process.wait()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if process.returncode != 0:
                log.error("agent_stream_error", returncode=process.returncode, duration_ms=elapsed_ms)
                raise RuntimeError(f"Crush 結束碼：{process.returncode}")
            log.info("agent_stream_done", duration_ms=elapsed_ms, total_chars=total_chars)
        finally:
            _terminate_process(process)


class OpenCodeAgentProvider:
    """OpenCode CLI provider（使用 opencode run 指令 + opencode.json 設定）"""

    name = "opencode"

    def __init__(self, config: AgentProviderConfig):
        self.config = config

    def _get_executable(self) -> str:
        return self.config.opencode_executable or "opencode"

    def _build_command(self, prompt: str) -> list[str]:
        exe = self._get_executable()
        cmd = [exe, "run"]
        model = self.config.opencode_model
        if model:
            cmd.extend(["--model", model])
        cmd.extend(["--format", "default"])
        cmd.append(prompt)
        return cmd

    def is_available(self) -> tuple[bool, str]:
        exe = self._get_executable()
        if shutil.which(exe) is None and not Path(exe).exists():
            return False, f"找不到 OpenCode：{exe}"

        try:
            result = subprocess.run(
                [exe, "--version"],
                capture_output=True,
                text=True,
                timeout=5,
                encoding="utf-8",
                errors="replace",
            )
            if result.returncode == 0:
                version = result.stdout.strip()
                model = self.config.opencode_model or "(default)"
                return True, f"v{version}, model={model}"
            return False, "OpenCode 啟動失敗"
        except Exception as e:
            return False, f"OpenCode 檢查失敗：{e}"

    def run(self, prompt: str, session_key: Optional[str] = None) -> str:
        _ = session_key
        log = logger.bind(provider="opencode", model=self.config.opencode_model)
        log.info("agent_run_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        result = subprocess.run(
            self._build_command(prompt),
            capture_output=True,
            text=True,
            timeout=self.config.timeout,
            cwd=str(self.config.working_dir),
            encoding="utf-8",
            errors="replace",
        )
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        if result.returncode != 0:
            log.error("agent_run_error", returncode=result.returncode, duration_ms=elapsed_ms)
            raise RuntimeError(result.stderr or "OpenCode 執行失敗")
        log.info("agent_run_done", duration_ms=elapsed_ms, output_len=len(result.stdout))
        return result.stdout.strip()

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]:
        _ = session_key
        log = logger.bind(provider="opencode", model=self.config.opencode_model)
        log.info("agent_stream_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        total_chars = 0
        mcp_calls_detected = 0

        process = subprocess.Popen(
            self._build_command(prompt),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            cwd=str(self.config.working_dir),
            encoding="utf-8",
            errors="replace",
        )

        try:
            for line in _iter_process_lines(process, self.config.timeout):
                if line:
                    total_chars += len(line)
                    # 偵測 MCP 工具調用跡象
                    if "exam_save_question" in line or "exam_" in line:
                        mcp_calls_detected += 1
                        log.info("mcp_call_detected", line=line.strip()[:200])
                    yield line

            process.wait()
            elapsed_ms = int((time.monotonic() - t0) * 1000)
            if process.returncode != 0:
                log.error("agent_stream_error", returncode=process.returncode, duration_ms=elapsed_ms)
                raise RuntimeError(f"OpenCode 結束碼：{process.returncode}")
            log.info("agent_stream_done", duration_ms=elapsed_ms, total_chars=total_chars, mcp_calls=mcp_calls_detected)
        finally:
            _terminate_process(process)


class CopilotSdkAgentProvider:
    """Copilot SDK provider（HTTP endpoint）"""

    name = "copilot-sdk"

    def __init__(self, config: AgentProviderConfig):
        self.config = config

    def is_available(self) -> tuple[bool, str]:
        if not self.config.copilot_sdk_endpoint:
            return False, "未設定 EXAM_COPILOT_SDK_ENDPOINT"
        return True, "可用"

    def _call_api(self, prompt: str) -> str:
        if not self.config.copilot_sdk_endpoint:
            raise RuntimeError("未設定 EXAM_COPILOT_SDK_ENDPOINT")

        payload = {
            "prompt": prompt,
            "model": self.config.model,
        }
        body = json.dumps(payload).encode("utf-8")

        headers = {
            "Content-Type": "application/json",
        }
        if self.config.copilot_sdk_token:
            headers["Authorization"] = f"Bearer {self.config.copilot_sdk_token}"

        req = request.Request(
            self.config.copilot_sdk_endpoint,
            data=body,
            headers=headers,
            method="POST",
        )

        try:
            with request.urlopen(req, timeout=self.config.timeout) as resp:
                raw = resp.read().decode("utf-8", errors="replace")
        except HTTPError as e:
            raise RuntimeError(f"Copilot SDK HTTP 錯誤：{e.code}") from e
        except URLError as e:
            raise RuntimeError(f"Copilot SDK 連線失敗：{e.reason}") from e

        try:
            data = json.loads(raw)
            return data.get("text") or data.get("content") or raw
        except json.JSONDecodeError:
            return raw

    def run(self, prompt: str, session_key: Optional[str] = None) -> str:
        _ = session_key
        return self._call_api(prompt)

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]:
        _ = session_key
        yield self._call_api(prompt)


class CodexAgentProvider:
    """OpenAI API provider for Codex / GPT-5 family models."""

    name = "codex"
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    DEFAULT_MODEL = "gpt-5.3-codex"

    def __init__(self, config: AgentProviderConfig):
        self.config = config

    def _get_model(self) -> str:
        return (
            self.config.codex_model
            or self.config.model
            or self.DEFAULT_MODEL
        )

    def _get_base_url(self) -> str:
        return (self.config.openai_base_url or self.DEFAULT_BASE_URL).rstrip("/")

    def _build_headers(self) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
        }
        if self.config.openai_api_key:
            headers["Authorization"] = f"Bearer {self.config.openai_api_key}"
        if self.config.openai_organization:
            headers["OpenAI-Organization"] = self.config.openai_organization
        if self.config.openai_project:
            headers["OpenAI-Project"] = self.config.openai_project
        return headers

    def _open(self, url: str, payload: dict | None = None):
        data = None
        method = "GET"
        if payload is not None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            method = "POST"
        req = request.Request(url, data=data, headers=self._build_headers(), method=method)
        return request.urlopen(req, timeout=self.config.timeout)

    def _run_via_responses(self, prompt: str) -> str:
        payload = {
            "model": self._get_model(),
            "input": prompt,
        }
        with self._open(f"{self._get_base_url()}/responses", payload) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Codex responses 回應非 JSON：{raw[:160]}") from exc
        return extract_responses_api_text(data).strip()

    def _run_via_chat_completions(self, prompt: str) -> str:
        payload = {
            "model": self._get_model(),
            "messages": [
                {"role": "user", "content": prompt},
            ],
        }
        with self._open(f"{self._get_base_url()}/chat/completions", payload) as response:
            raw = response.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"Codex chat-completions 回應非 JSON：{raw[:160]}") from exc
        return extract_chat_completion_text(data).strip()

    def _stream_via_responses(self, prompt: str) -> Iterator[str]:
        payload = {
            "model": self._get_model(),
            "input": prompt,
            "stream": True,
        }
        with self._open(f"{self._get_base_url()}/responses", payload) as response:
            for message in iter_sse_data_messages(response):
                if message == "[DONE]":
                    return
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    continue
                event_type = str(event.get("type") or "").strip()
                if event_type == "response.output_text.delta":
                    delta = str(event.get("delta") or "")
                    if delta:
                        yield delta
                elif event_type == "error":
                    raise RuntimeError(str(event.get("message") or "Codex Responses stream error"))

    def _stream_via_chat_completions(self, prompt: str) -> Iterator[str]:
        payload = {
            "model": self._get_model(),
            "messages": [
                {"role": "user", "content": prompt},
            ],
            "stream": True,
        }
        with self._open(f"{self._get_base_url()}/chat/completions", payload) as response:
            for message in iter_sse_data_messages(response):
                if message == "[DONE]":
                    return
                try:
                    event = json.loads(message)
                except json.JSONDecodeError:
                    continue
                choices = event.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
                content = delta.get("content")
                if isinstance(content, str) and content:
                    yield content
                    continue
                structured = extract_openai_text_content(content)
                if structured:
                    yield structured

    def is_available(self) -> tuple[bool, str]:
        if not self.config.openai_api_key:
            return False, "未設定 EXAM_OPENAI_API_KEY / OPENAI_API_KEY"

        model = self._get_model()
        try:
            with self._open(f"{self._get_base_url()}/models") as response:
                if getattr(response, "status", 200) < 400:
                    return True, f"可用, model={model}"
            return False, "OpenAI API 狀態檢查失敗"
        except HTTPError as e:
            if e.code in {401, 403}:
                return False, f"OpenAI 驗證失敗（HTTP {e.code}）"
            return False, f"OpenAI API HTTP 錯誤：{e.code}"
        except URLError as e:
            return False, f"OpenAI API 連線失敗：{e.reason}"
        except Exception as e:  # noqa: BLE001
            return False, f"Codex 檢查失敗：{e}"

    def run(self, prompt: str, session_key: Optional[str] = None) -> str:
        _ = session_key
        log = logger.bind(provider="codex", model=self._get_model())
        log.info("agent_run_start", prompt_len=len(prompt))
        t0 = time.monotonic()

        last_error: Exception | None = None
        for runner in (self._run_via_responses, self._run_via_chat_completions):
            try:
                output = runner(prompt).strip()
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                if output:
                    log.info("agent_run_done", duration_ms=elapsed_ms, output_len=len(output))
                    return output
                last_error = RuntimeError("Codex 回傳空內容")
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                log.warning("codex_run_candidate_failed", error=str(exc))

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.error("agent_run_error", duration_ms=elapsed_ms, error=str(last_error))
        raise RuntimeError(f"Codex 執行失敗：{last_error}")

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]:
        _ = session_key
        log = logger.bind(provider="codex", model=self._get_model())
        log.info("agent_stream_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        total_chars = 0
        last_error: Exception | None = None

        for streamer in (self._stream_via_responses, self._stream_via_chat_completions):
            emitted = False
            try:
                for chunk in streamer(prompt):
                    if not chunk:
                        continue
                    emitted = True
                    total_chars += len(chunk)
                    yield chunk
                elapsed_ms = int((time.monotonic() - t0) * 1000)
                log.info("agent_stream_done", duration_ms=elapsed_ms, total_chars=total_chars)
                return
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                if emitted:
                    elapsed_ms = int((time.monotonic() - t0) * 1000)
                    log.error("agent_stream_error", duration_ms=elapsed_ms, error=str(exc))
                    raise RuntimeError(f"Codex 串流失敗：{exc}") from exc
                log.warning("codex_stream_candidate_failed", error=str(exc))

        elapsed_ms = int((time.monotonic() - t0) * 1000)
        log.error("agent_stream_error", duration_ms=elapsed_ms, error=str(last_error))
        raise RuntimeError(f"Codex 串流失敗：{last_error}")


class OpenClawAgentProvider:
    """Repo-local OpenClaw CLI provider."""

    name = "openclaw"
    DEFAULT_MODEL = "gb10/Qwen3.5-122B-A10B-Q5_K_M-00001-of-00003.gguf"

    def __init__(self, config: AgentProviderConfig):
        self.config = config

    def _get_executable(self) -> str:
        return self.config.openclaw_executable or "openclaw"

    def _get_model(self) -> str:
        return self.config.openclaw_model or self.config.model or self.DEFAULT_MODEL

    def _get_mode(self) -> str:
        return (self.config.openclaw_mode or "agent").strip().lower() or "agent"

    def _get_agent_id(self) -> str:
        return (self.config.openclaw_agent_id or "main").strip() or "main"

    def _build_infer_command(self, prompt: str) -> list[str]:
        return [
            self._get_executable(),
            "infer",
            "model",
            "run",
            "--local",
            "--model",
            self._get_model(),
            "--prompt",
            prompt,
            "--json",
        ]

    def _default_session_key(self) -> str:
        return build_openclaw_session_key("site-default", agent_id=self._get_agent_id())

    def _build_agent_command(self, prompt: str, session_key: Optional[str] = None) -> list[str]:
        return [
            self._get_executable(),
            "agent",
            "--agent",
            self._get_agent_id(),
            "--session-key",
            (session_key or self._default_session_key()),
            "--json",
            "--message",
            prompt,
        ]

    def _build_command(self, prompt: str, session_key: Optional[str] = None) -> list[str]:
        if self._get_mode() == "infer":
            return self._build_infer_command(prompt)
        return self._build_agent_command(prompt, session_key=session_key)

    def _run_cli(self, args: list[str], *, timeout: int) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(self.config.working_dir),
            encoding="utf-8",
            errors="replace",
        )

    def is_available(self) -> tuple[bool, str]:
        exe = self._get_executable()
        if shutil.which(exe) is None and not Path(exe).exists():
            return False, f"找不到 OpenClaw：{exe}"

        mode = self._get_mode()
        config_path = self.config.openclaw_config_path
        if mode == "agent" and config_path and not config_path.exists():
            return False, f"找不到 OpenClaw 設定：{config_path}"
        if mode == "agent" and config_path:
            try:
                config_payload = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                return False, f"OpenClaw 設定無法解析：{exc}"
            agents = config_payload.get("agents") or {}
            agent_id = self._get_agent_id()
            if agent_id not in agents and agent_id != "main":
                return False, f"OpenClaw 設定缺少 agent：{agent_id}"
            if not resolve_openclaw_default_model(config_payload):
                return False, "OpenClaw 設定缺少可用模型"

        try:
            result = self._run_cli([exe, "models", "status", "--plain"], timeout=10)
        except Exception as e:  # noqa: BLE001
            return False, f"OpenClaw 檢查失敗：{e}"

        if result.returncode != 0:
            reason = (result.stderr or result.stdout or "OpenClaw 狀態檢查失敗").strip()
            return False, reason

        current_model = ""
        for line in (result.stdout or "").splitlines():
            if line.strip():
                current_model = line.strip()
        if mode == "agent":
            return True, f"可用, mode=agent, agent={self._get_agent_id()}, model={current_model or self._get_model()}"
        return True, f"可用, mode=infer, model={current_model or self._get_model()}"

    def run(self, prompt: str, session_key: Optional[str] = None) -> str:
        resolved_session_key = session_key or self._default_session_key()
        log = logger.bind(provider="openclaw", model=self._get_model(), session_key=resolved_session_key)
        log.info("agent_run_start", prompt_len=len(prompt))
        t0 = time.monotonic()
        result = self._run_cli(self._build_command(prompt, session_key=resolved_session_key), timeout=self.config.timeout)
        elapsed_ms = int((time.monotonic() - t0) * 1000)
        combined_output = "\n".join(part for part in [result.stdout, result.stderr] if part).strip()

        if result.returncode != 0:
            log.error("agent_run_error", returncode=result.returncode, duration_ms=elapsed_ms)
            raise RuntimeError(combined_output or "OpenClaw 執行失敗")

        payload = extract_last_json_object(combined_output)
        if isinstance(payload, dict):
            if payload.get("ok") is False:
                raise RuntimeError(str(payload.get("error") or combined_output or "OpenClaw 執行失敗"))
            text = extract_openclaw_text(payload)
            if text:
                log.info("agent_run_done", duration_ms=elapsed_ms, output_len=len(text))
                return text
            raise RuntimeError("OpenClaw JSON 缺少可見文字")
        if combined_output.strip():
            raise RuntimeError("OpenClaw 未回傳有效 JSON")

        log.error("agent_run_error", duration_ms=elapsed_ms, error="OpenClaw 回傳空內容")
        raise RuntimeError("OpenClaw 回傳空內容")

    def stream(self, prompt: str, session_key: Optional[str] = None) -> Iterator[str]:
        yield self.run(prompt, session_key=session_key)


def create_agent_provider(config: AgentProviderConfig) -> IAgentProvider:
    provider = config.provider.strip().lower()

    if provider == "crush":
        return CrushAgentProvider(config)
    if provider == "opencode":
        return OpenCodeAgentProvider(config)
    if provider == "copilot-sdk":
        return CopilotSdkAgentProvider(config)
    if provider == "codex":
        return CodexAgentProvider(config)
    if provider == "openclaw":
        return OpenClawAgentProvider(config)

    raise ValueError(f"不支援的 provider: {config.provider}")
