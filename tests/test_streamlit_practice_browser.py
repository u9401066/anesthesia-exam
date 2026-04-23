import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
from playwright.sync_api import Error, sync_playwright

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

pytestmark = pytest.mark.e2e

from src.domain.entities.past_exam import PastExam, PastExamQuestion, QuestionPattern  # noqa: E402
from src.domain.entities.question import Difficulty, Question  # noqa: E402
from src.domain.entities.question_draft import DraftQAStatus, QuestionDraft  # noqa: E402
from src.infrastructure.persistence.sqlite_past_exam_repo import SQLitePastExamRepository  # noqa: E402
from src.infrastructure.persistence.sqlite_question_draft_repo import SQLiteQuestionDraftRepository  # noqa: E402
from src.infrastructure.persistence.sqlite_question_repo import SQLiteQuestionRepository  # noqa: E402


def _pick_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def _wait_for_streamlit(base_url: str, timeout_seconds: float = 30.0) -> None:
    deadline = time.time() + timeout_seconds
    last_error: Exception | None = None
    while time.time() < deadline:
        try:
            with urlopen(base_url, timeout=2) as response:  # noqa: S310
                body = response.read().decode("utf-8", errors="ignore")
                if response.status == 200 and "streamlit" in body.lower():
                    return
        except URLError as exc:
            last_error = exc
        except OSError as exc:
            last_error = exc
        time.sleep(0.5)
    raise RuntimeError(f"Streamlit test server did not become ready: {last_error}")


def _wait_for_page_param(page, expected_page: str) -> None:
    page.wait_for_function(
        "(expectedPage) => new URL(window.location.href).searchParams.get('page') === expectedPage",
        arg=expected_page,
    )


def _open_generated_review_practice(page, base_url: str, question_text: str) -> None:
    last_error: Exception | None = None

    for attempt in range(2):
        page.goto(f"{base_url}/?page=generate", wait_until="networkidle")
        page.get_by_role("heading", name="AI 考題生成").wait_for()
        page.get_by_role("button", name="🧪 載入教材 preview-only").click()
        page.get_by_text("AI 生成結果：共 1 題", exact=False).wait_for()
        page.get_by_role("button", name="✍️ 立即練習").click()

        try:
            page.get_by_role("heading", name="作答練習").wait_for(timeout=5000)
        except Error:
            _radio_label(page, "✍️ 作答練習").click()
            page.get_by_role("heading", name="作答練習").wait_for(timeout=10000)

        try:
            page.get_by_text(question_text, exact=False).wait_for(timeout=8000)
            return
        except Error as exc:
            last_error = exc

    raise AssertionError(f"Timed out waiting for generated review practice payload: {last_error}")


def _seed_question_bank(db_path: Path) -> None:
    repo = SQLiteQuestionRepository(db_path=db_path)
    repo.save(
        Question(
            question_text="Browser smoke question 1",
            options=["Quartz", "Saffron", "Topaz", "Ivory"],
            correct_answer="A",
            explanation="Question 1 explanation",
            difficulty=Difficulty.EASY,
            topics=["browser-smoke"],
        ),
        actor_name="pytest-browser",
    )
    repo.save(
        Question(
            question_text="Browser smoke question 2",
            options=["One", "Two", "Three", "Four"],
            correct_answer="B",
            explanation="Question 2 explanation",
            difficulty=Difficulty.MEDIUM,
            topics=["browser-smoke"],
        ),
        actor_name="pytest-browser",
    )


def _seed_draft_box(db_path: Path) -> dict[str, str]:
    draft_repo = SQLiteQuestionDraftRepository(db_path=db_path)

    promote_success_draft = QuestionDraft(
        question=Question(
            question_text="Draft smoke promote success",
            options=["Mercury", "Venus", "Earth", "Mars"],
            correct_answer="C",
            explanation="Successful draft promote explanation",
            topics=["draft-smoke"],
        )
    )
    promote_success_draft.qa_metadata.overall_status = DraftQAStatus.READY
    draft_repo.save(promote_success_draft, actor_name="pytest-browser", reason="seed", action="created")

    promote_failure_draft = QuestionDraft(
        question=Question(
            question_text="Draft smoke promote failure",
            options=["North", "South", "East", "West"],
            correct_answer="A",
            explanation="Failure draft promote explanation",
            topics=["draft-smoke"],
        )
    )
    promote_failure_draft.qa_metadata.overall_status = DraftQAStatus.READY
    draft_repo.save(promote_failure_draft, actor_name="pytest-browser", reason="seed", action="created")

    return {
        "promote_success": promote_success_draft.id,
        "promote_failure": promote_failure_draft.id,
    }


