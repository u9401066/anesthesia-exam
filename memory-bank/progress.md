# Progress (Updated: 2026-04-23)

## Done

- 完成 Streamlit performance rescue：右側常駐聊天改成 background thread + fragment 同步的非阻塞串流，聊天期間 UI 可先響應，不再被同步 agent 回應整頁卡住
- 完成 Streamlit cache invalidation 收斂：教材清單、草稿箱、一般題庫、歷屆題庫、scope request 的 cached read-model 都在 mutation path 後明確清 cache，修掉 rerun 後短時間顯示舊資料的 UX bug
- 完成題庫/練習頁重型面板減載：多處由 `st.tabs` 改為單一 active-section 渲染，並讓待審面板採 opt-in 展開，降低左側切頁與對話期間 rerun 的固定成本
- 修正 `OpenClaw infer` availability 判斷：`infer` 模式不再無條件要求 repo-local config，只有 `agent` 模式才檢查 `openclaw_config_path`
- 修正 root `uv run pytest`：正式補上 fresh env 缺失的測試依賴、限制 root collection 只跑本 repo `tests/`，並新增 mixed root/vendored test collection 的隔離與防回歸測試
- 驗證完成：`uv run pytest -q` 為 `86 passed`；顯式 mixed command `uv run pytest -q libs/asset-aware-mcp/tests/unit/test_document_service.py tests/test_agent_provider_config.py` 為 `24 passed`

- 已完成 Miller 9th 分章教材 figure asset 全量受控刷新：87/87 章節重跑 `scripts/refresh_miller_figures.py`，並以 `scripts/audit_miller_image_quality.py` 做前後品質驗證
- 修正 asset-aware PyMuPDF figure caption extraction 可能卡死單章的問題：新增 document-level caption timeout，超時時只跳過該文件 captions，不讓整批 ingest/refresh 停住
- Miller figure audit 指標大幅收斂：figure 總數 `4159 -> 867`、極小碎圖 `<20k area` 為 `2267 -> 51`、低變異圖 `1759 -> 14`、最大單頁 figure 數 `268 -> 4`，且 path missing / unreadable / 舊 `/root` prefix 全部歸零
- 新增高品質 Miller ETL profile 與 OpenCode/Crush asset-aware MCP env 設定，讓後續 textbook figure extraction 預設走 `configs/asset-aware/miller_marker_hq.json`
- 新增可重跑的 Miller 圖像品質稽核報告：`data/reports/image_audit/summary_20260422T201458Z.json` 與 before/after comparison `refresh_comparison_20260422T201458Z.json`
- 已完成 `109/2020` 答案鍵正式修復：追查後確認 `109年筆試考題答案.pdf` 並非全卷送分，而是 PDF 隱藏文字層錯誤導致先前匯入誤寫成 `BONUS`；現在已用逐題校對的官方答案表修正 `data/questions.db` 中該年份 `100` 題 `correct_answer`
- 新增 `scripts/repair_109_written_answers.py`，可先備份正式 DB，再只更新 `109/2020` 這 `100` 題答案鍵並輸出 before/after 驗證報告
- 新增 `scripts/batch_fill_past_exam_explanations.py`，可先備份正式 DB，再以 repo 既有詳解 + `data/2020 Miller's Anesthesia 9th.pdf` 文字快取做 grounding，批次補寫指定年度考古題詳解
- 已正式寫入 `2025` 年首批 `10` 題考古題詳解到 `data/questions.db`；庫內驗證結果為 `generated_count=10`、`error_count=0`，`2025` 年剩餘缺詳解題數降為 `90`
- 新增 `src/application/services/past_exam_explanation_service.py`，可用 repo 既有一般題庫/歷屆題庫詳解當參考，生成考古題詳解並寫回 `past_exam_questions.explanation`
- Streamlit `📚 題庫管理 -> 歷屆題庫` 已補上互動式詳解工作流：可搜尋缺詳解題、查看相似參考題、單題生成並存檔、或小批次補寫本卷缺詳解
- `opencode.json` 與 provider config parser 已支援 custom OpenAI-compatible provider；repo 預設模型改為 `gb10/Qwen3.5-122B-A10B-Q5_K_M-00001-of-00003.gguf`，systemd sample 也同步指向 `http://192.168.1.145:8081/v1`
- 啟動面向下相容：`app.py` / `generation/fragments.py` 不再直接依賴 `question_formal_save_ready` symbol import，而是改走 `get_textbook_generation_service()` singleton，避免 refactor 後 symbol-level import 脆弱度
- focused 驗證新增 `test_agent_provider_config + test_past_exam_explanation_service`，目前相關 suite 為 `21 passed`
- `exam_server.py` 已完成第一刀瘦身：題庫型 MCP tools 先抽到 `src/application/services/exam_tool_application_service.py`，`call_tool` 改走 `src/infrastructure/mcp/exam_tool_handlers.py` registry；保留 `exam_server.save_question()` 等 module-level wrappers 與 pipeline/past-exam legacy handlers，focused 驗證 `10 passed`（`test_exam_tool_handlers + test_textbook_formal_save_gate + test_exam_pipeline_harness`）
- 生成頁的 textbook review/save slice 已從 `src/presentation/streamlit/app.py` 抽成 DDD 友善邊界：新增 `QuestionReviewService`（application layer）承接 formal save，用 `src/presentation/streamlit/generation/controller.py` + `fragments.py` 承接 Streamlit controller/render
- formal-save gate helper 已收斂到 `src/application/services/textbook_generation_service.py`，移除 `app.py` / fragments 的重複 wrapper
- 較完整驗證通過：`test_streamlit_practice_browser + test_textbook_generation_service + test_textbook_formal_save_gate + test_draft_workflow_guards` 共 `22 passed`

