"""Helpers for loading Streamlit document manifests."""

from pathlib import Path
from typing import Any

PROJECT_DIR = Path(__file__).resolve().parents[3]


def normalize_project_path_string(path_str: str, *, project_dir: Path = PROJECT_DIR) -> str:
    """Map stale absolute repo paths back onto the current workspace root."""
    normalized = str(path_str or "").strip()
    if not normalized:
        return normalized

    path = Path(normalized)
    if not path.is_absolute():
        return normalized

    parts = path.parts
    project_name = project_dir.name
    if project_name not in parts:
        return normalized

    relative_parts = parts[parts.index(project_name) + 1 :]
    if not relative_parts:
        return normalized

    return str(project_dir.joinpath(*relative_parts))


def normalize_manifest_paths(value: Any, *, project_dir: Path = PROJECT_DIR) -> Any:
    """Normalize stale persisted path fields inside manifest payloads."""
    if isinstance(value, dict):
        normalized: dict[str, Any] = {}
        for key, item in value.items():
            normalized_item = normalize_manifest_paths(item, project_dir=project_dir)
            if isinstance(normalized_item, str) and (key == "path" or key.endswith("_path")):
                normalized[key] = normalize_project_path_string(normalized_item, project_dir=project_dir)
            else:
                normalized[key] = normalized_item
        return normalized

    if isinstance(value, list):
        return [normalize_manifest_paths(item, project_dir=project_dir) for item in value]

    return value
