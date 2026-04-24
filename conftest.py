from __future__ import annotations

import os
import sys
from importlib import import_module
from importlib.util import find_spec
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parent
ASSET_AWARE_ROOT = REPO_ROOT / "libs" / "asset-aware-mcp"
REPO_TESTS_ROOT = REPO_ROOT / "tests"
ASSET_AWARE_TESTS_ROOT = ASSET_AWARE_ROOT / "tests"
SRC_SUBPACKAGES = ("application", "domain", "infrastructure", "presentation")


def _debug(message: str) -> None:
    if os.getenv("PYTEST_SRC_SWITCH_DEBUG") == "1":
        print(f"[src-switch] {message}")


def _purge_src_modules() -> None:
    for module_name in list(sys.modules):
        if module_name == "src" or module_name.startswith("src."):
            del sys.modules[module_name]


def _activate_import_root(preferred_root: Path) -> None:
    fallback_root = ASSET_AWARE_ROOT if preferred_root == REPO_ROOT else REPO_ROOT
    ordered_roots = [preferred_root, fallback_root]

    for root in ordered_roots:
        root_text = str(root)
        while root_text in sys.path:
            sys.path.remove(root_text)

    for root in reversed(ordered_roots):
        sys.path.insert(0, str(root))

    _debug(
        "activate "
        f"preferred={preferred_root} "
        f"sys.path[:4]={sys.path[:4]}"
    )
    if os.getenv("PYTEST_SRC_SWITCH_DEBUG") == "1":
        src_module = sys.modules.get("src")
        src_spec = find_spec("src")
        infra_spec = find_spec("src.infrastructure")
        agent_spec = find_spec("src.infrastructure.agent")
        _debug(
            "src-state "
            f"loaded={getattr(src_module, '__file__', None)} "
            f"loaded_path={getattr(src_module, '__path__', None)} "
            f"spec_origin={getattr(src_spec, 'origin', None)} "
            f"spec_locations={getattr(src_spec, 'submodule_search_locations', None)} "
            f"infra_origin={getattr(infra_spec, 'origin', None)} "
            f"infra_locations={getattr(infra_spec, 'submodule_search_locations', None)} "
            f"agent_origin={getattr(agent_spec, 'origin', None)} "
            f"agent_locations={getattr(agent_spec, 'submodule_search_locations', None)}"
        )


def _extend_package_path(module_name: str, paths: list[Path]) -> None:
    module = sys.modules.get(module_name)
    if module is None or not hasattr(module, "__path__"):
        return

    existing_paths = [str(path) for path in module.__path__]
    for path in paths:
        path_text = str(path)
        if path.exists() and path_text not in existing_paths:
            module.__path__.append(path_text)
            existing_paths.append(path_text)


def _merge_loaded_src_packages() -> None:
    src_roots = [REPO_ROOT / "src", ASSET_AWARE_ROOT / "src"]
    try:
        import_module("src")
    except ModuleNotFoundError:
        return

    _extend_package_path("src", src_roots)

    for package_name in SRC_SUBPACKAGES:
        package_roots = [root / package_name for root in src_roots]
        if not any(path.exists() for path in package_roots):
            continue

        try:
            import_module(f"src.{package_name}")
        except ModuleNotFoundError:
            continue

        _extend_package_path(f"src.{package_name}", package_roots)


def _switch_src_namespace_for_path(path: Path) -> None:
    resolved_path = path.resolve()
    if resolved_path.is_relative_to(ASSET_AWARE_TESTS_ROOT):
        _debug(f"switch asset-aware for {resolved_path}")
        _activate_import_root(ASSET_AWARE_ROOT)
        if "src" in sys.modules:
            _merge_loaded_src_packages()
        else:
            _purge_src_modules()
    elif resolved_path.is_relative_to(REPO_TESTS_ROOT):
        _debug(f"switch repo for {resolved_path}")
        _activate_import_root(REPO_ROOT)
        if "src" in sys.modules:
            _merge_loaded_src_packages()
        else:
            _purge_src_modules()


class SrcSwitchModule(pytest.Module):
    def _getobj(self):  # type: ignore[override]
        _switch_src_namespace_for_path(Path(str(self.path)))
        return super()._getobj()


def pytest_pycollect_makemodule(module_path: Path, parent):  # type: ignore[no-untyped-def]
    resolved_path = module_path.resolve()
    if resolved_path.is_relative_to(ASSET_AWARE_TESTS_ROOT) or resolved_path.is_relative_to(REPO_TESTS_ROOT):
        return SrcSwitchModule.from_parent(parent, path=module_path)
    return None


def pytest_runtest_setup(item):  # type: ignore[no-untyped-def]
    _switch_src_namespace_for_path(Path(str(item.path)))
