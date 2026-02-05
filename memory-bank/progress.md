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
- [x] **流式生成實作完成 (2026-02-05)**
  - 移除 st.spinner() 阻塞
  - 使用 st.empty() + st.container() 即時 UI 更新
  - parse_mcp_result() 即時解析 MCP 工具結果
  - render_question_card_inline() 即時顯示題目
  - 完整 logging 追蹤
- [x] 修復 source.get() NoneType 錯誤
- [x] **文檔與 Skills 更新 (2026-02-05)**
  - copilot-instructions.md: 新增 MCP Server 架構表、正確出題流程
  - decisionLog.md: DEC-006/007/008 (MCP 雙伺服器/先查後出/可展開來源)
  - mcq-generator Skill v2.0.0: 使用 MCP 工具查詢來源
  - source-tracker Skill v2.0.0: 使用 MCP 工具驗證來源
  - question-crud Skill v2.0.0: 強調來源必須真實
- [x] **P0 實作完成 (2026-02-05)**
  - exam_save_question schema 升級支援完整 Source 結構
  - Streamlit prompt 更新：有已索引教材時引導正確流程
  - 可展開來源顯示 UI (render_source_info)
  - asset-aware-mcp 整合：已索引文件下拉選單
- [x] **Marker 整合到標準 ingest 流程 (2026-02-03)**
  - `ingest_documents(use_marker=True)` 產出 blocks.json
  - IngestResult 新增 `backend` 欄位追蹤使用的解析器
  - 支援 lazy-load Marker extractor (避免啟動時載入重模型)
  - 研究 Unstructured.io (13.9k stars) 作為未來備選方案

## Doing

(目前無進行中任務)

## Next

### P1 (重要)

- [ ] 測試完整出題流程（需要先索引一份 PDF）
- [ ] 優化來源顯示樣式

### P2 (改善)

- [ ] 實作互動式 PDF 跳轉（點擊來源開啟 PDF）
- [ ] 詳解品質優化
- [ ] 來源驗證機制自動化

## Blocked

(目前無阻塞項目)
