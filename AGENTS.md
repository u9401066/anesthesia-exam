# AGENTS.md

這個 workspace 就是 anesthesia-exam repo 根目錄。

## 啟動規則

- 先讀 .github/copilot-instructions.md，再視任務補讀 CONSTITUTION.md、SPEC.md、ARCHITECTURE.md。
- Python 一律優先用 uv。
- 維持 DDD 邊界：Presentation -> Application -> Domain <- Infrastructure。
- 技能放在 skills/*/SKILL.md；repo 已把 skills 連到 .claude/skills。

## 題庫與教材工作流

- 教材型出題一律先走 MCP，不可先寫題再補來源。
- 正式教材出題流程：consult_knowledge_graph -> search_source_location -> exam_save_question。
- 若 consult_knowledge_graph 暫時不可用，可退回章節/全文閱讀或其他 asset-aware 工具，但不可捏造 citation。
- 需要精確頁碼/行號時，ETL 優先使用 Marker 路徑並保留 blocks.json。
- 對題目討論、審題、詳解補寫時，優先使用目前畫面帶入的題目上下文與 source metadata。

## 重要路徑

- .github/copilot-instructions.md
- .github/prompts/
- .claude/skills/
- src/
- scripts/
- data/

## Repo MCP

- exam-generator：題目 CRUD、驗證、考卷組裝。
- asset-aware：教材 ingest、section/source asset、search_source_location、knowledge graph。

## 安全邊界

- 不要做 destructive command，除非明確要求。
- 對外發送、推送、刪除資料前先停下來確認。