# Active Context

## Current Goals

- 讓 repo 的「考古題互動學習」主線先真正可用：優先補齊有完整答案鍵年份的詳解、維持 Streamlit 題庫管理頁可單題/批次生成詳解、並保留對 `192.168.1.145:8081/v1` 的 direct OpenAI-compatible fallback。

## Current Focus

**2026-04-23 補充：Miller 9th 分章教材的 figure asset 已完成全量刷新與品質稽核。這次不是再盲目全書 strict Marker 重跑，而是在 asset-aware pipeline 補上可控的 high-fidelity profile、figure filtering、Marker bbox crop fallback 與 PyMuPDF caption timeout guard 後，對 `Miller anesthesia章節分割版` 87/87 章節執行 figure-only refresh。刷新後 latest audit 顯示：figure 總數 `4159 -> 867`，極小碎圖 `<20k area` 從 `2267` 降到 `51`，低變異圖從 `1759` 降到 `14`，最大單頁 figure 數從 `268` 降到 `4`，且 manifest path 的 missing / unreadable / 舊 `/root` prefix 已歸零。這代表先前「圖像多數錯誤」的主要 root cause 已從大量 XObject/region false positives 收斂為少數章節的 caption/evidence matching 問題；下一步應做 targeted caption recovery，而不是再次全書重刷。**

**2026-04-22 補充：`109/2020` 年歷屆題答案鍵異常已完成 root-cause investigation 與正式修復。問題不是官方全卷送分，而是 `109年筆試考題答案.pdf` 的隱藏文字層/OCR 結果錯誤，先前匯入腳本因此把整份答案檔誤判成 `本題送分`，再硬寫成 `BONUS`。目前已把校對後的 `1-100` 題官方答案表固化進 `scripts/import_written_past_exams.py`，並透過 `scripts/repair_109_written_answers.py` 先備份再更新正式 DB；修復結果為 `updated_count=100`、`bonus_rows_remaining=0`，抽查 `Q1=B / Q40=A / Q71=D / Q100=C` 均符合原始答案頁。這代表 `2020` 年 written 題庫現在已重新具備網站互動判分資格。**

**2026-04-21 補充：已用正式流程把 `2025` 年歷屆題首批 `10` 題詳解寫入 `data/questions.db`。這批是透過新加的 `scripts/batch_fill_past_exam_explanations.py` 執行，流程會先備份正式 DB，再用 repo 內相似詳解題與 `data/2020 Miller's Anesthesia 9th.pdf` 萃出的文字片段一起組 prompt，最後直接呼叫 `http://192.168.1.145:8081/v1` 的 OpenAI-compatible endpoint。驗證結果為 `generated_count=10`、`error_count=0`，`2025` 年剩餘缺詳解題數目前是 `90`。這代表網站端已經有第一批「可判分 + 有詳解」的真實歷屆題可供練習。**

**2026-04-21 補充：已打通「考古題缺詳解補寫」這條使用者主線。新增 `PastExamExplanationService` 後，系統可先從 repo 內已有詳解的一般題庫/歷屆題庫找相似題，組成 reference context，再用 provider 或直接走 `opencode.json` 指向的 OpenAI-compatible endpoint 生成繁中詳解，最後寫回 `past_exam_questions.explanation`。Streamlit `📚 題庫管理 -> 歷屆題庫` 也同步補上單題生成/存檔、批次補寫本卷缺詳解、以及參考題脈絡檢視。這很重要，因為目前真實 DB 有 900 題歷屆題，其中 800 題缺 explanation；現在網站端終於有內建補齊路徑，而不必先等完整 MCP/pipeline 大改完。**

**2026-04-21 補充：`OpenCode` 設定面也做了一刀實用收斂。repo 的 `opencode.json` 已改成把預設模型指向 `gb10/Qwen3.5-122B-A10B-Q5_K_M-00001-of-00003.gguf`，base URL 為 `http://192.168.1.145:8081/v1`；`src/infrastructure/agent/provider.py` 與 Streamlit metadata loader 也不再假設 `provider.models` 一定是單一 dict 形狀，現在可正確列出 custom provider/model refs，且在 top-level `model` 缺席時會回退到第一個已配置模型。額外確認到目前這台機器其實沒有 `opencode` binary，因此「考古題詳解補寫」刻意支援 direct OpenAI-compatible fallback，避免功能被 CLI 安裝狀態卡死。**

**2026-04-21 補充：已完成 `exam_server.py` 第一刀瘦身。題庫型 MCP tools（save/list/create/stats/get/delete/validate/update/audit/search/restore/bulk）已下沉到 `src/application/services/exam_tool_application_service.py`，transport 名稱分派改由 `src/infrastructure/mcp/exam_tool_handlers.py` registry 統一處理；pipeline harness 與 past-exam flow 先留在 `exam_server.py` 作 legacy handlers，同時保留 `exam_server.save_question()` 等 module-level wrappers 以維持現有測試與 monkeypatch path。focused 驗證已通過：`tests/test_exam_tool_handlers.py + test_textbook_formal_save_gate.py + test_exam_pipeline_harness.py` 共 `10 passed`。下一刀適合繼續把 `get_generation_guide / get_topics` 或 past-exam handlers 往 application/service 層收，不要一口氣動整條 pipeline harness。**

