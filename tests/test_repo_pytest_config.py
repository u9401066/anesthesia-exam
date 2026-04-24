import subprocess
import sys
import tomllib
from pathlib import Path


PYPROJECT_PATH = Path(__file__).resolve().parents[1] / "pyproject.toml"


def test_root_pytest_collection_is_limited_to_repo_tests() -> None:
    data = tomllib.loads(PYPROJECT_PATH.read_text(encoding="utf-8"))
    pytest_options = data["tool"]["pytest"]["ini_options"]

    assert pytest_options["testpaths"] == ["tests"]
    assert "libs/asset-aware-mcp" in pytest_options["norecursedirs"]


def test_mixed_repo_and_vendored_pytest_collection_succeeds() -> None:
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "-q",
            "libs/asset-aware-mcp/tests/unit/test_document_service.py",
            "tests/test_agent_provider_config.py",
        ],
        cwd=PYPROJECT_PATH.parent,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        "Mixed pytest collection should succeed.\n"
        f"stdout:\n{result.stdout}\n"
        f"stderr:\n{result.stderr}"
    )
