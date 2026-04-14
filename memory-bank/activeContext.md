# Active Context

## Current Goals

- 已完成 asset-aware 子模組更新、large-PDF/page-range ingestion 強化與 past-exam-extraction 端到端實作；目前重點轉為讓 UI / prompts / agents 正式消費新工具鏈。

## Current Focus

**2026-04-14 補充：`libs/asset-aware-mcp` 已完成並發布 large-PDF ingestion 強化。Marker parse 現在會在頁數超過 800 頁時自動 chunk，遇到高圖片量 PDF 時自動停用 figure extraction；另外也新增真正的 `page_ranges` ingestion，會先 materialize `selected_pages.pdf` 再把 subset-local page number remap 回原始 PDF，避免來源頁碼失真，並用 page-range scope 避免 `doc_id` collision。子模組 commit 已推到 `7b1c6d5`，主 repo submodule pointer 已更新到 `841298d`。**

**2026-04-14 補充：已完成 reviewed-only / exam_track / scope request / heartbeat 這條 Web 治理切片。題庫資料模型現在支援 `exam_track`、`is_validated`、`validation_notes`；Streamlit 已補上 `📋 出題需求` 頁、題庫審查按鈕，以及 heartbeat / backlog 統計。Heartbeat 採 file-based contract，會把補題工作寫到 `data/jobs/*.json` 供外部 agent / OpenClaw 讀取。**

**2026-04-14 補充：已修正一個關鍵資料保真問題。`Question.source` 若只走舊的 page/line flatten 流程，會遺失 `stem_source` / `answer_source` / `explanation_sources`，導致 UI 看起來有來源但其實精確資訊已掉失；目前已統一改成 `Source.to_dict()` / `Source.from_dict()` round-trip。**

**2026-04-14 補充：已完成 Web 需求盤點並回寫 SPEC / ROADMAP。六項需求目前判定為：#1 快速作答已達基本需求；#2 指定教材/章節組卷部分達成；#3 使用者 scope request + heartbeat backfill 未實作；#4 管理者審查與 reviewed-only 使用部分達成；#5 後台 past-exam / template 雛形已具備但未串進 Web；#6 tag / exam_track 選題部分達成，仍缺正式 taxonomy。**

**2026-04-14 補充：已鎖定並修正生成頁的一個實際卡點。原因是 `嚴格來源追蹤` 與停用中的 `開始生成` 同時放在 `st.form` 內，導致切換到 preview 模式時 UI 不會即時 rerun，看起來像整個生成流程被鎖死。現在已改成一般容器 + 普通按鈕，切換後會立刻反映 warning / button 狀態。**

**2026-04-13 補充：已完成 Streamlit Web 工作台第一輪整併與實機驗證。生成頁現在會顯示 source readiness，非 Marker 文檔在嚴格模式下會被阻止正式生成；題庫篩選可直接切到練習頁，練習頁已實測可作答/提交/計分，右側 AI 助手快捷提問也已跑通。**

**✅ 已完成 past exam normalize/classify/blueprint 垂直切片；下一步聚焦實際 PDF 套跑與上層接線。**

**2026-04-13 補充：已實跑 exam-generation 證據鏈，確認「完整附詳解題目」的正式入庫前提是 `search_source_location` 可用；若文件缺少 Marker blocks 或 KG 失敗，workflow 現在會停在 preview / blocked，而不是繼續假裝有精確來源。**

目前已確認主流程：
- asset-aware 提供 shared artifacts：`data/doc_<id>/<doc_id>_manifest.json` + `..._full.md`
- exam-generator 透過新 MCP tools 讀 `doc_id` artifacts，完成 normalize / classify / blueprint
- pipeline run 可自動落地 `ingest_past_exams -> normalize_questions -> classify_patterns -> build_blueprint -> publish_reference_pack`

