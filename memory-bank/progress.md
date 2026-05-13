# Progress (Updated: 2026-05-13)

## Done

- 完成 asset-aware PyMuPDF figure extraction 修復：xobject 圖像現在會輸出 page-region display crop，保留 PDF text layer、label、vector overlay 與鄰近 caption，不再只存 raw embedded image
- `FigureAsset` 已新增 `raw_path / figure_bbox / crop_bbox / caption_bbox / caption_confidence / extraction_strategy`，供 UX、考題圖像引用與後續 audit 使用
- caption extraction 已支援 `Fig. 42.1` 這類 decimal figure number，並能回填 caption bbox；caption association 改成 spatial matching，而不是同頁 FIFO
- 多 panel figure 已新增 `caption_group_page_crop`：同一 caption 下的多個 xobject panel 會合併成一張 display crop，降低碎圖與錯配
- 新增並通過 focused regression tests：`uv --directory libs/asset-aware-mcp run pytest -q tests/unit/test_pdf_extractor.py tests/unit/test_document_service.py tests/unit/test_entities.py`，結果 `50 passed`
- 已用 MCP targeted reingest 重建 Miller Chapter 33/42，最終 figure audit 報告在 `data/reports/figure_crop_audit/20260513T0918/summary.json`，contact sheets 在同目錄
- Targeted audit 結果：Chapter 33 為 `44 figures / 33 captions / 44 crop_bbox / 33 caption_bbox / xobject_raw=0`；Chapter 42 為 `38 figures / 28 captions / 38 crop_bbox / 28 caption_bbox / xobject_raw=0`
- 驗證 MCP `search_source_location` 對 Chapter 42 仍正常，`inspect_document_manifest` 可列出新 figure metadata；OpenClaw embedded agent smoke 回 `OK` 且 `fallbackUsed=false`；Web service 重啟後 `http://127.0.0.1:8501` 回 `HTTP/1.1 200 OK`
- 已將 `libs/asset-aware-mcp` 升級到上游 latest `v0.6.29`；升級前 dirty files 已備份到 `.codex/backups/asset-aware-mcp-v0.6.8-dirty-20260512T155356Z/`，並在 subrepo 留有 `pre-v0.6.29 asset-aware local backup 20260512T155356Z` stash
- 已在 `v0.6.29` 重新套用 LightRAG lazy import：`ENABLE_LIGHTRAG=false` 時不 import `LightRAGAdapter`，讓 OpenClaw/web 不被 optional KG dependency 影響
- 已用 asset-aware MCP stdio 對 `98` 份 PDF 重新 ingest；結果為 `97 completed / 1 timeout / 0 failed / 0 exception`，報告落在 `data/reports/asset_aware_reingest/mcp_reingest_20260512T160030Z.json`
- MCP reingest 主要成果：`87/87` Miller 分章完成、`8` 份歷屆考題完成、`2` 份 uploads 完成；`98/98` 有 manifest/markdown/blocks，`97/98` 有 segmentation，總計 `6727` pages、`1434` figures、`496` tables
- 已驗證 latest asset-aware MCP lookup：`search_source_location` 對 Chapter 21 `doc_21___intravenous_anesthetics_ff4fff` 可回傳 `propofol=43`、`ketamine=25`、`etomidate=19` matches
- 已驗證 OpenClaw 仍可載入 MCP：agent smoke 回覆 `OK`，`asset-aware` 工具數更新為 `62`，`exam-generator` 為 `26`
- 已重新安裝並啟動 user-level `anesthesia-exam-web.service`，Streamlit 服務 active/running，`http://127.0.0.1:8501` 回 `HTTP/1.1 200 OK`
- 已將 repo-local OpenClaw runtime 更新到 `OpenClaw 2026.5.7 (eeef486)`，並重新套用 repo agent 設定；config validate 通過，模型仍指向 `gb10/Qwen3.5-122B-A10B-Q5_K_M-00001-of-00003.gguf`
- 修正 `asset-aware` MCP 的 LightRAG optional dependency 邊界：`ENABLE_LIGHTRAG=false` 時不再 eager import `LightRAGAdapter`，避免新版 `lightrag` 缺少舊 `EmbeddingFunc` 匯出時拖垮 OpenClaw bundled MCP
- 完整 OpenClaw agent smoke 已通過：回覆 `OK`、`fallbackUsed=False`，system prompt 中載入 `asset-aware` 48 個工具與 `exam-generator` 26 個工具
- 已重啟 user-level `anesthesia-exam-web.service`，服務為 active/running，`http://127.0.0.1:8501` 回 `HTTP/1.1 200 OK`
- 已更新 systemd/OpenClaw 文件與 unit env，讓 Web 服務預設使用 repo-local OpenClaw agent mode 與 MCP config
- 已確認 `vendor/openclaw-runtime` npm production audit 仍有 `1 high / 5 critical` advisories；未執行 `npm audit fix --force`，因 npm 建議 downgrade 到可疑 `openclaw@0.0.1`，需另行處理供應鏈版本
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