**2026-04-21 補充：`app.py` 的生成頁已開始做 DDD-friendly presentation 切片。這一輪沒有去碰整條 prompt orchestration，而是先把「生成後審閱/正式入庫」這塊從單檔抽開：新增 `src/application/services/question_review_service.py` 承接 review payload -> domain entity -> formal bank persistence，用於避免 Streamlit 直接持有正式入庫 mapping；同時新增 `src/presentation/streamlit/generation/controller.py` 與 `.../fragments.py`，把 review form 的 render 與按鈕行為移出 `app.py`。後續又把 `formal-save` gate helper 收斂成 `src/application/services/textbook_generation_service.py` 的單一 facade，避免 `app.py` 與 fragments 規則漂移。驗證已通過：`test_streamlit_practice_browser + test_textbook_generation_service + test_textbook_formal_save_gate + test_draft_workflow_guards` 共 `22 passed`，editor diagnostics 也全綠。**

**2026-04-21 補充：SQLite 資料層已從「每次裸 `sqlite3.connect()`」升級到 per-process 的 SQLAlchemy `QueuePool`，並在 connection factory 統一套用 WAL、`busy_timeout=15000ms`、`foreign_keys=ON`、`synchronous=NORMAL`、`wal_autocheckpoint` 等 hardening。主要 writer repo（question / past exam / scope request / draft）也同步補上 `BEGIN IMMEDIATE`，讓多使用者 Web、heartbeat、MCP agent、importer 同時碰 DB 時至少先有一致的 writer 競爭行為。這輪另外把 `HeartbeatService` 與 `TextbookGenerationService` 接上 structured logging；focused 驗證已通過：SQLite hardening + draft workflow + textbook service + browser smoke 共 `21 passed`，`import_written_past_exams.py --dry-run --only 112` 與 `run_heartbeat.py --status` 也正常。這一輪刻意沒有再拆 `app.py` 的 fragment/dialog，因為生成頁 rerun/state 耦合仍高，適合下一刀獨立 UI 切片處理。**

**2026-04-21 補充：已把 logging 初始化正式抽成共用 bootstrap，`main.py`、Streamlit Web、MCP server 與現有 Python scripts 都改走同一套 `bootstrap_logging()`。新 logging 層支援 env-driven level / JSON console / rotation / debug switch，並加入 contextvars-based `run_id` 綁定；資料層與 workflow 補點後，`database / sqlite_question_repo / sqlite_past_exam_repo / PastExamExtractionService / QuestionBankQueryService / historical importer` 會穩定帶出 `run_id`，且在適用路徑上補 `doc_id / question_id / provider`。同一輪也做了一個低風險 UX 收斂：生成流程改用 `st.status` 聚合長流程狀態，草稿箱成功/資訊訊息改優先走 `st.toast`，避免頁面被瞬時提示訊息洗版。驗證結果：focused pytest `22 passed`、importer dry-run 正常、repository write smoke 正常、所有 touched files `py_compile` 與 editor diagnostics 皆通過。**

**2026-04-21 補充：已修正一個真實的 Streamlit 視覺回歸。問題不是單純 sidebar 漏設字色，而是當瀏覽器/系統進入 dark color scheme 時，Streamlit 內層 widget 仍沿用暗色主題，但頁面外層背景已被自訂 CSS 改成淺色，於是出現 sidebar 白字、暗色輸入框與低對比按鈕。現在 `inject_app_styles()` 會強制 light color scheme，並明確覆寫 sidebar、markdown、form labels、select/input 與按鈕樣式；用 Playwright dark-mode 模擬已驗證 sidebar 字色回到深色，表單與按鈕也恢復可讀，另有 browser smoke `test_library_to_practice_syncs_url_and_navigation` 通過。**

**2026-04-21 補充：作答練習頁還有一個更局部的配色漏網。`📋 練習設定` expander header 與 `stNumberInput` 的 `- / +` stepper 在先前修完 dark color scheme 後，仍殘留 Streamlit 的暗色背景，因為這兩個元件沒有被前一輪按鈕/輸入框 selector 覆蓋到。現在已額外覆寫 expander summary 與 number-input stepper 樣式，Playwright 實測已從暗底切回淺底深字，且 `test_practice_submit_disables_answers_and_shows_score` 通過。**