def _seed_past_exam_bank(db_path: Path) -> dict[str, str]:
    repo = SQLitePastExamRepository(db_path=db_path)
    exams = [
        {
            "year": 113,
            "name": "Browser Smoke Past Exam",
            "source_pdf": "browser_smoke_past_exam.pdf",
            "questions": [
                PastExamQuestion(
                    exam_year=113,
                    exam_name="Browser Smoke Past Exam",
                    question_number=1,
                    question_text="Past exam browser question 1",
                    options=["Alpha", "Beta", "Gamma", "Delta"],
                    correct_answer="A",
                    difficulty="easy",
                    topics=["past-browser"],
                    pattern=QuestionPattern.DIRECT_RECALL,
                ),
                PastExamQuestion(
                    exam_year=113,
                    exam_name="Browser Smoke Past Exam",
                    question_number=2,
                    question_text="Past exam browser question 2",
                    options=["Red", "Blue", "Green", "Black"],
                    correct_answer="B",
                    difficulty="medium",
                    topics=["past-browser"],
                    pattern=QuestionPattern.CLINICAL_SCENARIO,
                ),
            ],
        },
        {
            "year": 112,
            "name": "Browser Mixed Past Exam",
            "source_pdf": "browser_mixed_past_exam.pdf",
            "questions": [
                PastExamQuestion(
                    exam_year=112,
                    exam_name="Browser Mixed Past Exam",
                    question_number=1,
                    question_text="Past exam mixed question 1",
                    options=["Copper", "Silver", "Gold", "Iron"],
                    correct_answer="C",
                    difficulty="medium",
                    topics=["mixed-browser"],
                    pattern=QuestionPattern.MECHANISM,
                ),
                PastExamQuestion(
                    exam_year=112,
                    exam_name="Browser Mixed Past Exam",
                    question_number=2,
                    question_text="Past exam mixed question 2",
                    options=["North", "South", "East", "West"],
                    correct_answer="A",
                    difficulty="hard",
                    topics=["mixed-browser"],
                    pattern=QuestionPattern.BEST_ANSWER,
                ),
            ],
        },
        {
            "year": 111,
            "name": "Browser Legacy Past Exam",
            "source_pdf": "browser_legacy_past_exam.pdf",
            "questions": [
                PastExamQuestion(
                    exam_year=111,
                    exam_name="Browser Legacy Past Exam",
                    question_number=1,
                    question_text="Past exam legacy question 1",
                    options=["Mercury", "Venus", "Earth", "Mars"],
                    correct_answer="D",
                    difficulty="easy",
                    topics=["legacy-browser"],
                    pattern=QuestionPattern.COMPARISON,
                ),
                PastExamQuestion(
                    exam_year=111,
                    exam_name="Browser Legacy Past Exam",
                    question_number=2,
                    question_text="Past exam legacy question 2",
                    options=["Spring", "Summer", "Autumn", "Winter"],
                    correct_answer="C",
                    difficulty="medium",
                    topics=["legacy-browser"],
                    pattern=QuestionPattern.SEQUENCE,
                ),
            ],
        },
    ]

    seeded_ids: dict[str, str] = {}
    for exam in exams:
        past_exam = PastExam(
            exam_year=exam["year"],
            exam_name=exam["name"],
            total_questions=len(exam["questions"]),
            source_pdf=exam["source_pdf"],
            imported_by="pytest-browser",
            is_parsed=True,
            is_classified=True,
        )
        repo.save_exam(past_exam)

        questions = []
        for question in exam["questions"]:
            question.past_exam_id = past_exam.id
            questions.append(question)

        repo.save_questions(past_exam.id, questions)
        seeded_ids[f"exam_{exam['year']}"] = past_exam.id

    return seeded_ids


