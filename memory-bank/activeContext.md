# Active Context

## Current Focus

考題生成系統基礎架構已完成，可進行端到端測試。

## 已完成

- Crush AI Agent + GitHub Copilot 認證
- MCP Server (4 個考題工具) 已連接
- Streamlit UI (4 頁面：Chat, 考題生成, 題庫管理, 統計)
- Domain 實體 (Question, Exam, Source)

## Key Files

| 檔案 | 用途 |
| ---- | ---- |
| `crush.json` | Crush 配置 (模型、MCP) |
| `src/infrastructure/mcp/exam_server.py` | MCP 考題工具 |
| `src/presentation/streamlit/app.py` | Streamlit UI |
| `src/domain/entities/question.py` | 考題實體 |
| `src/domain/entities/exam.py` | 考卷實體 |

## Streamlit URL

- Local: `http://localhost:8503`
- Crush 已連接 exam-generator MCP Server

## Current Blockers

- None

## Next Steps

1. 在 Streamlit UI 測試完整考題生成流程
2. 加入 PDF 解析 (asset-aware-mcp)
3. 強化來源追蹤