**2026-04-21 補充：browser smoke 環境阻塞已解除。補完 Ubuntu/Chromium 常見 Linux shared libraries 後，`tests/test_streamlit_practice_browser.py` 不再 skip，而是 8 條全部實跑通過；完整 `tests/` 目前為 `39 passed`。這代表先前的 browser smoke 問題確實是系統依賴缺失，不是 repo 內 test-mode gate 或 Playwright 腳本本身故障。**

**2026-04-21 補充：`past exam pipeline` 下一個真邊界已確認是「新頁題號重置」，不是跨頁題幹續接。新加的 cross-page fixture 已證實現有 extractor 本來就能保留跨頁題幹；真正出錯的是當題本在新頁從 `1.` 重新開始時，`extract_questions()` 原本只接受遞增題號，導致 reset 題被併進前題。現在 extractor 已針對「新頁 + reset 到 1 + 前題已成形 + answer map 可佐證」這個窄條件切出新題；同時 `SQLitePastExamRepository.list_questions()` 也改為依 `source_page + created_at + question_number` 讀回，避免 persistence 層把卷序重洗成數字排序。對應回歸測試已鎖住，past-exam focused suite 與 pipeline harness 為 `17 passed`。**

**2026-04-21 補充：`past exam pipeline` 又收掉一個更貼近真實資料的邊界。`PastExamExtractionService` 原本的答案 regex 只支援單一字母，因此 `40=BE`、`53=AD` 這類多重正確答案鍵會被解析成空字串；現在 `INLINE_ANSWER_RE` 與 `ANSWER_PAIR_RE` 已同步放寬，支援等號、multi-letter answer 與 `BONUS`，並新增 regression test 鎖住這個行為。這個修正很重要，因為 repo 其他 written import 路徑本來就已保留 `111` 年的 `40=BE` / `53=AD`，現在主 extraction service 與那條資料面終於對齊。當前非 E2E 測試面已提升到 `29 passed`。**

**2026-04-21 補充：已沿著 `past exam pipeline` 再往下一層收斂。除了先前修掉的 `1 -> 3` 跳號邊界外，現在也補上「答案區不完整時的跳號切題」回歸測試；root cause 是 `extract_questions()` 原本把跳號切題過度綁在 `matched_number in answer_map`，所以當答案區漏掉第 5 題答案時，`5.` 會被併進第 1 題。現在的規則是：若目前 block 已經長成可解析的完整題目，就算答案區不完整，也要把更大的題號視為新題邊界。新增測試已鎖住 `1 -> 5` 且答案區只含第 1 題答案的情境。browser smoke 診斷也更完整：本機已成功下載 Playwright Chromium，但啟動時仍因缺 `libatk-1.0.so.0` 而 skip；這代表 repo 內測試邏輯本身尚未開始執行到 UI 互動，下一步若要真正跑 smoke，必須先補齊 Linux 系統函式庫。當前非 E2E 測試面已提升到 `28 passed`。**

**2026-04-21 補充：已沿著 `past exam pipeline` 主線收斂下一個真邊界。`PastExamExtractionService.extract_questions()` 原本只接受嚴格連號切分，因此遇到 `1 ... 3 ...` 這種跳號題本時，第三題會被併進第一題；目前已改成在答案鍵可佐證時接受跳號邊界，並新增 regression test 鎖住。教材 source-tracking 也再補了一個更貼近真實的多文件/多 section hint 測試：不用 monkeypatch 打分邏輯，也能驗證完整 `source_ready` 文件會壓過較高分但不完整的 competing doc。browser smoke 部分則已確認本機 skip 根因不是 test-mode，而是環境依賴分兩層：先缺 Playwright Chromium binary，安裝後又缺 Linux shared library `libatk-1.0.so.0`；`playwright install-deps chromium` 可往前走，但在這台機器需要 sudo 才能完成。當前驗證結果已提升到非 E2E 測試面 `27 passed`。**

**2026-04-21 補充：已把 `tests/compare_section_extraction.py`、`tests/test_chapter_extraction.py`、`tests/test_ch79_ingest.py` 三支手動 PDF 腳本正式移出 `tests/`，集中到 `scripts/pdf_experiments/`，並改成 repo-relative 路徑與 CLI 用法，避免再被 pytest 收集為回歸測試。這一輪同時修掉一個更接近主線的教材 source-tracking bug：`TextbookGenerationService._build_evidence_pack()` 在多 `doc_id` 情境下，原本可能選到 `source_ready=false` 但分數較高的 pack，蓋掉另一個可正式入庫的完整 pack；現在已改成先比 `source_ready`，同狀態下才比 score，並新增 regression test 鎖住這個行為。當前驗證結果：`pytest --collect-only tests -q` 為 32 collected，非 E2E 測試面為 `25 passed`，`scripts/pdf_experiments/*.py` 也已通過 `py_compile`。**