def _start_streamlit_test_server(tmp_dir: Path) -> tuple[subprocess.Popen[str], dict[str, object]]:
    db_path = tmp_dir / "questions.db"
    _seed_question_bank(db_path)
    seeded_drafts = _seed_draft_box(db_path)
    seeded_past_exam = _seed_past_exam_bank(db_path)

    port = _pick_free_port()
    base_url = f"http://127.0.0.1:{port}"
    env = os.environ.copy()
    env["ANESTHESIA_EXAM_DB_PATH"] = str(db_path)
    env["ANESTHESIA_EXAM_E2E_TEST_MODE"] = "1"

    process = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "streamlit",
            "run",
            "src/presentation/streamlit/app.py",
            "--server.port",
            str(port),
            "--server.address",
            "127.0.0.1",
            "--server.headless=true",
        ],
        cwd=PROJECT_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )

    _wait_for_streamlit(base_url)
    return process, {
        "base_url": base_url,
        "db_path": db_path,
        "draft_ids": seeded_drafts,
        "past_exam": seeded_past_exam,
    }


def _radio_label(page, option_text: str):
    return page.locator('label[data-baseweb="radio"]', has_text=option_text).first


def _radio_input(page, option_text: str):
    return _radio_label(page, option_text).locator("input")


def _checkbox_label(page, label_text: str):
    return page.locator("label", has_text=label_text).first


def _select_all_drafts(page):
    page.get_by_role("button", name="🧪 E2E 全選目前草稿").click()


def _selectbox(page, label_text: str):
    return page.get_by_role("combobox", name=label_text)


def _selectbox_option(page, option_text: str):
    return page.get_by_test_id("stSelectboxVirtualDropdown").get_by_text(option_text, exact=False).first


def _delete_draft(db_path: Path, draft_id: str) -> None:
    with sqlite3.connect(db_path) as conn:
        conn.execute("DELETE FROM question_drafts WHERE id = ?", (draft_id,))
        conn.commit()


def _draft_question_texts(db_path: Path) -> set[str]:
    repo = SQLiteQuestionDraftRepository(db_path=db_path)
    return {draft.question.question_text for draft in repo.list_all(limit=500)}


def _bank_questions_by_text(db_path: Path) -> dict[str, Question]:
    repo = SQLiteQuestionRepository(db_path=db_path)
    return {question.question_text: question for question in repo.list_all(limit=500)}


def _wait_for_question_in_drafts(db_path: Path, question_text: str, timeout_seconds: float = 10.0) -> None:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if question_text in _draft_question_texts(db_path):
            return
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for question in drafts: {question_text}")


def _wait_for_question_in_bank(db_path: Path, question_text: str, timeout_seconds: float = 10.0) -> Question:
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        questions = _bank_questions_by_text(db_path)
        if question_text in questions:
            return questions[question_text]
        time.sleep(0.2)
    raise AssertionError(f"Timed out waiting for question in bank: {question_text}")


@pytest.fixture(scope="session")
def streamlit_test_server(tmp_path_factory: pytest.TempPathFactory):
    db_dir = tmp_path_factory.mktemp("streamlit-browser-db")
    process, server_info = _start_streamlit_test_server(db_dir)

    try:
        yield server_info
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture()
def isolated_streamlit_test_server(tmp_path: Path):
    process, server_info = _start_streamlit_test_server(tmp_path)

    try:
        yield server_info
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)


@pytest.fixture()
def browser_page():
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as exc:
            pytest.skip(f"Chromium is not available for Playwright: {exc}")

        page = browser.new_page()
        try:
            yield page
        finally:
            browser.close()


def test_library_to_practice_syncs_url_and_navigation(streamlit_test_server, browser_page) -> None:
    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=library", wait_until="networkidle")

    page.get_by_role("button", name="✍️ 用目前篩選結果練習").click()

    _wait_for_page_param(page, "practice")
    page.get_by_role("heading", name="作答練習").wait_for()

    assert page.url.endswith("?page=practice")
    assert page.get_by_role("radio", name="✍️ 作答練習").is_checked()
    assert page.get_by_text("Browser smoke question 2").is_visible()
    assert page.get_by_text("Browser smoke question 1").is_visible()


