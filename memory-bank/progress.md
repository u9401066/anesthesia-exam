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

## Doing

- [ ] PDF 解析與來源追蹤架構設計

## Next

- [ ] Phase 1 MVP 開發
  - [ ] PDF 上傳與解析 (asset-aware-mcp)
  - [ ] 原子化索引 (LightRAG)
  - [ ] 來源追蹤強化 (頁碼、行號、原文引用)
  - [ ] 真正的出題流程（基於真實 PDF 來源）
  - [ ] 詳解品質優化

## Blocked

- [ ] 真正的來源追蹤 - 需要 PDF 解析工具串接
  - 目前來源是 AI 編造的假資料
  - 需要: asset-aware-mcp 或類似 PDF 工具