**2026-04-20 補充：已收斂一個真實的測試面污染問題。`tests/test_ch79_ingest.py` 與 `tests/test_chapter_extraction.py` 都是舊的 Windows-only PDF 實驗腳本，不應再視為正式回歸測試；目前已改為 module-level skip，避免 `pytest` 在 broad collect / full non-E2E run 時因 `fitz` 缺失、硬編碼 Windows 路徑或不存在模組而失敗。同一輪也把 `src/domain/entities/message.py` 的 Pydantic class-based config 換成 `ConfigDict`，所以目前非 E2E 測試面為 `24 passed, 2 skipped`，且不再有 deprecation warning。**

**2026-04-17 補充：教材 review 後直接切到 practice 的 UI 路徑也已被 browser smoke 鎖住。`tests/test_streamlit_practice_browser.py` 新增 `review -> ✍️ 立即練習 -> 作答練習頁` 驗證，確認 seeded textbook review state 能直接開一回合練習，不只停留在 save gate 驗證。**

**2026-04-17 補充：textbook workflow 的 UI 驗證也已補齊。`tests/test_streamlit_practice_browser.py` 現在直接覆蓋 `preview-only` 與 `formal-save-ready` 兩條教材審閱/save gate 路徑；實作上沒有去跑真實 LLM generation，而是在 `ANESTHESIA_EXAM_E2E_TEST_MODE=1` 下用最小 deterministic seed hook 直接寫入 `st.session_state.generated_questions`。這一輪同時確認了一個 repo-local testing pattern：Streamlit browser smoke 不應硬等 `st.success` flash，而應以 SQLite 實際持久化結果作為成功條件。**

**2026-04-17 補充：textbook preview generator、formal evidence pack 與 formal-save gate 已完成第一版落地。主系統新增 `TextbookGenerationService`，可從 section/chapter/full-text 建立 prompt context、把生成結果標成 `preview_only`，並在 source probe 成功時自動組出 `stem_source / answer_source / explanation_sources`。Streamlit 審閱區現在會明確區分 preview-only 與 formal-save-ready；MCP `save_question` 也已改成後端硬性拒絕 preview-only 或 evidence pack 不完整的教材題目。基礎設施面則已修掉 Miller root data plane 的兩個核心阻塞：1) asset-aware 會在 Marker 只吐空 `MarkdownOutput` shell 時，自動由 markdown + PDF page text 合成可搜尋 blocks，因此 `doc_2020_miller_s_anesthesia_9th_7481c2` 現已能回傳 page/line/section 命中；2) LightRAG/Ollama 會動態挑 workspace 內實際存在的本機模型並自動推導 embedding dimension，且 `lightrag_working_dir` 已跟隨 root `data/` 平面。實測 root-plane KG smoke query 已成功回答 Miller shock therapy 問題；目前剩下的風險已從「完全不可用」縮小為「大批量 KG extraction 對部分 chunk 仍可能 timeout」，因此正式入庫的真正 hard gate 仍應以 source lookup + evidence pack 為準。**

**2026-04-17 補充：已把 Miller 小頁段直接 ingest 到主系統目前連線的 root `data/` 資料平面，確認 `doc_2020_miller_s_anesthesia_9th_7481c2` 的 `doc_id_full.md` 與 section title 可被讀到，但這不等於可正式出題。實測 `consult_knowledge_graph` 仍因 `http://localhost:11434/api/chat` 回 `404` 而失敗；更關鍵的是這份 Marker 產生的 `blocks.json` 只有兩個空的 `MarkdownOutput` shell，沒有可搜尋正文，因此 `search_source_location` 對實際句子也全部回 `No matches found`。結論是：目前教材拆解資料足以支撐 chapter/section 層級的 preview/draft generation，但不足以支撐要求精確 page/line/bbox 引用的正式入庫；`source_ready` 必須從「有 markdown/manifest」提升為「`search_source_location` probe 成功且 blocks 可搜尋」。**

**2026-04-16 補充：已對大型教材 `2020 Miller's Anesthesia 9th.pdf` 做第一輪完整可行性驗證。現場檔案實測為 `3336` 頁、`107.36 MB`。`libs/asset-aware-mcp` 既有 `.venv` 已可直接啟動，核心依賴 (`fitz/mcp/lightrag/httpx`) 匯入正常；大檔策略確認可用 `page_ranges + marker_max_pages_per_chunk + extract_figures=False`。實測上：1) 關閉 LightRAG 後，PyMuPDF 路徑可在約 `8.7s` 內成功 ingest `2967-2976` 頁，輸出 `doc_2020_miller_s_anesthesia_9th_b95b12` 並完整落地 `original.pdf + selected_pages.pdf + doc_id_full.md + doc_id_manifest.json + images/`；2) Marker 路徑可在 `page_ranges=2967-2972`、`chunk=5` 下成功 parse，約 `68s`，輸出 `doc_2020_miller_s_anesthesia_9th_7481c2` 與 `blocks.json`。目前真正卡點不在 ETL，而在知識圖譜：現場 `ENABLE_LIGHTRAG=true` 會打 `http://localhost:11434/api/embed` / `api/chat` 回 `404`，因此大檔正式 ingest 必須先停用 LightRAG 或補齊 Ollama embedding/chat endpoint。另已補一個相容性修正：`PastExamExtractionService.load_asset_document()` 現可同時讀 asset-aware 舊命名 `manifest.json/content.md` 與新命名 `doc_id_manifest/full.md`。直接驗證結果是 exam 端可讀到 Miller doc_id artifacts，但現有 `extract_questions()` 對教材章節文字不會抽出題目（question_count=0），表示它能讀教材，但不是適合拿來處理 textbook chapter 的生成入口。**