def test_practice_submit_disables_answers_and_shows_score(streamlit_test_server, browser_page) -> None:
    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=library", wait_until="networkidle")
    page.get_by_role("button", name="✍️ 用目前篩選結果練習").click()

    _wait_for_page_param(page, "practice")
    page.get_by_role("heading", name="作答練習").wait_for()

    _radio_label(page, "B. Two").click()
    _radio_label(page, "A. Quartz").click()
    page.get_by_role("button", name="📤 提交答案").click()

    page.get_by_text("本次成績：2/2 題 (100.0%)").wait_for()

    assert page.url.endswith("?page=practice")
    assert page.get_by_text("正確！答案：B").is_visible()
    assert page.get_by_text("正確！答案：A").is_visible()
    assert _radio_input(page, "B. Two").is_disabled()
    assert _radio_input(page, "A. Quartz").is_disabled()


def test_practice_can_select_past_exam_questions(streamlit_test_server, browser_page) -> None:
    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=practice", wait_until="networkidle")
    page.get_by_role("heading", name="作答練習").wait_for()

    practice_source = _selectbox(page, "題目來源")
    practice_source.click()
    _selectbox_option(page, "考古題模式").click()

    practice_mode = _selectbox(page, "練習方式")
    practice_mode.click()
    _selectbox_option(page, "單份考卷").click()

    page.get_by_text("目前選用 113 年 Browser Smoke Past Exam，共 2 題。", exact=True).wait_for()
    page.get_by_role("button", name="🎯 開始練習").click()

    page.get_by_text("Past exam browser question 1", exact=False).wait_for()

    assert page.url.endswith("?page=practice")
    assert page.get_by_text("Past exam browser question 2", exact=False).is_visible()
    assert page.get_by_text("113 年 Browser Smoke Past Exam 第 1 題", exact=False).is_visible()


def test_past_exam_mode_supports_mixed_year_range_stats_and_review(streamlit_test_server, browser_page) -> None:
    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=practice", wait_until="networkidle")
    page.get_by_role("heading", name="作答練習").wait_for()

    practice_source = _selectbox(page, "題目來源")
    practice_source.click()
    _selectbox_option(page, "考古題模式").click()

    start_year = _selectbox(page, "起始年度")
    start_year.click()
    _selectbox_option(page, "112").click()

    page.get_by_text("目前納入 2 份考卷，共 4 題可抽。", exact=True).wait_for()
    _checkbox_label(page, "隨機順序").click()
    page.get_by_role("button", name="🎯 開始練習").click()

    page.get_by_text("Past exam browser question 1", exact=False).wait_for()
    page.get_by_role("button", name="📤 提交答案").click()

    page.get_by_text("本次成績：0/4 題 (0.0%)", exact=False).wait_for()
    page.get_by_text("考古題模式統計", exact=True).wait_for()
    page.get_by_text("來源範圍：112-113 年；多份混抽；涵蓋 2 份考卷，已作答 0 / 4 題。", exact=True).wait_for()

    page.get_by_role("tab", name="錯題回顧 (4)").click()
    page.get_by_text("Past exam browser question 2", exact=False).first.wait_for()

    assert page.url.endswith("?page=practice")
    assert page.get_by_text("Past exam mixed question 1", exact=False).first.is_visible()


def test_draft_box_batch_promote_reports_partial_failure(streamlit_test_server, browser_page) -> None:
    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=library", wait_until="networkidle")
    page.get_by_role("heading", name="題庫管理").wait_for()
    page.get_by_role("tab", name="待審草稿").click()
    page.get_by_text("待審草稿區會在這裡處理模板套用、QA、批次編修與正式入庫。", exact=True).wait_for()

    _select_all_drafts(page)
    page.get_by_text("送入正式題庫前摘要", exact=True).wait_for()

    _delete_draft(streamlit_test_server["db_path"], streamlit_test_server["draft_ids"]["promote_failure"])

    page.get_by_role("button", name="✅ 送入正式題庫").click()
    _wait_for_question_in_bank(streamlit_test_server["db_path"], "Draft smoke promote success")

    assert page.url.endswith("?page=library")
    assert "Draft smoke promote failure" not in _draft_question_texts(streamlit_test_server["db_path"])