- 收斂 OpenClaw + Streamlit Web + asset-aware MCP 的服務化部署邊界，優先維持 user-level systemd 可重啟、可驗證、可使用 repo-local MCP config
- 準備將 PyMuPDF page-region figure crop 修復從 Chapter 33/42 擴大到 Miller 87 章全量 artifact refresh
- 後續教材 evidence 品質仍應轉為 targeted caption/evidence recovery，而不是再全書重跑 figure refresh

## Next

- 針對完整 `2020 Miller's Anesthesia 9th.pdf` 單一巨檔建立 chunked/page-ranged ingest 策略；不要把 3336 頁 monolithic PDF 當成同步批次主路徑
- 若需要 Marker bbox 級 citation，先解決 `marker-pdf` 與 `Pillow>=12.2.0` 的安全相容性，或隔離一套 Marker runtime；不要把 v0.6.8 時代的舊 Marker/Torch stack 直接回套到 v0.6.29
- 用本次修復後的 `caption_group_page_crop` pipeline 全量刷新 Miller 87 章，並用 `xobject_raw=0`、caption coverage、contact sheet 抽樣作驗收
- 處理 `vendor/openclaw-runtime` 供應鏈 audit：追 OpenClaw 上游是否發布移除惡意/脆弱 transitive dependency 的修正版，避免用 `npm audit fix --force` 降到不可信版本
- 對真實 Streamlit 頁面加 rerun / query 耗時量測，確認是否還有比聊天與重型 panel 更大的瓶頸
- 針對 caption coverage 偏低章節做定向補強：優先看 chapter 30、42、59、66、32，確認 caption extraction、page text 與 figure matching 是否需要專章策略
- 詳解/出題 pipeline 使用教材圖像時，應以最新 asset audit 作為最低品質門檻，避免重新使用舊碎圖 manifest
- 若要繼續收斂 `exam_server.py`，下一刀優先拆 `get_generation_guide / get_topics` 或 past-exam tool adapter，不要一次動整條 pipeline harness
- 針對新的 `app.py` orchestration + `exam_server` registry 結構補更廣的 Streamlit / MCP integration smoke
- 若需要開機後不登入也常駐，改成 system-level service 或啟用 linger

## 2026-05-13 Completed

- Asset-aware figure extraction review-first 修復完成：
  - JSON/default profile 與 `ETLProfile.compile_figure_caption_re()` 支援 decimal figure captions 與 `figure_caption_require_line_start=False`。
  - PyMuPDF XObject primary output 改以 page-region crop 為主，保留圖中文字/圖說；raw image 僅在有意義且非冗餘時保存。
  - DocumentService caption matching 改為硬幾何 gate，移除不安全 FIFO caption fallback，multi-panel grouping 加入下一個 caption 邊界。
  - Marker image path 補齊 `figure_bbox/crop_bbox/caption_bbox/caption_confidence/extraction_strategy` metadata。
  - fast fallback 也加入子進程 timeout，避免單章卡死整批；refresh script 加真 PDF magic bytes 過濾、run_status、zero-figure overwrite guard。
  - Streamlit chat context 補 `source/evidence_pack/generation_mode/question_type`，年份 filter 改安全轉型；generation normalization 補 question_type / answer labels / legacy source fallback；OpenClaw provider 改嚴格 JSON 回傳檢查。
