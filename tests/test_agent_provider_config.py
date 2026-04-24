import sys
import subprocess
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from src.infrastructure.agent.provider import (  # noqa: E402
    AgentProviderConfig,
    OpenClawAgentProvider,
    collect_openclaw_available_models,
    collect_opencode_available_models,
    create_agent_provider,
    extract_last_json_object,
    resolve_openclaw_default_model,
    resolve_opencode_default_model,
)


def test_collect_opencode_available_models_supports_dict_and_list_model_shapes() -> None:
    config = {
        "provider": {
            "gb10": {
                "models": {
                    "Qwen.gguf": {"name": "GB10 Qwen"},
                }
            },
            "legacy": {
                "models": [
                    {"id": "legacy-a", "name": "Legacy A"},
                    {"id": "legacy-b", "name": "Legacy B"},
                ]
            },
        }
    }

    assert collect_opencode_available_models(config) == [
        "gb10/Qwen.gguf",
        "legacy/legacy-a",
        "legacy/legacy-b",
    ]


def test_resolve_opencode_default_model_prefers_explicit_then_first_available() -> None:
    explicit_config = {
        "model": "gb10/Qwen.gguf",
        "provider": {
            "gb10": {
                "models": {
                    "Qwen.gguf": {"name": "GB10 Qwen"},
                }
            }
        },
    }
    inferred_config = {
        "provider": {
            "gb10": {
                "models": {
                    "Qwen.gguf": {"name": "GB10 Qwen"},
                }
            }
        }
    }

    assert resolve_opencode_default_model(explicit_config) == "gb10/Qwen.gguf"
    assert resolve_opencode_default_model(inferred_config) == "gb10/Qwen.gguf"


def test_collect_openclaw_available_models_and_resolve_primary() -> None:
    config = {
        "agents": {
            "defaults": {
                "model": {
                    "primary": "gb10/Qwen.gguf",
                }
            }
        },
        "models": {
            "providers": {
                "gb10": {
                    "models": [
                        {"id": "Qwen.gguf", "name": "GB10 Qwen"},
                        {"id": "Another.gguf", "name": "Another"},
                    ]
                }
            }
        },
    }

    assert collect_openclaw_available_models(config) == [
        "gb10/Qwen.gguf",
        "gb10/Another.gguf",
    ]
    assert resolve_openclaw_default_model(config) == "gb10/Qwen.gguf"


def test_extract_last_json_object_picks_final_payload_from_mixed_output() -> None:
    raw_output = """Installing plugin...
warning: cached state refreshed
{"ok": false, "error": "temporary"}
{"ok": true, "outputs": [{"text": "OK"}]}
"""

    assert extract_last_json_object(raw_output) == {
        "ok": True,
        "outputs": [{"text": "OK"}],
    }


def test_agent_provider_config_loads_codex_settings_from_env(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setenv("EXAM_AGENT_PROVIDER", "codex")
    monkeypatch.setenv("EXAM_CODEX_MODEL", "gpt-5.3-codex")
    monkeypatch.setenv("EXAM_OPENAI_BASE_URL", "https://api.openai.com/v1")
    monkeypatch.setenv("EXAM_OPENAI_API_KEY", "test-openai-key")

    config = AgentProviderConfig.load(
        project_dir=tmp_path,
        crush_config_path=tmp_path / "missing-crush.json",
    )

    assert config.provider == "codex"
    assert config.codex_model == "gpt-5.3-codex"
    assert config.openai_base_url == "https://api.openai.com/v1"
    assert config.openai_api_key == "test-openai-key"

    provider = create_agent_provider(config)
    assert provider.name == "codex"


def test_agent_provider_config_loads_openclaw_settings_from_repo_local_config(
    monkeypatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setenv("EXAM_AGENT_PROVIDER", "openclaw")
    openclaw_config_path = tmp_path / "vendor" / "openclaw-state" / "openclaw.json"
    openclaw_config_path.parent.mkdir(parents=True, exist_ok=True)
    openclaw_config_path.write_text(
        """
        {
          "agents": {
            "defaults": {
              "model": {
                "primary": "gb10/Qwen.gguf"
              }
            }
          },
          "models": {
            "providers": {
              "gb10": {
                "models": [
                  {"id": "Qwen.gguf", "name": "GB10 Qwen"}
                ]
              }
            }
          }
        }
        """.strip(),
        encoding="utf-8",
    )

    config = AgentProviderConfig.load(
        project_dir=tmp_path,
        crush_config_path=tmp_path / "missing-crush.json",
    )

    assert config.provider == "openclaw"
    assert config.openclaw_model == "gb10/Qwen.gguf"
    assert config.openclaw_config_path == openclaw_config_path

    provider = create_agent_provider(config)
    assert provider.name == "openclaw"


def test_openclaw_infer_mode_does_not_require_repo_local_config(tmp_path: Path) -> None:
    executable = tmp_path / "openclaw"
    executable.write_text("#!/usr/bin/env bash\nexit 0\n", encoding="utf-8")
    executable.chmod(0o755)

    provider = OpenClawAgentProvider(
        AgentProviderConfig(
            provider="openclaw",
            working_dir=tmp_path,
            model="gb10/Qwen.gguf",
            timeout=30,
            openclaw_executable=str(executable),
            openclaw_model="gb10/Qwen.gguf",
            openclaw_mode="infer",
            openclaw_agent_id="main",
            openclaw_config_path=tmp_path / "missing-openclaw.json",
        )
    )
    provider._run_cli = lambda args, *, timeout: subprocess.CompletedProcess(  # type: ignore[method-assign]
        args=args,
        returncode=0,
        stdout="gb10/Qwen.gguf\n",
        stderr="",
    )

    available, reason = provider.is_available()

    assert available is True
    assert "mode=infer" in reason
