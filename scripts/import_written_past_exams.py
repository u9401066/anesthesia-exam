from __future__ import annotations

import argparse
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.application.services.past_exam_extraction_service import (  # noqa: E402
    AssetAwareDocument,
    PastExamExtractionService,
)
from src.infrastructure.persistence.sqlite_past_exam_repo import (  # noqa: E402
    SQLitePastExamRepository,
)

DATA_DIR = ROOT / "data"
SOURCE_DIR = ROOT / "歷屆考題"
DOCX_NS = {"w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main"}
OPTION_LABELS = "ABCDE"
LABEL_ONLY_RE = re.compile(r"([A-E])[\.、\)）:：]?")
ASSET_DOC_IDS = {
    109: "doc_109______a9f9c7",
    110: "doc_110______172aeb",
    111: "doc_111______8d460a",
    112: "doc_112______4d585e",
    113: "doc_113______a6f586",
}
ASSET_EXAM_NAMES = {
    109: "109年麻醉科專科醫師甄審筆試試卷",
    110: "110年麻醉專科醫師甄審筆試",
    111: "111年麻醉專科醫師甄審筆試",
    112: "112年麻醉專科醫師甄審筆試",
    113: "113年重症醫學專科醫師聯合訓練及甄審筆試試卷",
}
QUESTION_HINTS = (
    "下列",
    "何者",
    "何項",
    "關於",
    "有關",
    "最可能",
    "最適當",
    "最主要",
    "不包括",
    "不是",
    "為非",
    "為是",
    "正確",
    "錯誤",
    "原因",
)
VERIFIED_114_ANSWER_TEXT = """
1 D 21 C 41 B 61 C 81 C
2 D 22 C 42 A 62 D 82 A
3 D 23 B 43 D 63 A 83 C
4 A 24 C 44 B 64 B 84 B
5 D 25 D 45 D 65 A 85 D
6 D 26 A 46 D 66 D 86 C
7 B 27 B 47 C 67 D 87 D
8 B 28 B 48 B 68 D 88 B
9 B 29 C 49 D 69 A 89 D
10 A 30 C 50 D 70 B 90 D
11 D 31 A 51 C 71 C 91 C
12 A 32 A 52 C 72 C 92 B
13 A 33 D 53 D 73 B 93 A
14 D 34 D 54 D 74 B 94 B
15 C 35 A 55 C 75 D 95 D
16 C 36 A 56 B 76 A 96 B
17 D 37 A 57 D 77 D 97 D
18 D 38 C 58 A 78 D 98 D
19 B 39 A 59 D 79 B 99 A
20 A 40 C 60 B 80 B 100 D
"""


EXTRACTION_SERVICE = PastExamExtractionService(DATA_DIR)


@dataclass(slots=True)
class QuestionBlock:
    number: int
    stem: str
    options: list[str]
    explanation: str = ""


@dataclass(slots=True)
class PreparedExam:
    roc_year: int
    exam_name: str
    document: AssetAwareDocument
    expected_question_count: int = 100
    expected_answer_count: int | None = 100
    answer_overrides: dict[int, str] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    @property
    def gregorian_year(self) -> int:
        return self.roc_year + 1911


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Import written historical anesthesia exams into SQLite.")
    parser.add_argument("--dry-run", action="store_true", help="Validate parsing without writing to SQLite.")
    parser.add_argument(
        "--only",
        type=int,
        action="append",
        help="Restrict import to one or more ROC years, e.g. --only 107 --only 114.",
    )
    return parser.parse_args()


def normalize_whitespace(value: str) -> str:
    value = value.replace("\u3000", " ").replace("\xa0", " ").replace("\ufeff", "")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\s*\n\s*", "\n", value)
    return value.strip()


def normalize_inline_text(value: str) -> str:
    return normalize_whitespace(value).replace("\n", " ").strip()