def test_textbook_preview_only_review_can_only_save_to_drafts(streamlit_test_server, browser_page) -> None:
    preview_text = "E2E textbook preview-only shock question"
    before_drafts = _draft_question_texts(streamlit_test_server["db_path"])

    page = browser_page
    page.goto(f"{streamlit_test_server['base_url']}/?page=generate", wait_until="networkidle")
    page.get_by_role("heading", name="AI 考題生成").wait_for()

    page.get_by_role("button", name="🧪 載入教材 preview-only").click()

    page.get_by_text("AI 生成結果：共 1 題", exact=False).wait_for()
    page.get_by_text("本批有 1 題屬於 preview-only 題目，只供工作台預覽，請到題庫管理進行審閱。", exact=True).wait_for()
    page.get_by_text("preview-only：這題只供工作台預覽，請到題庫管理進行審閱後再決定是否入庫。", exact=True).wait_for()

    page.get_by_role("button", name="📚 前往題庫管理").click()
    page.get_by_role("heading", name="題庫管理").wait_for()
    page.get_by_role("tab", name="待審草稿").click()
    page.get_by_text("待審草稿區會在這裡處理模板套用、QA、批次編修與正式入庫。", exact=True).wait_for()
    page.get_by_label("搜尋草稿").fill(preview_text)

    _select_all_drafts(page)

    page.get_by_text("送入正式題庫前摘要", exact=True).wait_for()

    after_drafts = _draft_question_texts(streamlit_test_server["db_path"])
    assert preview_text not in before_drafts
    assert preview_text in after_drafts


def test_textbook_formal_ready_review_can_save_to_question_bank(isolated_streamlit_test_server, browser_page) -> None:
    formal_text = "E2E textbook formal-save shock question"
    before_questions = _bank_questions_by_text(isolated_streamlit_test_server["db_path"])

    page = browser_page
    page.goto(f"{isolated_streamlit_test_server['base_url']}/?page=generate", wait_until="networkidle")
    page.get_by_role("heading", name="AI 考題生成").wait_for()

    page.get_by_role("button", name="🧪 載入教材 formal-save").click()
    page.wait_for_timeout(1500)
    _wait_for_question_in_drafts(isolated_streamlit_test_server["db_path"], formal_text)

    page.get_by_role("button", name="📚 前往題庫管理").click()
    page.get_by_role("heading", name="題庫管理").wait_for()
    page.get_by_role("tab", name="待審草稿").click()
    page.get_by_text("待審草稿區會在這裡處理模板套用、QA、批次編修與正式入庫。", exact=True).wait_for()
    page.get_by_label("搜尋草稿").fill(formal_text)

    _select_all_drafts(page)
    page.get_by_role("button", name="✅ 送入正式題庫").click()
    assert formal_text not in before_questions

    saved_question = _wait_for_question_in_bank(isolated_streamlit_test_server["db_path"], formal_text)
    assert saved_question.source is not None
    assert saved_question.source.document == "Miller E2E Textbook"
    assert saved_question.source.chapter == "ACUTE CIRCULATORY FAILURE IN CHILDREN (SHOCK AND SEPSIS)"
    assert saved_question.source.section == "Therapy and Outcomes"
    assert saved_question.source.stem_source is not None
    assert saved_question.source.answer_source is not None
    assert len(saved_question.source.explanation_sources) == 1


def test_textbook_review_can_jump_directly_to_practice(isolated_streamlit_test_server, browser_page) -> None:
    page = browser_page
    _open_generated_review_practice(
        page,
        isolated_streamlit_test_server["base_url"],
        "E2E textbook preview-only shock question",
    )

    assert page.get_by_role("radio", name="✍️ 作答練習").is_checked()
    assert page.get_by_text("E2E textbook preview-only shock question", exact=False).is_visible()
