# Progress

## Done

- [x] 初始化專案架構
- [x] 建立 SPEC.md 完整規格書
- [x] 複製並整合 template 規範 (bylaws, skills)
- [x] Git 配置 (u9401066)
- [x] Crush 編譯與 GitHub Copilot 認證
- [x] crush.json 配置 (copilot/gpt-5-mini)
- [x] DDD 目錄結構建立
- [x] Domain 實體: Message, Conversation, Question, Exam
- [x] MCP Server: exam_save_question, exam_list_questions, exam_create_exam, exam_get_stats
- [x] Streamlit Multi-page UI (Chat, 考題生成, 題庫管理, 統計)
- [x] Crush MCP 整合測試通過
- [x] 新增考題生成開源參考資源到 SPEC.md
- [x] SQLite 資料庫架構 + Repository Pattern
- [x] Audit 追蹤機制 (AuditAction, ActorType, AuditEntry)
- [x] MCP Server 擴展為 13 個工具 (CRUD + 審計 + 搜尋)
- [x] Question CRUD Skill 文檔
- [x] JSON → SQLite 資料遷移 (9 題)
- [x] Streamlit 三欄佈局 (側邊選單 + 操作區 + 常駐 Chat)
- [x] Port 8501 標準化 (bylaws)
- [x] PDF 解析與來源追蹤架構設計 (SPEC Section 9)
- [x] Source/SourceLocation 實體重新設計
- [x] decisionLog 記錄 (PyMuPDF, FastMCP 選型)

## Doing

- [ ] 建立 PDF 解析 MCP Server (pdf_server.py)

## Next

- [ ] Phase 1 MVP 開發
  - [ ] 串接 PDF 工具到出題流程
  - [ ] 實作來源驗證機制
  - [ ] PDF 上傳與解析
  - [ ] 原子化索引 (LightRAG)
  - [ ] 詳解品質優化

## Blocked

- [ ] 真正的來源追蹤 - 架構已設計，待實作 PDF MCP Server
  - 目前來源仍是 AI 編造的假資料
  - 已選定: PyMuPDF + FastMCP
  - 待實作: `src/infrastructure/mcp/pdf_server.py`