- 將 Streamlit Agent 控制台改成伺服器端固定 provider/model 顯示
- 新增作答練習題組的 markdown 下載，不寫入資料庫
- 修正教材 manifest 舊絕對路徑在 UI 讀取時的 normalization
- 將 8501 站台安裝為 user-level systemd 服務並確認 HTTP 200
- 建立共用 logging bootstrap，統一 Web / MCP / CLI / Python scripts 的初始化方式
- 加入 env-driven log level、debug switch、rotation 與 contextvars run_id 綁定
- 為 database、repositories、past-exam service、query service、historical importer 補上結構化 logging
- 生成流程改用 `st.status` 聚合長流程狀態，草稿提示成功/資訊訊息優先改走 `st.toast`
- 驗證通過：focused pytest 22 passed、importer dry-run 正常、repository write smoke 正常、touched files compile/diagnostics 全綠
- SQLite connection layer 升級為 SQLAlchemy QueuePool，統一套用 WAL、busy timeout、foreign keys 與 writer hardening
- question / past exam / scope request / draft repositories 的主要寫入路徑補上 `BEGIN IMMEDIATE`
- `HeartbeatService` 與 `TextbookGenerationService` 補齊 structured logging
- 驗證通過：SQLite hardening/browser/textbook focused suite 21 passed、heartbeat status 正常、importer dry-run 正常

## Doing

- 進入 commit/push 收尾；本次主 repo 先提交 Streamlit performance rescue、OpenClaw availability fix、pytest isolation 與對應測試/文件，排除正式 DB 與個人環境檔
- 後續教材 evidence 品質應轉為 targeted caption/evidence recovery，而不是再全書重跑 figure refresh

## Next

- 對真實 Streamlit 頁面加 rerun / query 耗時量測，確認是否還有比聊天與重型 panel 更大的瓶頸
- 針對 caption coverage 偏低章節做定向補強：優先看 chapter 30、42、59、66、32，確認 caption extraction、page text 與 figure matching 是否需要專章策略
- 詳解/出題 pipeline 使用教材圖像時，應以最新 asset audit 作為最低品質門檻，避免重新使用舊碎圖 manifest
- 若要繼續收斂 `exam_server.py`，下一刀優先拆 `get_generation_guide / get_topics` 或 past-exam tool adapter，不要一次動整條 pipeline harness
- 針對新的 `app.py` orchestration + `exam_server` registry 結構補更廣的 Streamlit / MCP integration smoke
- 若需要開機後不登入也常駐，改成 system-level service 或啟用 linger
