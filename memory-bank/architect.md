# MemoriPilot: System Architect

## Overview
This file contains the architectural decisions and design patterns for the MemoriPilot project.

## Architectural Decisions

1. **Decision 1**: Description of the decision and its rationale.
2. **Decision 2**: Description of the decision and its rationale.
3. **Decision 3**: Description of the decision and its rationale.

## 2026-04-23 Miller Asset-Aware Figure Pipeline

- Miller textbook figure assets now have an explicit operational boundary: full-text markdown / blocks / tables are not rebuilt when only figure quality needs repair; use `scripts/refresh_miller_figures.py` for figure-only refresh
- Figure extraction quality is gated by reusable audit reports from `scripts/audit_miller_image_quality.py`, with checks for missing paths, old absolute prefixes, tiny assets, low-variance assets, and page-level figure explosions
- Asset-aware now supports a Miller-specific ETL profile via `configs/asset-aware/miller_marker_hq.json`; OpenCode/Crush MCP env should point asset-aware at that profile for textbook work
- Caption extraction must be best-effort and bounded. A single pathological chapter may lose caption attachment, but it must not block the whole batch; targeted caption recovery is the follow-up layer
- Future explanation/question generation should consume figure assets only after passing the audit gate; do not use old manifest snapshots that predate the 2026-04-23 refresh

## 2026-04-21 Streamlit Generation Slice

- `src/presentation/streamlit/app.py` 不再承擔所有生成頁 review/save 細節；生成後審閱區已拆成 presentation 子模組 `src/presentation/streamlit/generation/`
- `controller.py` 負責 UI action dispatch 與 session-state 級控制流，`fragments.py` 負責 Streamlit render fragments
- 正式入庫的 review use case 不直接留在 Streamlit，而是下沉到 `src/application/services/question_review_service.py`
- 這個切法是局部 DDD 收斂：先把「正式入庫 use case」與「UI 渲染」分開，再考慮下一刀是否繼續拆 prompt orchestration 或 MCP tool handlers

## 2026-04-21 MCP Exam Server Slice

- `src/infrastructure/mcp/exam_server.py` 不再直接承擔全部題庫型 MCP tool 業務邏輯；題庫 save/list/create/stats/get/delete/validate/update/audit/search/restore/bulk 已先下沉到 `src/application/services/exam_tool_application_service.py`
- MCP 名稱分派不再使用單一巨大 `if/elif` 鏈，而是改由 `src/infrastructure/mcp/exam_tool_handlers.py` 建立 registry；這讓題庫型 handlers 與 legacy pipeline/past-exam handlers 可以逐步切開
- `exam_server.save_question()` 等 module-level wrappers 目前刻意保留，因為現有測試與 monkeypatch path 直接依賴這層 API；application adapter 採 per-call 建立，避免 module import 時綁死舊 repo/paths
- 下一刀應繼續把 `get_generation_guide / get_topics` 或 past-exam handlers 抽離，但 pipeline harness 先維持原地，避免同一輪同時改動 state machine 與 transport wiring

## 2026-04-21 Past Exam Explanation Slice

- `src/application/services/past_exam_explanation_service.py` 建立了一個新的 application 邊界：它不直接依賴 Streamlit widget state，而是專注在 `question -> repo reference matches -> LLM prompt -> explanation persistence`
- 這個 slice 刻意不走 MCP tool-calling；因為補寫考古題詳解的 immediate value 在「用現有 repo 資料幫使用者學習」，不在教材來源追蹤或跨 MCP orchestration
- `SQLitePastExamRepository` 因此補了 `list_all_questions()` 與 `update_question_explanation()` 兩個較窄的 read/write API，避免 Streamlit 自己去拼 SQL 或整包重存 exam aggregate
- Web 端目前把這條能力掛在 `📚 題庫管理 -> 歷屆題庫`；若後續要擴成 practice review inline 補寫、版本歷史或 reviewer approval，應繼續沿用這個 application slice，而不是把 explain generation code 回塞到 `app.py` 大頁面中
