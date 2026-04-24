"""Support preview generation and formal evidence packing for textbook-derived questions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from src.application.services.past_exam_extraction_service import PastExamExtractionService
from src.infrastructure.logging import get_logger

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_DATA_DIR = PROJECT_ROOT / "data"
logger = get_logger(__name__)

MATCH_STOPWORDS = {
    "about",
    "after",
    "among",
    "because",
    "between",
    "choice",
    "correct",
    "during",
    "following",
    "from",
    "goal",
    "incorrect",
    "patient",
    "question",
    "regarding",
    "therapy",
    "these",
    "this",
    "those",
    "under",
    "which",
    "with",
}


def _normalize_text(value: str) -> str:
    cleaned = re.sub(r"<!--.*?-->", " ", value)
    cleaned = cleaned.replace("`", " ")
    cleaned = re.sub(r"[_*#>\-]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned)
    return cleaned.strip().lower()


def _truncate_text(value: str, limit: int) -> str:
    compact = re.sub(r"\s+", " ", value).strip()
    if len(compact) <= limit:
        return compact
    return compact[: max(limit - 3, 0)].rstrip() + "..."


def _dedupe_preserve_order(values: list[str]) -> list[str]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        normalized = value.strip()
        if not normalized or normalized in seen:
            continue
        seen.add(normalized)
        deduped.append(normalized)
    return deduped


class TextbookGenerationService:
    """Assemble textbook context, preview metadata, and formal evidence packs."""

    def __init__(self, data_dir: Path | None = None):
        self.data_dir = data_dir or DEFAULT_DATA_DIR
        self.asset_loader = PastExamExtractionService(self.data_dir)
        self._source_readiness_cache: dict[str, tuple[tuple[int, int], dict[str, Any]]] = {}
        logger.debug("textbook_generation_service_initialized", data_dir=str(self.data_dir))

    def assess_document_source_readiness(self, doc_id: str) -> dict[str, Any]:
        """Check whether a document has searchable blocks with persisted line metadata."""
        log = logger.bind(doc_id=doc_id)
        doc_dir = self.data_dir / doc_id
        blocks_path = doc_dir / "blocks.json"
        if not blocks_path.exists():
            result = {
                "doc_id": doc_id,
                "source_ready": False,
                "has_blocks": False,
                "searchable_block_count": 0,
                "precise_block_count": 0,
                "gate_reasons": ["缺少 blocks.json"],
            }
            log.info("textbook_source_readiness_checked", **result)
            return result

        try:
            stat = blocks_path.stat()
            cache_key = (stat.st_mtime_ns, stat.st_size)
        except OSError:
            cache_key = (0, 0)

        cached = self._source_readiness_cache.get(doc_id)
        if cached and cached[0] == cache_key:
            return dict(cached[1])

        try:
            blocks = json.loads(blocks_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            result = {
                "doc_id": doc_id,
                "source_ready": False,
                "has_blocks": True,
                "searchable_block_count": 0,
                "precise_block_count": 0,
                "gate_reasons": [f"blocks.json 無法讀取: {exc}"],
            }
            self._source_readiness_cache[doc_id] = (cache_key, result)
            log.info("textbook_source_readiness_checked", **result)
            return dict(result)

        searchable_blocks = [block for block in blocks if self._block_has_searchable_text(block)]
        precise_blocks = [
            block
            for block in searchable_blocks
            if isinstance((block.get("metadata") or {}).get("line_start"), int)
            and isinstance((block.get("metadata") or {}).get("line_end"), int)
            and int(block.get("page") or 0) > 0
        ]

        gate_reasons: list[str] = []
        if not searchable_blocks:
            gate_reasons.append("blocks.json 缺少可搜尋文字")
        if not precise_blocks:
            gate_reasons.append("blocks.json 缺少 line metadata")

        result = {
            "doc_id": doc_id,
            "source_ready": not gate_reasons,
            "has_blocks": True,
            "searchable_block_count": len(searchable_blocks),
            "precise_block_count": len(precise_blocks),
            "gate_reasons": gate_reasons,
        }
        self._source_readiness_cache[doc_id] = (cache_key, result)
        log.info("textbook_source_readiness_checked", **result)
        return dict(result)

    def build_prompt_context(
        self,
        doc_ids: list[str],
        selected_sections: list[dict] | None = None,
        *,
        max_chars: int = 8000,
    ) -> dict[str, Any]:
        """Build section/chapter/full-text context for preview or formal generation prompts."""
        logger.debug(
            "textbook_prompt_context_start",
            document_count=len(doc_ids),
            selected_section_count=len(selected_sections or []),
            max_chars=max_chars,
        )
        if not doc_ids:
            return {"documents": [], "prompt_context": "", "selected_section_titles": []}

        selected_by_doc: dict[str, list[dict]] = {}
        for section in selected_sections or []:
            doc_id = str(section.get("doc_id") or "").strip()
            if doc_id:
                selected_by_doc.setdefault(doc_id, []).append(section)

        prompt_chunks: list[str] = []
        documents: list[dict[str, Any]] = []
        selected_titles: list[str] = []
        remaining_chars = max_chars

        for doc_id in doc_ids:
            document = self.asset_loader.load_asset_document(doc_id)
            parsed_sections = self._parse_markdown_sections(document.markdown)
            chapter_title = parsed_sections[0]["title"] if parsed_sections else document.title

            excerpts: list[str] = []
            for requested in selected_by_doc.get(doc_id, []):
                selected_title = str(requested.get("title") or "").strip()
                matched = self._find_section(parsed_sections, selected_title)
                excerpt = matched["body"] if matched else requested.get("preview", "")
                excerpt = _truncate_text(excerpt, 1800)
                if excerpt:
                    selected_titles.append(selected_title)
                    excerpts.append(f"### {selected_title}\n{excerpt}")

            if not excerpts:
                headings = ", ".join(section["title"] for section in parsed_sections[:8])
                cleaned_markdown = self._clean_markdown_excerpt(document.markdown)
                excerpt = _truncate_text(cleaned_markdown, 2400)
                summary_lines = [f"### {document.title}"]
                if headings:
                    summary_lines.append(f"Headings: {headings}")
                if excerpt:
                    summary_lines.append(excerpt)
                excerpts.append("\n".join(summary_lines))

            doc_context = "\n\n".join(excerpts)
            documents.append(
                {
                    "doc_id": doc_id,
                    "title": document.title,
                    "chapter_title": chapter_title,
                    "selected_sections": [section.get("title", "") for section in selected_by_doc.get(doc_id, [])],
                    "context_excerpt": doc_context,
                }
            )

            if remaining_chars > 0 and doc_context:
                limited = _truncate_text(doc_context, remaining_chars)
                if limited:
                    prompt_chunks.append(limited)
                    remaining_chars = max(0, remaining_chars - len(limited))

        result = {
            "documents": documents,
            "prompt_context": "\n\n".join(prompt_chunks),
            "selected_section_titles": _dedupe_preserve_order(selected_titles),
        }
        logger.info(
            "textbook_prompt_context_complete",
            document_count=len(documents),
            selected_section_count=len(result["selected_section_titles"]),
            prompt_chars=len(result["prompt_context"]),
        )
        return result

    def enrich_generated_questions(
        self,
        questions: list[dict],
        *,
        selected_doc_ids: list[str],
        selected_sections: list[dict] | None = None,
        preview_only: bool,
    ) -> list[dict]:
        """Attach preview metadata or formal evidence packs to generated question dicts."""
        if not questions:
            return []

        logger.info(
            "textbook_question_enrichment_start",
            question_count=len(questions),
            document_count=len(selected_doc_ids),
            preview_only=preview_only,
        )

        prompt_context = self.build_prompt_context(
            selected_doc_ids,
            selected_sections,
            max_chars=6000,
        )
        readiness_by_doc = {
            doc_id: self.assess_document_source_readiness(doc_id) for doc_id in selected_doc_ids
        }

        enriched_questions: list[dict] = []
        for question in questions:
            item = json.loads(json.dumps(question, ensure_ascii=False))
            if preview_only:
                enriched_questions.append(
                    self._apply_preview_metadata(item, prompt_context, selected_doc_ids, selected_sections or [])
                )
            else:
                enriched_questions.append(
                    self._apply_formal_evidence_pack(
                        item,
                        prompt_context,
                        selected_doc_ids,
                        selected_sections or [],
                        readiness_by_doc,
                    )
                )
        logger.info(
            "textbook_question_enrichment_complete",
            question_count=len(enriched_questions),
            formal_ready_count=sum(1 for question in enriched_questions if question.get("formal_save_ready")),
            preview_only=preview_only,
        )
        return enriched_questions

    def build_evidence_pack_for_question(
        self,
        question: dict,
        *,
        selected_doc_ids: list[str],
        selected_sections: list[dict] | None = None,
    ) -> dict[str, Any]:
        """Build a formal evidence pack for an existing question without mutating it."""
        if not selected_doc_ids:
            return {
                "source_ready": False,
                "matched_doc_id": None,
                "matched_doc_title": None,
                "gate_reasons": ["缺少教材 doc_id"],
                "source": {},
            }

        prompt_context = self.build_prompt_context(
            selected_doc_ids,
            selected_sections,
            max_chars=6000,
        )
        readiness_by_doc = {
            doc_id: self.assess_document_source_readiness(doc_id) for doc_id in selected_doc_ids
        }
        return self._build_evidence_pack(
            question,
            selected_doc_ids,
            selected_sections or [],
            readiness_by_doc,
            prompt_context,
        )

    def question_formal_save_ready(self, question: dict) -> bool:
        """Return whether a question has a complete formal-save evidence pack."""
        if str(question.get("pattern") or "").strip().lower() == "image_based":
            return False

        if "formal_save_ready" in question:
            return bool(question.get("formal_save_ready"))

        source = question.get("source") or {}
        stem_source = source.get("stem_source") or {}
        answer_source = source.get("answer_source") or {}
        explanation_sources = source.get("explanation_sources") or []
        return bool(
            source.get("document")
            and stem_source.get("page")
            and stem_source.get("original_text")
            and answer_source.get("page")
            and answer_source.get("original_text")
            and explanation_sources
        )

    def _apply_preview_metadata(
        self,
        question: dict,
        prompt_context: dict[str, Any],
        selected_doc_ids: list[str],
        selected_sections: list[dict],
    ) -> dict:
        source = dict(question.get("source") or {})
        context_document = prompt_context.get("documents", [{}])[0] if prompt_context.get("documents") else {}
        if context_document and not source.get("document"):
            source["document"] = context_document.get("title", "")
        if context_document and not source.get("chapter"):
            source["chapter"] = context_document.get("chapter_title")
        if selected_sections and not source.get("section"):
            source["section"] = selected_sections[0].get("title")
        if source:
            question["source"] = source

        question["preview_only"] = True
        question["formal_save_ready"] = False
        question["generation_mode"] = "preview_only"
        question["evidence_pack"] = {
            "source_ready": False,
            "matched_doc_id": selected_doc_ids[0] if selected_doc_ids else None,
            "matched_doc_title": source.get("document", ""),
            "gate_reasons": [
                "preview-only 模式只使用 section/chapter/full text 上下文，不可直接正式入庫。"
            ],
            "context_sections": prompt_context.get("selected_section_titles", []),
        }
        return question

    def _apply_formal_evidence_pack(
        self,
        question: dict,
        prompt_context: dict[str, Any],
        selected_doc_ids: list[str],
        selected_sections: list[dict],
        readiness_by_doc: dict[str, dict[str, Any]],
    ) -> dict:
        evidence_pack = self._build_evidence_pack(
            question,
            selected_doc_ids,
            selected_sections,
            readiness_by_doc,
            prompt_context,
        )
        question["preview_only"] = False
        question["generation_mode"] = "formal"
        question["formal_save_ready"] = bool(evidence_pack.get("source_ready"))
        question["evidence_pack"] = evidence_pack
        if evidence_pack.get("source"):
            question["source"] = evidence_pack["source"]
        return question

    def _build_evidence_pack(
        self,
        question: dict,
        selected_doc_ids: list[str],
        selected_sections: list[dict],
        readiness_by_doc: dict[str, dict[str, Any]],
        prompt_context: dict[str, Any],
    ) -> dict[str, Any]:
        gate_reasons: list[str] = []
        log = logger.bind(
            question_id=question.get("id"),
            question_text=_truncate_text(str(question.get("question_text") or ""), 120),
        )
        if not selected_doc_ids:
            gate_reasons.append("缺少教材 doc_id")
            result = {"source_ready": False, "gate_reasons": gate_reasons, "source": {}}
            log.info("textbook_evidence_pack_built", source_ready=False, matched_doc_id=None, gate_reasons=gate_reasons)
            return result

        preferred_sections = [section.get("title", "") for section in selected_sections if section.get("title")]
        best_pack: dict[str, Any] | None = None

        for doc_id in selected_doc_ids:
            readiness = readiness_by_doc.get(doc_id) or self.assess_document_source_readiness(doc_id)
            if not readiness.get("source_ready"):
                gate_reasons.extend(readiness.get("gate_reasons", []))
                continue

            document = self.asset_loader.load_asset_document(doc_id)
            blocks = self._load_blocks(doc_id)
            candidate_blocks = [block for block in blocks if self._block_has_precise_source(block)]
            if not candidate_blocks:
                gate_reasons.append(f"{doc_id} 缺少可精確引用的 block")
                continue

            stem_queries = self._stem_queries(question)
            answer_queries = self._answer_queries(question)
            explanation_queries = self._explanation_queries(question)

            stem_match = self._find_best_match(candidate_blocks, stem_queries, preferred_sections)
            answer_match = self._find_best_match(candidate_blocks, answer_queries, preferred_sections)
            explanation_matches = self._find_explanation_matches(
                candidate_blocks,
                explanation_queries,
                preferred_sections,
            )

            if not explanation_matches:
                explanation_matches = _dedupe_preserve_order([
                    block_id
                    for block_id in [stem_match.get("block_id") if stem_match else "", answer_match.get("block_id") if answer_match else ""]
                    if block_id
                ])
                explanation_matches = [
                    self._find_block_by_id(candidate_blocks, block_id) for block_id in explanation_matches
                ]
                explanation_matches = [match for match in explanation_matches if match]

            source_payload = self._build_source_payload(document.title, stem_match, answer_match, explanation_matches)

            local_gate_reasons = []
            if not source_payload.get("stem_source"):
                local_gate_reasons.append("找不到題幹來源")
            if not source_payload.get("answer_source"):
                local_gate_reasons.append("找不到答案依據")
            if not source_payload.get("explanation_sources"):
                local_gate_reasons.append("找不到詳解來源")

            score = float(stem_match.get("score", 0.0) if stem_match else 0.0) + float(
                answer_match.get("score", 0.0) if answer_match else 0.0
            )
            pack = {
                "source_ready": not local_gate_reasons,
                "matched_doc_id": doc_id,
                "matched_doc_title": document.title,
                "gate_reasons": local_gate_reasons,
                "queries": {
                    "stem": stem_queries,
                    "answer": answer_queries,
                    "explanation": explanation_queries,
                },
                "source": source_payload,
                "score": score,
                "context_sections": prompt_context.get("selected_section_titles", []),
            }
            if best_pack is None:
                best_pack = pack
            elif pack["source_ready"] and not best_pack.get("source_ready"):
                best_pack = pack
            elif pack["source_ready"] == bool(best_pack.get("source_ready")) and pack["score"] > best_pack["score"]:
                best_pack = pack

        if best_pack is None:
            result = {
                "source_ready": False,
                "matched_doc_id": None,
                "matched_doc_title": None,
                "gate_reasons": _dedupe_preserve_order(gate_reasons or ["沒有可用的 source-ready 文件"]),
                "source": {},
            }
            log.info(
                "textbook_evidence_pack_built",
                source_ready=False,
                matched_doc_id=None,
                gate_reasons=result["gate_reasons"],
            )
            return result

        if not best_pack.get("source_ready"):
            best_pack["gate_reasons"] = _dedupe_preserve_order(
                list(best_pack.get("gate_reasons", [])) + gate_reasons
            )
        log.info(
            "textbook_evidence_pack_built",
            source_ready=bool(best_pack.get("source_ready")),
            matched_doc_id=best_pack.get("matched_doc_id"),
            score=best_pack.get("score"),
            gate_reasons=best_pack.get("gate_reasons", []),
        )
        return best_pack

    def _build_source_payload(
        self,
        document_title: str,
        stem_match: dict[str, Any] | None,
        answer_match: dict[str, Any] | None,
        explanation_matches: list[dict[str, Any]],
    ) -> dict[str, Any]:
        reference_match = stem_match or answer_match or (explanation_matches[0] if explanation_matches else None)
        chapter = None
        section = None
        if reference_match:
            hierarchy_values = list((reference_match.get("section_hierarchy") or {}).values())
            if hierarchy_values:
                chapter = hierarchy_values[0]
                section = hierarchy_values[-1]

        return {
            "document": document_title,
            "chapter": chapter,
            "section": section,
            "stem_source": self._to_source_location(stem_match),
            "answer_source": self._to_source_location(answer_match),
            "explanation_sources": [
                location
                for match in explanation_matches
                if (location := self._to_source_location(match))
            ],
        }

    def _to_source_location(self, match: dict[str, Any] | None) -> dict[str, Any] | None:
        if not match:
            return None

        metadata = match.get("metadata") or {}
        line_start = metadata.get("line_start")
        line_end = metadata.get("line_end")
        if not isinstance(line_start, int) or not isinstance(line_end, int):
            return None

        return {
            "page": int(match.get("page") or 0),
            "line_start": line_start + 1,
            "line_end": line_end + 1,
            "bbox": match.get("bbox") or None,
            "original_text": _truncate_text(match.get("text", ""), 500),
        }

    def _find_explanation_matches(
        self,
        blocks: list[dict[str, Any]],
        explanation_queries: list[str],
        preferred_sections: list[str],
    ) -> list[dict[str, Any]]:
        matches: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for query in explanation_queries[:3]:
            match = self._find_best_match(blocks, [query], preferred_sections)
            block_id = str(match.get("block_id") or "") if match else ""
            if match and block_id and block_id not in seen_ids:
                seen_ids.add(block_id)
                matches.append(match)
        return matches

    def _find_best_match(
        self,
        blocks: list[dict[str, Any]],
        queries: list[str],
        preferred_sections: list[str],
    ) -> dict[str, Any] | None:
        best_match: dict[str, Any] | None = None
        best_score = 0.0
        section_hints = [_normalize_text(title) for title in preferred_sections if title]

        for query in queries:
            normalized_query = _normalize_text(query)
            if not normalized_query:
                continue
            query_tokens = self._match_tokens(normalized_query)
            if not query_tokens:
                continue

            for block in blocks:
                block_text = str(block.get("text") or "")
                normalized_block = _normalize_text(block_text)
                if not normalized_block:
                    continue

                score = 0.0
                if normalized_query in normalized_block:
                    score += 1.6

                overlap = sum(1 for token in query_tokens if token in normalized_block)
                if overlap:
                    score += overlap / len(query_tokens)

                block_sections = [_normalize_text(value) for value in (block.get("section_hierarchy") or {}).values()]
                if section_hints and any(
                    hint in block_section or block_section in hint
                    for hint in section_hints
                    for block_section in block_sections
                    if hint and block_section
                ):
                    score += 0.35

                if block.get("block_type") == "SectionHeader" and len(query_tokens) <= 8:
                    score += 0.1

                if score > best_score and score >= 0.34:
                    best_score = score
                    best_match = {
                        **block,
                        "score": round(score, 4),
                    }

        return best_match

    @staticmethod
    def _find_block_by_id(blocks: list[dict[str, Any]], block_id: str) -> dict[str, Any] | None:
        for block in blocks:
            if str(block.get("block_id") or "") == block_id:
                return block
        return None

    def _load_blocks(self, doc_id: str) -> list[dict[str, Any]]:
        blocks_path = self.data_dir / doc_id / "blocks.json"
        if not blocks_path.exists():
            return []
        try:
            return json.loads(blocks_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return []

    @staticmethod
    def _block_has_searchable_text(block: dict[str, Any]) -> bool:
        return bool(_normalize_text(str(block.get("text") or ""))) and int(block.get("page") or 0) > 0

    def _block_has_precise_source(self, block: dict[str, Any]) -> bool:
        if not self._block_has_searchable_text(block):
            return False
        metadata = block.get("metadata") or {}
        return isinstance(metadata.get("line_start"), int) and isinstance(metadata.get("line_end"), int)

    def _stem_queries(self, question: dict) -> list[str]:
        topics = " ".join(question.get("topics", []))
        base = str(question.get("question_text") or "").strip()
        queries = [base, f"{base} {topics}".strip()]
        return _dedupe_preserve_order([query for query in queries if query])

    def _answer_queries(self, question: dict) -> list[str]:
        answer_text = self._answer_option_text(question)
        explanation_sentences = self._explanation_queries(question)
        combined_queries = [
            answer_text,
            f"{question.get('question_text', '')} {answer_text}".strip(),
            f"{answer_text} {explanation_sentences[0]}".strip() if explanation_sentences else answer_text,
        ]
        return _dedupe_preserve_order([query for query in combined_queries if query])

    def _explanation_queries(self, question: dict) -> list[str]:
        explanation = str(question.get("explanation") or "").strip()
        if not explanation:
            return []
        sentences = [
            sentence.strip()
            for sentence in re.split(r"(?<=[。！？.!?])\s+", explanation)
            if sentence.strip()
        ]
        sentences = sorted(sentences, key=len, reverse=True)
        return _dedupe_preserve_order(sentences[:3])

    @staticmethod
    def _answer_option_text(question: dict) -> str:
        answer = str(question.get("correct_answer") or "").strip().upper()
        options = question.get("options", []) or []
        if len(answer) == 1 and "A" <= answer <= "Z":
            index = ord(answer) - ord("A")
            if 0 <= index < len(options):
                return str(options[index]).strip()
        return answer

    @staticmethod
    def _match_tokens(normalized_query: str) -> list[str]:
        tokens = re.findall(r"[a-z0-9]{3,}", normalized_query)
        return [token for token in tokens if token not in MATCH_STOPWORDS]

    def _parse_markdown_sections(self, markdown: str) -> list[dict[str, Any]]:
        lines = markdown.splitlines()
        sections: list[dict[str, Any]] = []

        for index, line in enumerate(lines):
            match = re.match(r"^(#{1,6})\s+(.+)$", line.strip())
            if not match:
                continue

            level = len(match.group(1))
            title = re.sub(r"\*+", "", match.group(2)).strip()
            end_index = len(lines)
            for next_index in range(index + 1, len(lines)):
                next_match = re.match(r"^(#{1,6})\s+(.+)$", lines[next_index].strip())
                if next_match and len(next_match.group(1)) <= level:
                    end_index = next_index
                    break

            body = "\n".join(lines[index + 1 : end_index]).strip()
            sections.append(
                {
                    "title": title,
                    "level": level,
                    "body": self._clean_markdown_excerpt(body),
                }
            )

        return sections

    def _find_section(self, parsed_sections: list[dict[str, Any]], title: str) -> dict[str, Any] | None:
        normalized_title = _normalize_text(title)
        for section in parsed_sections:
            candidate = _normalize_text(section.get("title", ""))
            if candidate == normalized_title or normalized_title in candidate or candidate in normalized_title:
                return section
        return None

    @staticmethod
    def _clean_markdown_excerpt(markdown: str) -> str:
        without_page_markers = re.sub(r"<!--\s*Page\s+\d+\s*-->", " ", markdown)
        lines = [line.strip() for line in without_page_markers.splitlines() if line.strip()]
        return "\n".join(lines)


_service: TextbookGenerationService | None = None


def get_textbook_generation_service() -> TextbookGenerationService:
    """Return singleton textbook generation support service."""
    global _service
    if _service is None:
        _service = TextbookGenerationService()
        logger.debug("textbook_generation_service_singleton_created")
    return _service


def question_formal_save_ready(question: dict) -> bool:
    """Convenience facade for UI/controller callers that need the formal-save gate."""
    return get_textbook_generation_service().question_formal_save_ready(question)
