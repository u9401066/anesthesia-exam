import ast
from pathlib import Path


APP_PATH = Path(__file__).resolve().parents[1] / "src/presentation/streamlit/app.py"


def _decorator_sources(function_name: str) -> list[str]:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return [ast.unparse(decorator) for decorator in node.decorator_list]
    raise AssertionError(f"Function not found: {function_name}")


def _function_node(function_name: str) -> ast.FunctionDef:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == function_name:
            return node
    raise AssertionError(f"Function not found: {function_name}")


def _iter_nodes(tree: ast.AST):
    for node in ast.walk(tree):
        yield node


def _is_st_session_state_attribute(node: ast.AST) -> bool:
    return (
        isinstance(node, ast.Attribute)
        and node.attr == "session_state"
        and isinstance(node.value, ast.Name)
        and node.value.id == "st"
    )


def test_streamlit_heavy_read_paths_use_cache_data() -> None:
    heavy_read_paths = [
        "load_indexed_documents",
        "_load_agent_metadata_cached",
        "load_past_exam_catalog",
        "load_past_exam_questions",
        "load_question_drafts",
        "get_draft_stats",
        "get_questions_stats",
        "load_questions",
        "load_scope_requests",
    ]

    for function_name in heavy_read_paths:
        decorators = _decorator_sources(function_name)
        assert any(decorator.startswith("st.cache_data") for decorator in decorators), function_name


def test_streamlit_chat_panel_is_a_fragment_boundary() -> None:
    decorators = _decorator_sources("render_chat_panel")

    assert any("fragment" in decorator for decorator in decorators)


def test_chat_stream_start_lambda_avoids_session_state_lookup_in_background_thread() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))

    for node in _iter_nodes(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "start":
            continue
        if ast.unparse(node.func.value) != "get_chat_stream_jobs()":
            continue
        if not node.args or not isinstance(node.args[0], ast.Lambda):
            continue

        lambda_node = node.args[0]
        has_session_state_lookup = any(_is_st_session_state_attribute(inner) for inner in ast.walk(lambda_node))
        assert not has_session_state_lookup
        return

    raise AssertionError("get_chat_stream_jobs().start(lambda: ...) call not found")


def test_streamlit_chat_jobs_are_scoped_to_session_state() -> None:
    source = APP_PATH.read_text(encoding="utf-8")

    assert "CHAT_STREAM_JOBS = ChatStreamJobStore()" not in source

    node = _function_node("get_chat_stream_jobs")
    return_values = [
        ast.unparse(return_node.value)
        for return_node in ast.walk(node)
        if isinstance(return_node, ast.Return) and return_node.value is not None
    ]
    assert "ensure_chat_stream_job_store(st.session_state)" in return_values


def test_streamlit_chat_panel_logs_chat_lifecycle_events() -> None:
    source = APP_PATH.read_text(encoding="utf-8")

    for event_name in (
        "chat_stream_start",
        "chat_stream_cancel_requested",
        "chat_stream_job_missing",
        "chat_stream_terminal",
    ):
        assert event_name in source


def test_streamlit_avoids_st_tabs_for_heavy_panels() -> None:
    tree = ast.parse(APP_PATH.read_text(encoding="utf-8"))
    tab_calls = 0
    for node in _iter_nodes(tree):
        if not isinstance(node, ast.Call):
            continue
        if not isinstance(node.func, ast.Attribute):
            continue
        if node.func.attr != "tabs":
            continue
        if isinstance(node.func.value, ast.Name) and node.func.value.id == "st":
            tab_calls += 1

    assert tab_calls == 0


def test_streamlit_cache_invalidation_helpers_clear_cached_read_models() -> None:
    expectations = {
        "invalidate_document_caches": {"load_indexed_documents"},
        "invalidate_draft_caches": {"load_question_drafts", "get_draft_stats"},
        "invalidate_question_bank_caches": {"load_questions", "get_questions_stats"},
        "invalidate_past_exam_caches": {"load_past_exam_catalog", "load_past_exam_questions"},
        "invalidate_scope_request_caches": {"load_scope_requests"},
    }

    for function_name, expected_names in expectations.items():
        node = _function_node(function_name)
        actual_names = {
            ast.unparse(call.args[0])
            for call in ast.walk(node)
            if isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name)
            and call.func.id == "_clear_cached_read_function"
            and call.args
        }
        missing = expected_names - actual_names
        assert not missing, f"{function_name} missing {sorted(missing)}"


def test_streamlit_mutation_paths_invalidate_cached_read_models() -> None:
    source = APP_PATH.read_text(encoding="utf-8")
    expectations = {
        "draft_service.promote_drafts(selected_draft_ids)": [
            "invalidate_draft_caches()",
            "invalidate_question_bank_caches()",
        ],
        'repo.mark_validated(': [
            "invalidate_question_bank_caches()",
        ],
        "generate_and_save_missing_explanations(": [
            "invalidate_past_exam_caches()",
        ],
        "dispatch_service.dispatch(": [
            "invalidate_scope_request_caches()",
            "invalidate_question_bank_caches()",
        ],
    }

    for marker, expected_snippets in expectations.items():
        start = source.find(marker)
        assert start >= 0, f"marker not found: {marker}"
        window = source[start : start + 800]
        for expected in expected_snippets:
            assert expected in window, f"{expected!r} not found near {marker!r}"