**2026-04-15 補充：作答練習頁的 `指定考古題` 已升級成完整 `考古題模式`。現在可在 `✍️ 作答練習` 直接選 `多份混抽 / 單份考卷`，並以 `起始年度 / 結束年度` 決定年份區間，再從區間內混抽多份考卷練習。提交後若本回合來源為考古題，結果區會額外顯示 `年度表現 / 考卷表現 / 題型與主題 / 錯題回顧` 四組統計。這一輪也順手收掉一個 Streamlit practice state 真實風險：每次開始新回合前必須清掉 radio widget key，否則同一批題目重開時會殘留舊答案。同步已把 browser smoke 擴成 5 條，完整檔 `pytest -q tests/test_streamlit_practice_browser.py` 現為 `5 passed`。**

**2026-04-15 補充：作答練習頁已補上題目來源切換，現在可在 `✍️ 作答練習` 直接選 `一般題庫 / 指定考古題`。實作上沿用既有 `load_past_exam_catalog()` + `load_past_exam_questions()`，讓使用者可指定某一份歷屆考卷後再套用題數、難度、主題與隨機順序。這一輪刻意沒有把 `validated_only / exam_track` 套到考古題，因為那兩個 filter 只屬於一般題庫。同步已新增 Playwright smoke 覆蓋 `practice -> 指定考古題 -> 開始練習`。**

**2026-04-15 補充：已把 Playwright browser smoke 正式接到 root CI。新增 `.github/workflows/ci.yml`，以 `uv sync --extra webapp --dev` 建環境，並在 browser job 執行 `uv run python -m playwright install --with-deps chromium`，分開跑 `tests/test_draft_workflow_guards.py` 與 `tests/test_streamlit_practice_browser.py`。同一輪也把草稿箱 partial-failure 前端路徑補成第三條可重跑 browser smoke：`drafts -> batch promote -> partial failure`。為了讓這條路徑在 Streamlit rerun 下仍可穩定驗證，`app.py` 現在新增 `draft_flash_level`、`draft_batch_selection_override` 與 `draft_batch_selection_reset_pending`，並只在 `ANESTHESIA_EXAM_E2E_TEST_MODE=1` 時顯示最小 test anchor `🧪 E2E 全選目前草稿`，避免再直接改已實例化的 multiselect widget key。**

**2026-04-15 補充：已把前一輪手動 browser smoke 正式落成可重跑自動化測試。新增 `tests/test_streamlit_practice_browser.py`，使用 Playwright 啟動臨時 Chromium、啟 Streamlit 子程序、並以暫時 SQLite DB seed 固定資料，覆蓋兩條 UI 路徑：1) `library -> practice` 需同步切換 URL / 內容 / sidebar；2) `practice submit` 後需顯示正確結果、總分、且 radio 進入 disabled。為了讓 E2E 不碰現場 `data/questions.db`，`src/infrastructure/persistence/database.py` 現已支援 `ANESTHESIA_EXAM_DB_PATH` env override，供測試或臨時 smoke server 注入隔離 DB。**

**2026-04-15 補充：draft promote 的 focused regression suite 也再補了一個批次邊界 case：當 multi-draft promote 中前一題成功、後一題在 `mark_promoted_with_connection()` 失敗時，成功題仍保留 promoted 狀態與正式題目，失敗題則維持 draft 且不得留下 orphan question。這個 case 已收進 `tests/test_draft_workflow_guards.py`，用來鎖住 per-draft transaction 邊界。**

**2026-04-15 補充：draft promote 已從前一輪的「補償式 rollback」正式收斂成真正的單一 transaction workflow。`SQLiteQuestionRepository` 與 `SQLiteQuestionDraftRepository` 現在都支援在既有 SQLite connection 內執行 save / mark_promoted，`QuestionDraftService.promote_drafts()` 會對每個 draft 開一個 shared connection + `BEGIN IMMEDIATE`，在同一 transaction 內完成 question save 與 draft promoted snapshot；任何一步失敗都直接 rollback，不再靠事後 soft delete 補償。同步已新增 happy-path regression test，現在 draft workflow focused suite 覆蓋：invalid bulk update guard、promote rollback、promote success、concurrent version numbering。**

