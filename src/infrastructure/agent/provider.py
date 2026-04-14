"""Agent Provider 抽象層

目的：讓上層（Streamlit）不再綁定單一 Agent（如 Crush）。
可透過設定切換底層 provider：
- crush: 本地 Crush CLI
- opencode: OpenCode CLI + opencode.json（Ollama/自訂 LLM）
- copilot-sdk: HTTP API（由 EXAM_COPILOT_SDK_ENDPOINT 指定）
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional, Protocol
from urllib import request
from urllib.error import HTTPError, URLError

from src.infrastructure.logging import get_logger

logger = get_logger(__name__)


class IAgentProvider(Protocol):
    """Agent provider 介面"""

    name: str

    def is_available(self) -> tuple[bool, str]: ...

    def run(self, prompt: str) -> str: ...

    def stream(self, prompt: str) -> Iterator[str]: ...


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

    @classmethod
    def load(
        cls,
        project_dir: Path,
        crush_config_path: Path,
        provider_override: Optional[str] = None,
        model_override: Optional[str] = None,
    ) -> "AgentProviderConfig":
        provider = (provider_override or os.getenv("EXAM_AGENT_PROVIDER", "crush")).strip().lower()
        timeout = int(os.getenv("EXAM_AGENT_TIMEOUT", "120"))

        model = None
        if crush_config_path.exists():
            try:
                with open(crush_config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                model = data.get("agents", {}).get("coder", {}).get("model")
            except Exception:
                model = None

        crush_executable = os.getenv("EXAM_CRUSH_PATH")
        if not crush_executable:
            crush_executable = shutil.which("crush")

        if not crush_executable:
            crush_executable = "D:/workspace260203/crush/crush.exe"

        # OpenCode: 從 opencode.json 讀取模型設定
        opencode_executable = os.getenv("EXAM_OPENCODE_PATH") or shutil.which("opencode")
        opencode_model = model_override or os.getenv("EXAM_OPENCODE_MODEL")
        if not opencode_model:
            opencode_json = project_dir / "opencode.json"
            if opencode_json.exists():
                try:
                    with open(opencode_json, "r", encoding="utf-8") as f:
                        oc_data = json.load(f)
                    opencode_model = oc_data.get("model")
                except Exception:
                    pass

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

    def run(self, prompt: str) -> str:
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

    def stream(self, prompt: str) -> Iterator[str]:
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
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
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
            process.terminate()


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

    def run(self, prompt: str) -> str:
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

    def stream(self, prompt: str) -> Iterator[str]:
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
            assert process.stdout is not None
            for line in iter(process.stdout.readline, ""):
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
            process.terminate()


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

    def run(self, prompt: str) -> str:
        return self._call_api(prompt)

    def stream(self, prompt: str) -> Iterator[str]:
        yield self._call_api(prompt)


def create_agent_provider(config: AgentProviderConfig) -> IAgentProvider:
    provider = config.provider.strip().lower()

    if provider == "crush":
        return CrushAgentProvider(config)
    if provider == "opencode":
        return OpenCodeAgentProvider(config)
    if provider == "copilot-sdk":
        return CopilotSdkAgentProvider(config)

    raise ValueError(f"不支援的 provider: {config.provider}")
