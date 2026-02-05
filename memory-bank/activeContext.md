# Active Context

## Current Focus

**✅ 流式生成已完成！下一步：來源追蹤顯示設計**

流式生成題目已正常工作：
- AI 輸出即時顯示（不再等到最後才一次性顯示）
- 每儲存一題就即時在右側顯示題目卡片
- 完整 logging 追蹤每個步驟

目前待討論：
- 來源如何顯示？(文件名、頁碼、行號)
- Source entity 格式如何映射到 UI？

## 已完成

- Crush AI Agent + GitHub Copilot 認證
- MCP Server (13 個考題工具) 已連接
- SQLite 資料庫 + Repository Pattern + Audit 追蹤
- Streamlit UI (三欄佈局：側邊選單 + 操作區 + 常駐 Chat)
- Domain 實體 (Question, Exam, Source, Audit)
- **流式生成 (2026-02-05)**：stream_crush_generate() + 即時 UI 更新

## Key Files

| 檔案 | 用途 |
| ---- | ---- |
| `crush.json` | Crush 配置 (模型、MCP) |
| `src/infrastructure/mcp/exam_server.py` | MCP 考題工具 (13 個) |
| `src/presentation/streamlit/app.py` | Streamlit UI |
| `src/domain/entities/question.py` | 考題實體 |
| `src/infrastructure/persistence/sqlite_question_repo.py` | SQLite Repository |
| `data/questions.db` | SQLite 資料庫 (9 題) |

## Streamlit URL

- Local: `http://localhost:8501`

## Current Blockers

- **PDF 解析工具未串接**：無法獲取真實來源
- **來源追蹤是假的**：AI 編造頁碼/行號
- **SPEC 與實作不一致**：需要更新規格書

## Next Steps

1. **更新 SPEC.md**：定義 PDF 解析與來源追蹤需求
2. **串接 PDF 工具**：asset-aware-mcp 或 pdf-splitter-mcp
3. **重新設計出題流程**：
   - 先解析 PDF → 建立 RAG 索引
   - 出題時引用真實來源 (章節/頁碼/行號/原文)
   - 驗證來源準確性