**2026-04-15 補充：Streamlit UI 這輪 key/state 修正也已補成更完整的瀏覽器 smoke。實際驗證過三條路徑：1) `?page=drafts` reload 仍停在草稿箱；2) `題庫管理 -> 用目前篩選結果練習` 會把 URL、sidebar radio 與主內容一起切到 `?page=practice`；3) practice 頁選答案後提交，會正常 rerun 成計分模式，radio 會 disabled 並顯示結果 alert。這輪中途也抓到真實 bug：`navigate_to()` 在 widget 已實例化後直接寫 `st.session_state.page_nav` 會觸發 `StreamlitAPIException`；現已修成只改 `current_page + query params`，再由 render 前的 `sync_nav_widget_state()` 回填 sidebar radio。**

**2026-04-15 補充：已完成一輪「雙 subagent audit + 自主修正」收斂。這一輪直接修掉三類真實風險：1) Streamlit 生成審閱區與作答練習改用穩定 widget key，不再依賴 enumerate/index 當 UI identity，降低 rerun/重排後把編輯內容或答案映到錯題的風險；2) `SQLiteQuestionDraftRepository.bulk_update()` 現在會先解析 `difficulty / exam_track` enum，再進入迴圈，非法值會在寫入前直接失敗，不再留下部分成功的 batch update；3) draft save 入口加上 `BEGIN IMMEDIATE`，讓 version snapshot 分配串行化，並在 `QuestionDraftService.promote_drafts()` 加入補償式 rollback，若正式題目已存成功但 `mark_promoted()` 失敗，會自動把正式題目 soft delete 掉，避免 orphan question。同步已新增 focused regression tests 覆蓋 invalid bulk update、promote rollback 與 concurrent version numbering。**

**2026-04-15 補充：已修正 Streamlit 左側導航在點擊 / refresh 後容易卡住或跳回 `📝 生成考題` 的 UX 問題。root cause 不是單一 widget bug，而是兩層 state 同時失真：一是 sidebar `st.radio` 以動態 `index` 與 `current_page` 互相覆寫；二是瀏覽器 refresh 會建立新 session，導致 `current_page` 掉回預設值。現在 `src/presentation/streamlit/app.py` 已改成 `page_nav` widget key + callback + `navigate_to()` 單一導覽 helper，並把 active page 同步到 URL query param `?page=`。實測以 `?page=drafts` 進站與 reload 都能穩定停在 `🗃️ 草稿箱`，不再自動跳回生成頁。後續若再加任何程式化跳頁，必須一律走 `navigate_to()`，不要重新直接寫 `st.session_state.current_page = ...`。**

**2026-04-15 補充：題目作者工作流第四刀已完成。草稿箱現在不只可用歷史模板建立新草稿，也能把歷史模板套用到既有草稿；列表摘要新增 `相似題` 欄，批次選取時會顯示「送入正式題庫前摘要」，彙總 QA readiness 與 similarity warning。另已新增 `question_draft_versions` snapshot table，所有 draft create / batch update / template apply / QA update / archive / promote 都會留下版本快照，可在草稿 detail 直接查看版本歷史。這一版已用 `py_compile`、editor diagnostics、SQLite smoke（existing draft -> template apply -> QA update -> history）與 live 8501 browser smoke 驗證。重要邊界也已確認：正式「產出考題」仍應由 Copilot/OpenClaw 經 MCP pipeline 完成；草稿模板、QA 與版本歷史是生成後的作者工作流層，不應反向取代 MCP generation orchestration。**

**2026-04-15 補充：題目作者工作流第三刀已完成第一版「歷史模板 + blueprint + QA metadata」。`QuestionDraft` 現在新增 `template_data`、`blueprint_data`、`qa_metadata` 三組結構化欄位，並以 `question_drafts.template_data / blueprint_data / qa_metadata` JSON columns 持久化。Streamlit `🗃️ 草稿箱` 頁新增「歷史題型模板」區，模板直接從 `past_exam_questions`（目前 902 題）按 `pattern` 分布萃取，不是 AI 自造 skeleton；建立模板草稿時會帶入歷史年份/題號、blueprint 摘要與 QA 初始欄位。已用 `py_compile`、editor diagnostics、直接 Python smoke（template list -> create draft -> update QA）與 live 8501 草稿箱頁確認可運作。後續若要再往前推，優先做「模板套用到既有草稿」與「相似題提醒前移到列表/入庫摘要」，不要重回直接 bank-first 流程。**

**2026-04-15 補充：題目作者工作流第一優先的第二刀已完成相似題提醒 MVP。新增 `src/application/services/question_similarity_service.py`，以正式題庫 + 活動草稿的題幹文字做正規化比對（SequenceMatcher），在生成審閱區與草稿箱 expander 顯示 duplicate/similar warning。這一版刻意採 soft warning，不在 promote/save 時直接 hard block，避免先把作者流程卡死；若後續要升級成阻擋規則，應先補上更穩定的 similarity metric 與人工覆寫 UX。已用 `py_compile` + 直接 Python snippet 驗證：現有正式題庫題目可回傳 `top_similarity=1.0` 的 match。**

