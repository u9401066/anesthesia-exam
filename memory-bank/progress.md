# Progress (Updated: 2026-04-14)

## Done

- `libs/asset-aware-mcp` 已完成並發布大 PDF ingestion 強化：Marker 解析現在會在頁數超過 800 頁時自動啟用 chunking，遇到高圖片量 PDF 時自動關閉 figure extraction，避免大型文件解析時記憶體與輸出量失控
- `libs/asset-aware-mcp` 已完成真正的 page-range ingestion：支援只 materialize 指定頁段的 `selected_pages.pdf`，並把 markdown / toc / table / image / marker 輸出頁碼 remap 回原始 PDF 頁碼，同時用 page-range scope 避免 `doc_id` collision
- 上述 asset-aware 變更已提交並推送到子模組 repo `u9401066/asset-aware-mcp`（commit `7b1c6d5`），主 repo 也已更新 submodule pointer（commit `841298d`）

- 完成題庫治理切片第一階段：`Question` 新增 `exam_track`、`is_validated`、`validation_notes`，`IQuestionRepository.list_all()` 與 SQLite repo 已支援 `validated_only` / `exam_track` 篩選
- `database.py` 補上 migration runner，`questions` 表新增 `exam_track` migration，並新增 `scope_requests` table 與索引初始化
- 新增 `ScopeRequest` 實體、repository 介面與 `SQLiteScopeRequestRepository`
- 新增 `HeartbeatService` 與 `scripts/run_heartbeat.py`，heartbeat 會把補題工作寫成 `data/jobs/*.json`，供外部 agent / OpenClaw 讀取
- Streamlit 已加入 `📋 出題需求` 頁：可提交 backlog、管理者可核准/駁回、可從 UI 直接 dry-run / 寫出 heartbeat jobs
- 題庫管理頁已加入 reviewed-only / exam-track 篩選與審查按鈕；統計頁已加入 heartbeat / backlog 摘要
- 修正 `Question.source` 的 round-trip 保真：改成完整 `Source.to_dict()` / `Source.from_dict()`，避免精確來源欄位在 UI / SQLite hydration 過程遺失
- 驗證完成：`app.py` 無 diagnostics、py_compile 通過；repository round-trip 測試通過；heartbeat 對暫存目錄成功寫出 job 檔

- 依使用者提出的 6 項 Web 需求完成盤點：#1 已達基本需求，#2/#4/#6 部分達成，#5 後台雛形已具備，#3 尚未實作
- 更新 `SPEC.md`：補上 Web 需求驗收矩陣、題庫治理 metadata、現況實作狀態與正式缺口
- 更新 `ROADMAP.md`：把已驗證的 Web MVP 能力與 reviewed-only / exam taxonomy / scope request / heartbeat 等待辦拆開

- 確認並初始化 `libs/asset-aware-mcp` 子模組（checkout: 2a4ba4c）
- README 新增 submodule 初始化說明，避免 ETL 因空目錄失效
- `libs/asset-aware-mcp` 已更新到 upstream `master` 最新 commit `2252829`
- 補上 past exam 垂直切片：`doc_id -> normalize -> classify -> blueprint`
- 新增 past exam repository / service / MCP tools，真正把 asset-aware artifacts 接進 exam-generator
- 新增 regression tests，覆蓋 rerun idempotency 與 pipeline phase completion
- 實跑 exam-generation 證據鏈，確認目前 KG endpoint 404、非-marker 文檔無法 `search_source_location`
- 收斂完整出題規則：沒有 `source_ready=true` 不得進入 `draft_questions` 正式入庫流程
- 更新 `generate-mcq` / `add-explanation` prompts，加入 marker readiness probe、KG fallback、preview-only stop condition
- 新增 pipeline harness regression test，驗證 `source_ready=false` 時 gate 會正確阻擋
- Streamlit Web UI 第一輪重構完成：加入全域設計系統、頁面 hero、空狀態與更清楚的資訊層級
- 生成頁加入 ETL Marker 切換、教材 source readiness 摘要、嚴格正式模式 / preview 草稿模式分流
- 修正 Streamlit 導航 state：題庫篩選結果可直接切到練習頁，避免 `page_nav` widget state mutation 例外
- 題庫管理加入關鍵字 / 難度 / 主題篩選，並已實測可用目前篩選結果開始練習
- 作答練習頁已加入回合摘要卡，並實測完成選答、提交、計分流程（3/3 smoke test）
- AI 助手空狀態與快捷提問已實測可送出請求並取得回應
- 安裝 webapp optional dependencies，修復本地缺少 Streamlit 導致 UI 無法啟動的環境問題
- 修正生成頁卡住的互動缺陷：移除 `st.form` 對來源模式切換的阻塞，現在 `嚴格來源追蹤 -> preview 草稿` 的切換會即時更新 warning 與「開始生成」按鈕狀態

## Doing

- 準備把新的 asset-aware `page_ranges` / auto chunking 能力往上接到正式教材 ingest 與 Web / agent 工作流
- 準備將生成頁從 prompt 編排式整合進一步收斂到服務層 / pipeline tool 接線
- 準備重 ingest 真實教材，讓正式出題可取得精確來源
- 持續補做 web smoke test，優先確認新增的需求頁 / 題庫審查 / heartbeat 統計與既有生成、練習、聊天頁面
- 規劃下一輪 taxonomy / template / past-exam Web 接線，避免補題只停留在 topic-level gap

## Next

- 讓上層 ingest / parse 流程實際使用 `page_ranges`，驗證只 ingest 指定頁段時仍能維持精確來源顯示
- 讓 Streamlit / Agent 直接消費新的 `exam_run_past_exam_extraction` 工具
- 用 `use_marker=True` 重新 ingest 正式教材 PDF，打通 `search_source_location -> exam_save_question`
- 補瀏覽器級 smoke test，確認 `📋 出題需求` 的提交 / 核准 / heartbeat job 產生流程
- 設計 heartbeat 完成回寫與外部 agent 消費後的反饋流程，讓 job `done/error` 更容易從 UI 操作
- 視實際 past exam PDF 格式再擴充 parser 規則（多欄、答案表、圖片題）
- 把聊天與生成流程中的舊工具名稱清乾淨，統一成目前 MCP tool 實際可用名稱