def run_pdftotext(pdf_path: Path) -> str:
    result = subprocess.run(
        ["pdftotext", "-layout", "-nopgbrk", str(pdf_path), "-"],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout


def parse_answer_pairs(text: str) -> dict[int, str]:
    return {
        int(number): answer.upper()
        for number, answer in re.findall(r"(\d{1,3})\s*[\.、\)）:：-]?\s*([A-E]{1,5})\b", text)
    }


def build_answer_section(answer_map: dict[int, str]) -> str:
    lines = ["## 答案"]
    for number in sorted(answer_map):
        answer = answer_map[number]
        if re.fullmatch(r"[A-E]", answer):
            lines.append(f"{number}. {answer}")
    return "\n".join(lines)


def make_document(doc_id: str, title: str, source_path: Path, markdown: str) -> AssetAwareDocument:
    return AssetAwareDocument(
        doc_id=doc_id,
        title=title,
        manifest={"title": title, "filename": source_path.name},
        markdown=markdown,
        markdown_path=source_path,
    )


def append_answer_section(markdown: str, answer_map: dict[int, str]) -> str:
    if not answer_map:
        return markdown
    return markdown.rstrip() + "\n\n" + build_answer_section(answer_map) + "\n"


def extract_stem_and_options(block_text: str) -> tuple[str, list[str]]:
    return EXTRACTION_SERVICE._extract_stem_and_options(block_text)


def parse_block_lines(cleaned_lines: list[str]) -> tuple[str, list[str]]:
    stem, options = extract_stem_and_options(" ".join(cleaned_lines))
    if len(options) >= 4:
        return stem, options

    label_only = []
    for line in cleaned_lines[1:]:
        match = LABEL_ONLY_RE.fullmatch(line)
        if match is not None:
            label_only.append(match.group(1).upper())
    if len(label_only) >= 4:
        return cleaned_lines[0], [f"圖像選項 {label}" for label in label_only]
    return stem, options


def build_markdown_from_blocks(blocks: list[QuestionBlock], answer_map: dict[int, str]) -> str:
    lines: list[str] = []
    for block in sorted(blocks, key=lambda item: item.number):
        lines.append(f"{block.number}. {block.stem}")
        for label, option in zip(OPTION_LABELS, block.options):
            lines.append(f"{label}. {option}")
        if block.explanation:
            lines.append(f"Explanation: {block.explanation}")
        lines.append("")
    if answer_map:
        lines.append(build_answer_section(answer_map))
    return "\n".join(lines).strip() + "\n"


def parse_numbered_question_blocks(text: str) -> list[QuestionBlock]:
    matches = list(re.finditer(r"(?m)^\s*(\d{1,3})\.\s*(.*)$", text))
    blocks_by_number: dict[int, QuestionBlock] = {}
    for index, match in enumerate(matches):
        number = int(match.group(1))
        if not 1 <= number <= 100:
            continue
        block_end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        block_text = match.group(2) + "\n" + text[match.end() : block_end]
        cleaned_lines = []
        for raw_line in block_text.splitlines():
            line = normalize_inline_text(raw_line)
            if not line or line in {"Page #", "答案列印"}:
                continue
            cleaned_lines.append(line)
        stem, options = parse_block_lines(cleaned_lines)
        if len(options) < 4:
            continue
        candidate = QuestionBlock(number=number, stem=stem, options=options)
        existing = blocks_by_number.get(number)
        if existing is None or len(candidate.stem) > len(existing.stem):
            blocks_by_number[number] = candidate
    return [blocks_by_number[number] for number in sorted(blocks_by_number)]


def read_docx_body_paragraphs(docx_path: Path) -> list[str]:
    with ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    paragraphs: list[str] = []
    for paragraph in root.findall(".//w:body/w:p", DOCX_NS):
        text = "".join(node.text or "" for node in paragraph.findall(".//w:t", DOCX_NS))
        cleaned = normalize_inline_text(text)
        if cleaned:
            paragraphs.append(cleaned)
    return paragraphs


def read_docx_table_rows(docx_path: Path) -> list[list[list[str]]]:
    with ZipFile(docx_path) as archive:
        root = ET.fromstring(archive.read("word/document.xml"))
    tables = root.findall(".//w:tbl", DOCX_NS)
    rows: list[list[list[str]]] = []
    if not tables:
        return rows
    for row in tables[0].findall("./w:tr", DOCX_NS):
        row_cells: list[list[str]] = []
        for cell in row.findall("./w:tc", DOCX_NS):
            paragraphs: list[str] = []
            for paragraph in cell.findall("./w:p", DOCX_NS):
                text = "".join(node.text or "" for node in paragraph.findall(".//w:t", DOCX_NS))
                cleaned = normalize_inline_text(text)
                if cleaned:
                    paragraphs.append(cleaned)
            if paragraphs:
                row_cells.append(paragraphs)
        if row_cells:
            rows.append(row_cells)
    return rows


def parse_docx_answer_table(docx_path: Path) -> dict[int, str]:
    answer_map: dict[int, str] = {}
    for row in read_docx_table_rows(docx_path):
        for cell in row:
            for text in cell:
                answer_map.update(parse_answer_pairs(text))
    return answer_map


def looks_like_question_stem(line: str) -> bool:
    return bool(
        "？" in line
        or "?" in line
        or line.endswith((":", "："))
        or any(token in line for token in QUESTION_HINTS)
    )


def segment_docx_question_lines(lines: list[str], expected_count: int = 100) -> list[list[str]]:
    start_index = next(index for index, line in enumerate(lines) if looks_like_question_stem(line))
    body_lines = lines[start_index:]

    @lru_cache(maxsize=None)
    def solve(position: int, remaining: int) -> tuple[int, ...] | None:
        if remaining == 0:
            return () if position == len(body_lines) else None
        for size in (5, 6):
            next_position = position + size
            if next_position > len(body_lines):
                continue
            if not looks_like_question_stem(body_lines[position]):
                continue
            if next_position < len(body_lines) and not looks_like_question_stem(body_lines[next_position]):
                continue
            rest = solve(next_position, remaining - 1)
            if rest is not None:
                return (size, *rest)
        return None

    sizes = solve(0, expected_count)
    if sizes is None:
        raise ValueError(f"無法將 DOCX 段落穩定切成 {expected_count} 題")

    grouped: list[list[str]] = []
    cursor = 0
    for size in sizes:
        grouped.append(body_lines[cursor : cursor + size])
        cursor += size
    return grouped


def extract_archive(rar_path: Path, temp_root: Path) -> Path:
    subprocess.run(
        ["unar", "-force-overwrite", "-output-directory", str(temp_root), str(rar_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    candidates = [path for path in temp_root.iterdir() if path.name != "__MACOSX"]
    if len(candidates) == 1:
        return candidates[0]
    return temp_root


def prepare_106_exam(archive_dir: Path) -> PreparedExam:
    source_path = archive_dir / "2017_written_ans.pdf"
    text = run_pdftotext(source_path)
    parts = re.split(r"\bQUESTION\s+(\d+)\b", text)
    blocks_by_number: dict[int, QuestionBlock] = {}
    answer_map: dict[int, str] = {}

    for index in range(1, len(parts), 2):
        number = int(parts[index])
        block = parts[index + 1]
        answer_match = re.search(r"Correct Answer\s*:\s*([A-E])", block)
        if answer_match is None or not 1 <= number <= 100:
            continue

        question_part = block.split("Correct Answer", 1)[0]
        cleaned_lines = []
        for raw_line in question_part.splitlines():
            line = normalize_inline_text(raw_line)
            if not line or line == "Page #":
                continue
            cleaned_lines.append(line)
        stem, options = parse_block_lines(cleaned_lines)
        if len(options) < 4:
            continue

        reference_match = re.search(
            r"Explanation/Reference:\s*(.+?)(?:難易度|分類|QUESTION\s+\d+|$)",
            block,
            re.S,
        )
        explanation = normalize_inline_text(reference_match.group(1)) if reference_match else ""
        blocks_by_number[number] = QuestionBlock(number=number, stem=stem, options=options, explanation=explanation)
        answer_map[number] = answer_match.group(1).upper()

    markdown = build_markdown_from_blocks([blocks_by_number[number] for number in sorted(blocks_by_number)], answer_map)
    document = make_document("hist_106_written", "106年麻醉科專科醫師甄審筆試", source_path, markdown)
    return PreparedExam(roc_year=106, exam_name=document.title, document=document)


def prepare_107_exam(archive_dir: Path) -> PreparedExam:
    question_docx = archive_dir / "2018_筆試題目.docx"
    answer_docx = archive_dir / "2018_筆試答案.docx"
    grouped_lines = segment_docx_question_lines(read_docx_body_paragraphs(question_docx))
    blocks = [
        QuestionBlock(number=index, stem=group[0], options=group[1:])
        for index, group in enumerate(grouped_lines, start=1)
    ]
    answer_map = parse_docx_answer_table(answer_docx)
    markdown = build_markdown_from_blocks(blocks, answer_map)
    document = make_document("hist_107_written", "107年麻醉專科醫師甄審筆試", question_docx, markdown)
    return PreparedExam(roc_year=107, exam_name=document.title, document=document)


def prepare_108_exam(archive_dir: Path) -> PreparedExam:
    source_path = archive_dir / "108年麻醉科專科醫師甄審筆試試卷與答案_學會公佈版.pdf"
    text = run_pdftotext(source_path)
    question_text, answer_text = text.split("答案列印", 1)
    blocks = parse_numbered_question_blocks(question_text)
    answer_map = parse_answer_pairs(answer_text)
    markdown = build_markdown_from_blocks(blocks, answer_map)
    document = make_document("hist_108_written", "108年麻醉科專科醫師甄審筆試試卷", source_path, markdown)
    return PreparedExam(roc_year=108, exam_name=document.title, document=document)


def load_asset_exam_with_answers(roc_year: int, answer_map: dict[int, str], notes: list[str] | None = None) -> PreparedExam:
    doc_id = ASSET_DOC_IDS[roc_year]
    document = EXTRACTION_SERVICE.load_asset_document(doc_id)
    markdown = append_answer_section(document.markdown, answer_map)
    normalized_document = AssetAwareDocument(
        doc_id=document.doc_id,
        title=document.title,
        manifest=document.manifest,
        markdown=markdown,
        markdown_path=document.markdown_path,
    )
    return PreparedExam(
        roc_year=roc_year,
        exam_name=ASSET_EXAM_NAMES.get(roc_year, document.title),
        document=normalized_document,
        answer_overrides={
            number: answer for number, answer in answer_map.items() if not re.fullmatch(r"[A-E]", answer)
        },
        notes=notes or [],
    )


def prepare_109_exam() -> PreparedExam:
    document = EXTRACTION_SERVICE.load_asset_document(ASSET_DOC_IDS[109])
    bonus_answers = {number: "BONUS" for number in range(1, 101)}
    return PreparedExam(
        roc_year=109,
        exam_name=ASSET_EXAM_NAMES[109],
        document=document,
        answer_overrides=bonus_answers,
        notes=["答案本僅標示本題送分，已以 BONUS 覆寫 1-100 題答案欄位。"],
    )


def prepare_110_exam() -> PreparedExam:
    answer_map = parse_docx_answer_table(SOURCE_DIR / "110筆試答案.docx")
    return load_asset_exam_with_answers(110, answer_map)


def prepare_111_exam() -> PreparedExam:
    answer_map = parse_answer_pairs(run_pdftotext(SOURCE_DIR / "111年筆試考題答案.pdf"))
    return load_asset_exam_with_answers(111, answer_map)


def prepare_112_exam() -> PreparedExam:
    document = EXTRACTION_SERVICE.load_asset_document(ASSET_DOC_IDS[112])
    return PreparedExam(
        roc_year=112,
        exam_name=ASSET_EXAM_NAMES[112],
        document=document,
        expected_answer_count=0,
        notes=["workspace 內未找到 112 年筆試答案來源，保留題目但答案欄位維持空白。"],
    )


def prepare_113_exam() -> PreparedExam:
    answer_map = parse_answer_pairs(run_pdftotext(SOURCE_DIR / "113年筆試考題答案.pdf"))
    return load_asset_exam_with_answers(113, answer_map)


def prepare_114_exam() -> PreparedExam:
    question_docx = SOURCE_DIR / "114年筆試考題.docx"
    rows = read_docx_table_rows(question_docx)
    blocks: list[QuestionBlock] = []
    for index, row in enumerate(rows[1:], start=1):
        paragraphs = row[0]
        blocks.append(QuestionBlock(number=index, stem=paragraphs[0], options=paragraphs[1:]))
    answer_map = parse_answer_pairs(VERIFIED_114_ANSWER_TEXT)
    markdown = build_markdown_from_blocks(blocks, answer_map)
    document = make_document("hist_114_written", "114年麻醉專科醫師甄審筆試試卷", question_docx, markdown)
    return PreparedExam(roc_year=114, exam_name=document.title, document=document)


def prepare_exams(only_years: set[int] | None = None) -> list[PreparedExam]:
    prepared: list[PreparedExam] = []
    with tempfile.TemporaryDirectory() as temp_dir_name:
        temp_root = Path(temp_dir_name)
        archive_106 = extract_archive(SOURCE_DIR / "106年專甄考古題.rar", temp_root / "106")
        archive_107 = extract_archive(SOURCE_DIR / "107年專甄題庫.rar", temp_root / "107")
        archive_108 = extract_archive(SOURCE_DIR / "108年專甄題庫.rar", temp_root / "108")
        prepared.extend(
            [
                prepare_106_exam(archive_106),
                prepare_107_exam(archive_107),
                prepare_108_exam(archive_108),
            ]
        )

    prepared.extend(
        [
            prepare_109_exam(),
            prepare_110_exam(),
            prepare_111_exam(),
            prepare_112_exam(),
            prepare_113_exam(),
            prepare_114_exam(),
        ]
    )
    if only_years is None:
        return prepared
    return [exam for exam in prepared if exam.roc_year in only_years]


def process_exam(prepared: PreparedExam, repo: SQLitePastExamRepository | None, dry_run: bool) -> dict:
    extraction = EXTRACTION_SERVICE.extract_questions(
        prepared.document,
        exam_name=prepared.exam_name,
        exam_year=prepared.gregorian_year,
    )
    for question in extraction.questions:
        override = prepared.answer_overrides.get(question.question_number)
        if override:
            question.correct_answer = override
    answer_count = sum(1 for question in extraction.questions if question.correct_answer)

    if len(extraction.questions) != prepared.expected_question_count:
        raise ValueError(
            f"{prepared.roc_year} 年題數異常：預期 {prepared.expected_question_count} 題，實得 {len(extraction.questions)} 題"
        )
    if prepared.expected_answer_count is not None and answer_count != prepared.expected_answer_count:
        raise ValueError(
            f"{prepared.roc_year} 年答案數異常：預期 {prepared.expected_answer_count} 題，實得 {answer_count} 題"
        )

    classified_questions, concepts = EXTRACTION_SERVICE.classify_questions(extraction.questions)
    past_exam = EXTRACTION_SERVICE._build_past_exam_aggregate(prepared.document, extraction, repo)
    past_exam.questions = classified_questions
    past_exam.total_questions = len(classified_questions)
    past_exam.is_classified = True

    if not dry_run and repo is not None:
        repo.save_exam(past_exam)
        repo.save_questions(past_exam.id, classified_questions)
        repo.upsert_concepts(concepts)

    return {
        "roc_year": prepared.roc_year,
        "gregorian_year": prepared.gregorian_year,
        "exam_id": past_exam.id,
        "source_doc_id": prepared.document.doc_id,
        "question_count": len(classified_questions),
        "answer_count": answer_count,
        "concept_count": len(concepts),
        "notes": prepared.notes,
    }


def print_summary(results: list[dict], dry_run: bool) -> None:
    mode = "DRY RUN" if dry_run else "IMPORTED"
    print(f"mode={mode}")
    for result in sorted(results, key=lambda item: item["roc_year"]):
        print(
            f"{result['roc_year']}({result['gregorian_year']}): "
            f"questions={result['question_count']} answers={result['answer_count']} "
            f"doc_id={result['source_doc_id']} exam_id={result['exam_id']}"
        )
        for note in result["notes"]:
            print(f"  note: {note}")


def main() -> None:
    args = parse_args()
    only_years = set(args.only) if args.only else None
    repo = None if args.dry_run else SQLitePastExamRepository(DATA_DIR / "questions.db")

    prepared_exams = prepare_exams(only_years=only_years)
    results = [process_exam(prepared, repo, dry_run=args.dry_run) for prepared in prepared_exams]
    print_summary(results, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