**2026-04-15 補充：題目作者工作流已正式進入第一個高優先切片。`ROADMAP.md` 已新增「題目作者工作流（2026-04-15）」並拆成三層優先級；實作上先完成草稿箱基礎：新增 `QuestionDraft` entity、`IQuestionDraftRepository`、`SQLiteQuestionDraftRepository`、`QuestionDraftService` 與 `question_drafts` schema，並把 Streamlit 導航擴成 `🗃️ 草稿箱`。目前生成頁審閱區已改為「先送草稿箱、再正式入庫」的雙路徑，草稿箱頁已支援篩選、加星、批次編修、批次送入正式題庫、批次封存。這一輪已以 `py_compile` + 臨時 `8505` smoke test 驗證新頁可載入；下一步應聚焦題目模板與 QA/blueprint metadata，不要把更多資料組裝邏輯塞回 `app.py`。**

**2026-04-15 補充：已修正 Streamlit `load_questions()` 與 repository 之間的相容性問題。因現場曾出現 `SQLiteQuestionRepository.list_all()` 不接受 `validated_only` 的 runtime 漂移，UI 端現在會先檢查 `repo.list_all` signature，再決定是否下傳 `validated_only` / `exam_track`，必要時回退成 app-layer filtering，避免整頁崩潰。同步已完成題庫/統計 UX 收斂：sidebar 明確拆成「一般題庫 23 / 歷屆題庫 902 / 歷屆考卷 10」，題庫管理改為「一般題庫 / 歷屆題庫 / 待審題目」tabs，作答練習在 `validated=0` 時會停用 reviewed-only 篩選，生成頁改成 3-step flow 並把 `0 份精確來源教材` 升級成強警告。已以 `py_compile` + 臨時 `8503` Streamlit smoke test 驗證。**

**2026-04-15 補充：已把歷屆題庫的 aggregate / catalog 查詢從 `src/presentation/streamlit/app.py` 下沉到 `SQLitePastExamRepository`，新增 `list_exam_catalog()` 與 `get_statistics()`，讓 UI 不再直接碰 `past_exams` / `past_exam_questions` SQL。同步已把 `app.py` 內全部 `use_container_width=True` 換成新版 `width="stretch"`，以 `py_compile`、editor diagnostics 與臨時 `8504` smoke test 確認頁面正常，且 terminal 不再出現 Streamlit deprecation warning。**

**2026-04-15 補充：已新增 `src/application/services/question_bank_query_service.py`，把一般題庫的內容統計、generated exam 檔案數整合，以及 `validated_only / exam_track` 的 signature-aware 查詢邏輯從 `app.py` 收進 application layer。`app.py` 的 `get_questions_stats()` / `load_questions()` 現在只剩 service facade。之後若要擴一般題庫 dashboard、搜尋或排序，優先加在這個 service，不要再把 read-model 邏輯長回 `app.py`。同一輪已用 `scripts/run_web.sh` 重啟 live 8501，現行 PID 為 `156210`，首頁 live check 正常。**

**2026-04-14 補充：已完成 written 歷屆題庫 `106-114` 的異質來源匯入。新增 `scripts/import_written_past_exams.py` 後，現在可以把 `106-108` 的 RAR/PDF/DOCX、`109-113` 的題本 + 分離式答案檔，以及 `114` 的 DOCX 題本 + JPG 答案表，統一轉成既有 past-exam markdown pipeline 並寫回 SQLite。當前 DB 狀態為：`106/107/108/109/110/111/113/114` 皆已達 `100` 題且 `100` 題有答案；`112` 題本也已完整落庫 `100` 題，但因 workspace 內找不到答案來源，答案欄位維持空白。`109` 年答案鍵已在 2026-04-22 依官方答案表影像修正；`111` 的 `40=BE` 與 `53=AD` 也已保留。**

**2026-04-14 補充：已用真實歷屆題本完成 past-exam parser 第三輪收斂。`109` 到 `113` 五份 PDF 題本皆已驗證可經 asset-aware ingestion 後正確抽出 100/100 題，並已全部落庫，累計 past exam questions = 500。這輪額外修正了 image-style 題目邊界：若上一題以純 `(D)`/`(E)` 收尾，也必須允許下一個連續題號正常切出。當前真正未解的是 `106-108` 的 `rar` 前處理、`114` 題本 `docx` 匯入，以及分離式答案檔（PDF/DOCX/JPG）的 OCR / merge 流程。**