目前待處理：
- 讓上層 ingest / parse / UI 真正暴露 `page_ranges` 與新的 auto strategy，避免大 PDF 仍只能走整本 ingestion
- 用真實 past exam PDF 再跑一輪，補 parser 對多欄/答案區格式的邊界案例
- 讓上層 UI / prompt 直接呼叫 `exam_run_past_exam_extraction`
- `create_exam` 仍讀取 JSON 檔，與 SQLite 主儲存路徑不一致
- 重新 ingest 需要正式 source tracking 的教材 PDF（`use_marker=True`），否則 exam-generation 只能產出 preview 草稿，不可正式入庫
- 將 Streamlit 生成頁正式接上新的 exam pipeline tools，避免聊天模型回答中仍出現舊工具名稱
- 題庫的 `validated_only / exam_track / scope request / heartbeat` 已落地；下一步改成補瀏覽器 smoke test、review workflow 細節與 template/past-exam 的 Web 接線

## 已完成

- Crush AI Agent + GitHub Copilot 認證
- MCP Server (13 個考題工具) 已連接
- SQLite 資料庫 + Repository Pattern + Audit 追蹤
- Streamlit UI (三欄佈局：側邊選單 + 操作區 + 常駐 Chat)
- Domain 實體 (Question, Exam, Source, Audit)
- **流式生成 (2026-02-05)**：stream_crush_generate() + 即時 UI 更新
- **Past Exam Extraction (2026-04-13)**：`exam_extract_past_exam_questions`、`exam_classify_past_exam_patterns`、`exam_build_past_exam_blueprint`、`exam_run_past_exam_extraction`

## Key Files

| 檔案 | 用途 |
| ---- | ---- |
| `crush.json` | Crush 配置 (模型、MCP) |
| `src/infrastructure/mcp/exam_server.py` | MCP 考題工具 (13 個) |
| `src/presentation/streamlit/app.py` | Streamlit UI |
| `src/domain/entities/question.py` | 考題實體 |
| `src/infrastructure/persistence/sqlite_question_repo.py` | SQLite Repository |
| `data/questions.db` | SQLite 資料庫 (9 題) |
| `src/application/services/past_exam_extraction_service.py` | Past exam normalize / classify / blueprint service |
| `src/infrastructure/persistence/sqlite_past_exam_repo.py` | Past exam SQLite repository |

## Streamlit URL

- Local: `http://localhost:8501`

## Current Blockers

- **生成頁仍是 prompt orchestration 為主**：雖然 preview / formal 切換 UX 已修正，但正式出題仍未完全收斂成穩定的服務層調用
- **新 page-range / large-PDF 能力尚未上浮到使用者入口**：底層 asset-aware 已支援，但上層 ingest / Web / agent 尚未全面暴露這些控制項
- **真實考古題格式仍未完全驗證**：目前規則已用 synthetic fixture 驗證，尚需真實 PDF 套跑
- **上層 workflow 尚未全面切換**：部分 prompt / UI 仍停留在舊流程
- **新治理切片雖已落地，但仍缺完整 smoke test**：目前已用 repository round-trip + heartbeat job emission 驗證，尚未做完整瀏覽器互動驗證
- **現有 randomized trial 文獻缺少 Marker blocks**：`search_source_location` 會失敗，無法提供 page/line/bbox 級來源
- **知識圖譜環境未就緒**：`consult_knowledge_graph` 目前打到本機 LLM endpoint 404，需修環境或依 fallback 流程處理
- **Web 生成頁仍屬 prompt 編排式整合**：UI gating 已正確，但正式生成仍需要把 pipeline tool 調用做成更穩定的服務層接線

## Next Steps

1. **把 `page_ranges` 與 large-PDF 策略接到上層**：讓 ingest / parse UI 與 agent 能真正只處理指定頁段
2. **用真實 past exam PDF 驗證**：直接跑 `exam_run_past_exam_extraction` 檢查抽題品質
3. **重 ingest 正式教材**：用 `use_marker=True` 重新建立可精確追來源的 doc_id
4. **補 browser smoke test**：驗證 `📋 出題需求`、題庫審查按鈕與統計頁 heartbeat 卡片的互動流程
5. **補 UI / Agent 接線**：讓生成頁正式消費 pipeline tools，並保留目前已驗證的 source-ready gate / preview mode UX
6. **把 template / past-exam 能力帶進 Web**：讓 backlog 補題不只靠 topic gap，也能用歷屆模式輔助
