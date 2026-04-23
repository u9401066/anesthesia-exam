# System Patterns

## Architectural Patterns

- Pattern 1: Description

## Design Patterns

- Repository Pattern + SQLite migrations
- MCP Tool Boundary for closed-loop exam workflows
- File-based job contract for external-agent backfill
- Streamlit presentation slice: `app.py` 只保留頁面組裝，局部互動區拆成 controller + fragments，正式 use case 盡量下沉到 application service
- Asset audit gate: 教材 figure refresh 後必須用固定 audit 腳本驗證 path / tiny / variance / page explosion，不以人工抽樣或單頁 smoke 宣稱完成

## Common Idioms

- `session_state` 作為 Streamlit workflow 狀態機
- `Source.to_dict()` / `Source.from_dict()` 保持精確來源 round-trip
- 以 JSON artifacts 持久化 pipeline run / heartbeat jobs，避免對話中斷導致狀態遺失

## Streamlit-First Orchestration

UI 層由 Streamlit 直接編排生成流程與互動狀態，使用 session_state 管理生成/練習生命週期，並以 placeholder（st.empty/container）呈現流式輸出與即時題目預覽。

### Examples

- src/presentation/streamlit/app.py


## Streamlit Controller + Fragment Split

當單一頁面的某個互動區同時包含大量 render 與 save/promote 行為時，先在 Presentation 層切出 `controller.py` 與 `fragments.py`，並把正式 persistence use case 下沉到 Application service；這是比「一次拆完整頁面」更安全的 DDD 收斂方式。

### Examples

- src/presentation/streamlit/generation/controller.py
- src/presentation/streamlit/generation/fragments.py
- src/application/services/question_review_service.py


## Repository + Audit Trail

題目資料透過 SQLite Repository 統一存取，所有關鍵操作（create/update/delete/validate/restore）附帶審計記錄，支援後續追溯與驗證。

### Examples

- src/infrastructure/persistence/sqlite_question_repo.py
- src/infrastructure/mcp/exam_server.py


## MCP Tool Boundary

Agent 透過 exam-generator MCP 工具邊界操作題庫，工具 schema 承載來源欄位與生成上下文，避免 UI/Agent 直接耦合資料層細節。

### Examples

- src/infrastructure/mcp/exam_server.py
- src/domain/entities/question.py


## File-Based Backfill Contract

heartbeat 不直接在 Web UI 內呼叫 agent；它只分析 coverage gap / backlog，並把工作輸出成 `data/jobs/*.json`，由外部 agent 或 OpenClaw 消費後再回寫結果。

### Examples

- src/application/services/heartbeat_service.py
- scripts/run_heartbeat.py
- src/presentation/streamlit/app.py


## Asset Refresh + Audit Gate

教材圖像修復採「只刷新 figure assets，再以 audit 報告驗證」的可重跑模式。全章節刷新不應重建 markdown/blocks/tables/KG，避免為了修圖污染已可用的文字資料面；品質判斷則以機器可重跑的 path/size/variance/page-density 指標為準。

### Examples

- scripts/refresh_miller_figures.py
- scripts/audit_miller_image_quality.py
- configs/asset-aware/miller_marker_hq.json