**2026-04-14 補充：`libs/asset-aware-mcp` 已正式發布 `v0.6.5`。本次 release 收斂 large-PDF auto strategy、真正的 `page_ranges` ingestion 與 page-scoped `doc_id` 修正；release commit 已推到 `37068f2`，tag `v0.6.5` 已存在遠端。過程中確認遠端已先存在不同內容的 `v0.6.4` tag，因此沒有覆寫舊 tag，而是安全順推到 `0.6.5`。主 repo 下一步只剩把 submodule pointer 更新到這個 release commit。**

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
- 追 `112` 年筆試答案來源；目前只能維持 question-only coverage
- 決定 oral / ultrasound 歷屆資料是否要納入現有 past-exam repository，或另建非 MCQ 模型
- 讓上層 UI / prompt 直接呼叫 `exam_run_past_exam_extraction`
- `create_exam` 仍讀取 JSON 檔，與 SQLite 主儲存路徑不一致
- 重新 ingest 需要正式 source tracking 的教材 PDF（`use_marker=True`），否則 exam-generation 只能產出 preview 草稿，不可正式入庫
- 將 Streamlit 生成頁正式接上新的 exam pipeline tools，避免聊天模型回答中仍出現舊工具名稱
- 題庫的 `validated_only / exam_track / scope request / heartbeat` 已落地；下一步改成補瀏覽器 smoke test、review workflow 細節與 template/past-exam 的 Web 接線
- 題目作者工作流已進到 draft-first + historical-template 模式：生成候選題先進 `question_drafts`；草稿箱現在可直接從 `past_exam_questions` 建模板草稿，並附 blueprint/QA metadata

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
- **written 非 PDF 來源已打通，但 `112` 年答案來源仍缺**：本地 workspace 未找到對應答案 PDF / DOCX / 圖檔，外部搜尋也因 challenge 無法快速取得
- **oral / ultrasound 歷屆資料尚未併入**：目前已完整覆蓋的是 written MCQ 題庫，若要再擴需先定義資料模型與匯入策略
- **上層 workflow 尚未全面切換**：部分 prompt / UI 仍停留在舊流程
- **新治理切片雖已落地，但仍缺完整 smoke test**：目前已用 repository round-trip + heartbeat job emission 驗證，尚未做完整瀏覽器互動驗證
- **現有 randomized trial 文獻缺少 Marker blocks**：`search_source_location` 會失敗，無法提供 page/line/bbox 級來源
- **知識圖譜已可用但仍非最穩定 gate**：LightRAG/Ollama 的本機模型 fallback 與 root `data/` 平面對齊已修好，root-plane KG smoke query 已成功；但對多文件或較大批次 extraction 仍可能出現 chunk timeout，因此教材正式入庫仍應以 `search_source_location` + evidence pack 為硬性 gate，KG 作為輔助檢索
- **Web 生成頁仍屬 prompt 編排式整合**：UI gating 已正確，但正式生成仍需要把 pipeline tool 調用做成更穩定的服務層接線
- **作者工具仍未完整**：草稿箱已具 draft-first、相似題提醒、歷史模板、blueprint、QA checklist、版本歷史與 promote 前摘要基礎，但尚未支援 filter presets、版本回滾與更細的 promote gate override UX
- **systemd 服務在目前 workspace 內無法直接啟動**：unit / install script 已備妥，且 `/etc/systemd/system/anesthesia-exam-web.service` 已落檔；但此容器 PID 1 非 systemd，因此 `systemctl` 無法連 bus
- **Miller 圖像 caption coverage 仍需 targeted 補強**：碎圖與壞路徑已收斂，但 chapter 30、42、59、66、32 等章節仍有較高 no-caption ratio；詳解/出題若需要圖像證據，應先做章節級 caption/evidence recovery，不要把無 caption 圖直接當作可靠引用

## Next Steps

1. **追 `112` 年答案來源**：一旦取得原始答案檔，直接重跑 `scripts/import_written_past_exams.py --only 112` 補齊 answer coverage
2. **決定 oral / ultrasound 歷屆是否納入**：若要收錄，先定義非單選題在 repository / UI 的表達方式
3. **重 ingest 正式教材**：用 `use_marker=True` 重新建立可精確追來源的 doc_id
4. **補 browser smoke test**：驗證 `📋 出題需求`、題庫審查按鈕與統計頁 heartbeat 卡片的互動流程
5. **擴草稿箱下一刀**：補 filter presets、版本回滾與更清楚的 promote override UX，讓版本歷史不只可看也可回復
6. **補 UI / Agent 接線**：讓生成頁正式消費 pipeline tools，並保留目前已驗證的 source-ready gate / preview mode UX
7. **在真正的 systemd 主機驗證 service lifecycle**：執行 `./scripts/install_systemd_service.sh`，確認 enable/restart/journal 行為
8. **針對 Miller 低 caption coverage 章節補強 evidence recovery**：優先從 latest image audit 的高風險章節開始，讓圖像、頁碼、caption 與 markdown evidence 可一起被詳解/出題流程消費