- 驗證：
  - `uv --directory libs/asset-aware-mcp run pytest -q` => 854 passed, 21 skipped。
  - `uv run pytest -q` => 92 passed。
  - MCP stdio smoke：62 tools，`search_source_location` 對 Chapter 42 `Transducer manipulation` 命中 page 3 Fig. 42.1。
  - OpenClaw smoke：embedded runner 回 `OK`。
  - Web service：`anesthesia-exam-web.service` active，`curl http://127.0.0.1:8501` 回 HTTP 200。
  - Full image audit：777 records，missing=0，unreadable=0，raw_only=0。

## 2026-05-13 Residual Risks

- Chapter 30 仍是特殊風險章：PyMuPDF fast fallback 會卡住，只能保守用既有 image files 恢復圖資；若要 caption/bbox，需要另做章節專屬 recovery 或改用 Marker/vision workflow。
- 全 87 尚未全數轉成新 strategy schema；舊 manifest `unknown` strategy 仍有 476 records，但目前 path health 與 raw_only gate 正常。

## 2026-05-13 Follow-up: Chapter 33 Fig. 33.1 Manual QA

- 人工測試指出 Chapter 33 `Principles of Ultrasound` 附近的 Fig. 33.1 只被舊 crop 截到下方 caption/小 XObject，漏掉完整 vector/text 圖。
- 已新增 `caption_anchor_page_crop` heuristic：當 caption 很寬、候選 XObject 很小時，用 caption 反推 full-width page-region crop，覆蓋大型 vector/text figure。
- 已重刷 Chapter 33；`fig_2_1` 現為完整 `1290x953` png，包含完整 Fig. 33.1 與 caption。
- 驗證：asset-aware 全測 `855 passed, 21 skipped`；MCP `inspect_document_manifest` 顯示 `fig_2_1` size `1290x953`。

## 2026-05-13 Follow-up: Chapter 33 Fig. 33.4 Multi-panel QA

- 人工測試指出 Fig. 33.4 是 A/B 組圖，舊流程會把 subvolumes 與 3D image panels 拆成碎圖，不能作為教材圖像引用。
- 已調整 `caption_group_page_crop`：遇到 caption 明確包含 `(A)` / `(B)` 等 panel marker 時放寬同 caption 垂直 gap，但仍用下一個 caption 邊界阻止跨圖吞噬。
- 已重刷 Chapter 33；`fig_8_1` 現為完整 `1042x616` png，包含 A/B 組圖與 caption，strategy 為 `caption_group_page_crop`，不再產生碎裂的 `fig_8_2`。
- 驗證：asset-aware 全測 `856 passed, 21 skipped`；Chapter 33 figure refresh 報告顯示 `figures=34`，碎片被合併而非遺失。

## 2026-05-13 Release Prep: asset-aware v0.6.30

- 已把 asset-aware dirty patch 備份到 `.codex-backups/asset-aware-v0.6.30-dirty-20260513T110521Z.patch`。
- 已將 subrepo 從 detached `v0.6.29` 移到最新 `origin/master`，建立 `release/v0.6.30` 分支後重新套回 figure crop 修補。
- 已更新 release metadata：`pyproject.toml`、`src/__init__.py`、VSIX `package.json/package-lock.json`、`CHANGELOG.md`、README/docs 版本文字。
- Release gate 注意：本機目前缺 `npm`，VSIX `sync-assets:check`、`test:ci`、`test:install-smoke` 尚不能宣稱通過；tag 前必須以實際命令結果作準。
