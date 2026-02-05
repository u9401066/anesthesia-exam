# Decision Log

## 2026-02-05

### DEC-006: 流式生成實作方案

| 項目 | 內容 |
|------|------|
| **決策** | 使用 `st.empty()` + `st.container()` 取代 `st.spinner()` |
| **問題** | `st.spinner()` 會阻塞 UI 更新，導致「轉完才一次顯示」 |
| **解決方案** | 每 100ms 更新 `st.empty()` placeholder，實現即時顯示 |
| **影響** | `stream_crush_generate()` 函數重寫 |

### DEC-007: 出題流程架構 - 先查詢再出題

| 項目 | 內容 |
|------|------|
| **決策** | Agent 必須先查詢 RAG 知識庫，再根據真實內容出題 |
| **問題** | 直接讓 Agent 出題會產生幻覺（編造內容和來源） |
| **正確流程** | `consult_knowledge_graph()` → `search_source_location()` → `exam_save_question()` |
| **工具依賴** | asset-aware-mcp (RAG) + exam-generator (CRUD) |
| **影響** | 需要更新 Streamlit prompt，指導 Agent 執行正確流程 |

### DEC-008: 來源顯示方案 - 可展開詳情

| 項目 | 內容 |
|------|------|
| **決策** | 採用方案 B：可展開的來源詳情 |
| **備選方案** | A. 簡潔內嵌、C. 互動跳轉 PDF |
| **選擇理由** | 不增加 UI 負擔，需要時可展開看詳細來源 |
| **UI 元素** | `st.expander("📖 來源詳情")` |
| **狀態** | 待實作（需先升級 exam_save_question schema） |

---

## 2026-02-03

### DEC-001: PDF 解析工具選擇 PyMuPDF

| 項目 | 內容 |
|------|------|
| **決策** | 選擇 PyMuPDF (fitz) 作為 PDF 解析核心 |
| **備選方案** | pdf-reader-mcp, asset-aware-mcp, Marker, PyMuPDF4LLM |
| **選擇理由** | `get_text("words")` 原生提供 `line_no` 欄位，無需自己計算行號 |
| **影響** | 可實現精確到行的來源追蹤 |

### DEC-002: MCP Server 框架選擇 FastMCP

| 項目 | 內容 |
|------|------|
| **決策** | 使用 FastMCP 建立 PDF 解析 MCP Server |
| **備選方案** | 直接擴展現有 exam_server.py |
| **選擇理由** | FastMCP 輕量、Python 原生、與現有 MCP 架構一致 |
| **影響** | 需要新建 `src/infrastructure/mcp/pdf_server.py` |

### DEC-003: Source 實體結構重新設計

| 項目 | 內容 |
|------|------|
| **決策** | 新增 `SourceLocation` 資料類別，增強 `Source` 結構 |
| **變更** | 加入 `stem_source`, `answer_source`, `explanation_sources`, `is_verified`, `pdf_hash` |
| **選擇理由** | 支援精確到行的來源追蹤與驗證機制 |
| **影響** | 需要更新 JSON 序列化邏輯、MCP 工具 |
| **向後相容** | 保留 `page`, `lines`, `original_text` 舊欄位 |

### DEC-004: SQLite + Repository Pattern

| 項目 | 內容 |
|------|------|
| **決策** | 使用 SQLite 持久化 + Repository Pattern |
| **備選方案** | 繼續使用 JSON 檔案 |
| **選擇理由** | 支援查詢、統計、效能較好 |
| **影響** | 資料庫位於 `data/questions.db` |

### DEC-005: Streamlit 三欄布局

| 項目 | 內容 |
|------|------|
| **決策** | Sidebar + Main(2/3) + Chat(1/3) 布局 |
| **選擇理由** | Chat 常駐右側，主要操作在中間，導航在左側 |
| **影響** | 重寫 `app.py` 使用 `st.columns([2, 1])` |

---

## 待決策

| 議題 | 選項 | 狀態 |
|------|------|------|
| PDF 快取策略 | hash-based / mtime-based / 不快取 | 待討論 |
| 圖片題處理 | PyMuPDF 抽取 / Marker 抽取 / vision model | 待討論 |
| 來源驗證失敗處理 | 拒絕儲存 / 標記警告 / 人工審核 | 待討論 |
