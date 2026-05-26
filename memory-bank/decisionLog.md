# Decision Log

## 2026-05-26

### DEC-050: 多人 Web 場景下維持單一 OpenClaw agent，但用 session-key 分流記憶與工具上下文

| 項目 | 內容 |
|------|------|
| **決策** | 保留一隻網站常駐 OpenClaw agent `main`，但禁止所有入口共用 `agent:main:main`。Web chat 依使用者 session 與題目分流，worker 用 `agent:main:job:{job_id}`，scope dispatch 用 `agent:main:scope:{scope_request_id}`，Telegram `/ask` 用 `agent:main:telegram:{chat_id}`。 |
| **問題** | 多人 Web、背景 worker、scope request 與 Telegram 若共用同一個 default session，會互相污染對話歷史，最後造成 default session overflow；即使封存舊 session，fresh agent turn 仍可能因 OpenClaw 直接暴露所有 MCP/skills/tool schema 而超過 local model 實際可承受上下文。 |
| **解決方案** | 在 provider 加 `session_key` 支援並讓各入口傳入穩定 key；封存舊 `agent:main:main`。同時把 repo-local OpenClaw config 調成 lean profile：`tools.toolSearch=true`、`localModelLean=true`、`contextInjection=continuation-skip`、bootstrap caps 與題庫/教材管理 skill allowlist，並把同樣設定落到 `scripts/configure_openclaw_gb10.sh`。 |
| **影響** | 單一 OpenClaw 仍可作為網站考題管理員存在，但記憶隔離符合多人使用。MCP 工具仍完整可用，只是模型先看 compact `tool_search_code`，需要時再搜尋/呼叫實際 asset-aware 或 exam-generator 工具，避免每回合把所有 schema 直接塞進 prompt。 |

## 2026-05-13

### DEC-049: VSIX npm audit hotfix 以 lockfile 升級 `fast-uri` 並發布 asset-aware `v0.6.31`

| 項目 | 內容 |
|------|------|
| **決策** | 對 `v0.6.30` 發現的 VSIX npm audit high severity finding，不用 `npm audit fix --force` 做大範圍升級；採最小 hotfix：更新 `vscode-extension/package-lock.json`，讓 transitive `fast-uri` 解析到 patched `3.1.2`，並同步 bump repo/VSIX 版本到 `0.6.31`。 |
| **問題** | `npm audit` 指出 `fast-uri <=3.1.1` 存在 path traversal / host confusion 高風險 advisory。實際 dependency chain 是 `@vscode/vsce -> @secretlint/node -> @secretlint/config-loader -> ajv -> fast-uri`，本地 lockfile 安裝到 `fast-uri@3.1.0`。 |
| **解決方案** | 先確認 `npm view fast-uri version` 為 `3.1.2`，再用 `npm update fast-uri --package-lock-only` 更新 lockfile，重新 `npm ci` 後 `npm audit --audit-level=high` 回 `0 vulnerabilities`，`npm ls fast-uri` 顯示 `fast-uri@3.1.2`。完成 VSIX/Python/package/Docker/release audits 後，發布 `v0.6.31` GitHub Release。 |
| **影響** | `v0.6.31` 是 security hotfix release，功能內容等同 `v0.6.30`，但 VSIX dependency tree 不再帶該 high severity npm audit finding。後續 extension dependency 更新仍應優先走 lockfile/semver 範圍內最小修復，不要用 force fix 引入不可控 major drift。 |

### DEC-048: asset-aware v0.6.30 release 必須基於最新 `origin/master`，並把 Figure crop 修復作為正式 patch release 發布

| 項目 | 內容 |
|------|------|
| **決策** | 不在 detached `v0.6.29` tag 上直接 commit/tag；先備份 dirty patch，再切到最新 `origin/master` 建立 `release/v0.6.30`，將 PyMuPDF figure crop 修復、metadata、tests 與 release docs 一起發成 `0.6.30`。 |
| **問題** | 本地修補最初掛在 `v0.6.29` tag，而遠端 `master` 已經前進 53 commits。若直接 tag，本次修復會漏掉 master 上的 release harness、docs、VSIX 與 citation workflow 更新，造成新版基準倒退。 |
| **解決方案** | 先輸出 `.codex-backups/asset-aware-v0.6.30-dirty-20260513T110521Z.patch`，再 stash、fast-forward local master 到 `origin/master`、建立 release branch、套回修補。v0.6.30 的 release scope 明確聚焦：page-region crop、caption-anchor crop、A/B multi-panel group crop、decimal caption regex、FigureAsset geometry metadata、isolated fast fallback timeout 與 LightRAG lazy import。 |
| **影響** | Tag/push 前 release gate 必須重新跑在最新 master 基準上。本機目前缺 `npm`，所以 VSIX release gate 不能被視為已通過；若要正式 tag，必須安裝/提供 Node/npm 或在可用環境補跑 extension checks。 |

## 2026-05-12

### DEC-047: Miller 圖像資產以 PyMuPDF page-region display crop 作為主輸出，raw xobject 只保留為 fallback/diagnostic

| 項目 | 內容 |
|------|------|
| **決策** | asset-aware 的 PyMuPDF figure extraction 不再把 `doc.extract_image(xref)` 的 raw embedded image 當作正式教材圖像；正式 display asset 改為 `page.get_pixmap(clip=...)` 的 page-region crop，並把 `raw_path / figure_bbox / crop_bbox / caption_bbox / caption_confidence / extraction_strategy` 寫入 `FigureAsset`。 |
| **問題** | Miller PDF 常把圖像 bitmap、PDF text layer、label、arrow/vector 與 caption 分開儲存。raw xobject 只會抽到 bitmap 本體，因此網站與 agent 看到的圖常常沒有文字、沒有 panel label、沒有圖說；同頁 FIFO caption matching 也會讓 subfigure 對錯 caption 或完全空 caption。 |
| **解決方案** | 用 `page.get_image_rects(xref)` 取得 image bbox，再 render 擴張後的 page clip；caption 偵測支援 `Fig. 42.1` decimal 編號並保留 bbox；caption association 改為 spatial matching；若同一 caption 附近有多個 xobject panel，合併為 `caption_group_page_crop`。保留 raw path 作診斷，但 UX/考題應優先使用 display crop path。 |
| **影響** | Chapter 33/42 targeted reingest 已驗證：`xobject_raw=0`、caption bbox 可用、圖內 label 與圖說進入 display crops。這條路徑在主 runtime 不依賴 Marker，因此與 v0.6.29 的 Pillow 安全 baseline 相容。後續全量 Miller refresh 應沿用此 gate，而不是回退舊 Marker/Torch stack。 |

### DEC-046: asset-aware 升級到 v0.6.29 後採安全 PyMuPDF/blocks/segmentation 主路徑，Marker bbox 能力改為後續隔離策略

| 項目 | 內容 |
|------|------|
| **決策** | 將 `libs/asset-aware-mcp` 升級到上游 latest `v0.6.29`，保留升級前 dirty files 備份與 stash；重新套用 LightRAG lazy import，但不把 v0.6.8 時代的 `marker-pdf` / Torch stack 直接回套進 v0.6.29。全量教材重拆先走 v0.6.29 目前安全的 PyMuPDF/blocks/segmentation pipeline。 |
| **問題** | 使用者需要最新 asset-aware，並用 MCP 重新拆解全部 PDF 供 exam generation 使用；但 v0.6.29 的 `marker` extra 是刻意留空，因為目前 `marker-pdf 1.10.2` 仍要求 `Pillow<11`，與安全 runtime 的 `Pillow>=12.2.0` 衝突。若直接回套舊依賴，等於用 citation 需求換掉 dependency security baseline。 |
| **解決方案** | 先備份 dirty files 到 `.codex/backups/asset-aware-mcp-v0.6.8-dirty-20260512T155356Z/`，再 checkout `v0.6.29`、`uv sync`，只重新套用 LightRAG lazy import。接著用 MCP stdio 對 `98` 份 PDF ingest：`87/87` Miller 分章、`8` 份歷屆考題、`2` 份 uploads 完成；單一完整 Miller 巨檔 3336 頁在 90 分鐘保護時間 timeout，但仍產出 manifest/markdown/blocks。MCP lookup smoke 對 Chapter 21 `propofol/ketamine/etomidate` 查詢成功。 |
| **影響** | exam generation 現在有可用的最新 v0.6.29 artifact corpus，正式出題應優先使用分章 doc_id 與 `search_source_location`。若後續要 bbox/Marker 級 citation，應等 Marker 支援新版 Pillow，或建立隔離 Marker runtime；不要在主服務環境回退到舊且安全性衝突的依賴組合。 |

### DEC-045: OpenClaw 服務化整合採 repo-local agent config；LightRAG 對 asset-aware MCP 保持 optional，不讓停用的 KG dependency 拖垮 Web/agent

| 項目 | 內容 |
|------|------|
| **決策** | user-level `anesthesia-exam-web.service` 預設使用 repo-local OpenClaw agent mode 與 `vendor/openclaw-state/openclaw.json`，其中 MCP server 由 OpenClaw bundled MCP 啟動；`asset-aware` 在 `ENABLE_LIGHTRAG=false` 時不得 import LightRAG adapter。 |
| **問題** | OpenClaw runtime 更新到 `2026.5.7` 後，agent smoke 一開始可跑模型但 bundled `asset-aware` MCP 啟動失敗。root cause 是 `asset-aware` composition root 在設定判斷前 eager import `LightRAGAdapter`，而目前安裝的 `lightrag` 已缺少舊 `EmbeddingFunc` 匯出，造成 optional KG dependency 直接讓整個 MCP server crash。 |
| **解決方案** | 將 `LightRAGAdapter` 改為 lazy import，只有 `settings.enable_lightrag` 為真時才載入；OpenClaw service config 則維持 `ENABLE_LIGHTRAG=false`，讓教材 asset/search/tooling 可先穩定提供給 agent。更新後完整 OpenClaw smoke 顯示 `asset-aware` 48 個工具與 `exam-generator` 26 個工具皆進入 system prompt，`fallbackUsed=False`。 |
| **影響** | Web 服務與 OpenClaw agent 現在可以共用同一套 repo-local MCP config；正式教材出題仍可走 `search_source_location` / asset-aware tools，但 KG/LightRAG 仍是後續可選能力。另已確認 OpenClaw npm production audit 有高/critical advisories，不能用 `npm audit fix --force` 盲目降級處理，應等待或追上游修正版。 |

## 2026-04-24

### DEC-043: Streamlit 先採「非阻塞串流 + 顯式 cache invalidation + 單區塊渲染」救 UX，不急著直接重寫 TypeScript

| 項目 | 內容 |
|------|------|
| **決策** | 先保留現有 Streamlit 架構，透過 background chat job、fragment 同步、mutation 後顯式清 cache，以及把重型 `tabs` 改成單一 active-section 渲染來做性能救援；這一輪不直接改造成前後端分離的 TypeScript SPA。 |
| **問題** | 使用者遇到的主要 UX 痛點是真實的：聊天時每次互動都像整頁重載、左側切頁慢、`st.cache_data` 加上寫入後只 `st.rerun()` 會短時間繼續顯示舊資料。這些問題雖然源自 Streamlit rerun model，但並不代表眼前只能整套重寫。 |
| **解決方案** | 新增 `async_chat.py` 承接背景串流工作，聊天面板改成 fragment 邊界；教材/草稿/題庫/歷屆題/補題需求的 cached read-model 全部補上 mutation 後 invalidation helper；題庫管理與考古題統計頁則改成單區塊渲染與 opt-in 展開重型面板。 |
| **影響** | 目前可以在不離開 Streamlit 的前提下，先把「同步卡整頁」「切頁慢」「寫入後看見舊資料」這三個主 UX bug 收斂。長期若要做到真正 SPA 級別的無感切頁，仍可再評估 TypeScript 重構，但那應該建立在先量清剩餘 bottleneck 之後。 |

### DEC-044: root pytest 預設只跑本 repo tests；若顯式混跑 vendored `asset-aware-mcp` tests，改用 repo-root `conftest.py` 合併雙 `src` package search path

| 項目 | 內容 |
|------|------|
| **決策** | `pyproject.toml` 的 root pytest 設定明確限制為 `testpaths = ["tests"]` 與 `norecursedirs = ["libs/asset-aware-mcp", ...]`；但若使用者顯式指定 `libs/asset-aware-mcp/tests/...` 與 root `tests/...` 同時執行，則由 repo-root `conftest.py` 在 collection/setup 階段切換並合併 `src` package search path。 |
| **問題** | 主 repo 與 vendored `asset-aware-mcp` 都有頂層 `src` package。單純放任 root `pytest` 遞迴收集會讓 collection 在 fresh env 下同時踩到缺依賴、雙 `src` collision 與 `tests` namespace 汙染；但使用者又明確給出 mixed-path command 作為真實重現式，不能只靠「不要這樣跑」帶過。 |
| **解決方案** | 一方面補齊 root dev/test env 真正缺的依賴，讓 `uv run pytest -q` 在乾淨環境下成立；另一方面在 repo-root `conftest.py` 自訂 module collect/setup，按 test file 來源切換 import root，並把已載入的 `src`/`src.application`/`src.infrastructure` 等 package `__path__` 擴成雙 root 搜尋路徑，讓 mixed command 也能成功。 |
| **影響** | 現在文件、fresh env、以及使用者給的 mixed command 三者終於一致：root `uv run pytest` 穩定只跑本 repo test suite，而顯式混跑 vendored tests 也不再因雙 `src` package 汙染而直接崩潰。 |

## 2026-04-23

### DEC-042: Miller 教材圖像修復採「figure-only 全章節刷新 + audit gate」，不再用無界限 strict Marker 全書重跑

| 項目 | 內容 |
|------|------|
| **決策** | 對 Miller 9th 分章教材先做 figure-only refresh，重建每個章節 manifest 的 `assets.figures` 與 `images/`，並以 image audit 指標作為完成門檻；strict Marker 僅保留作為 targeted 高風險章節策略，不作為這台機器上的全書預設重跑方式。 |
| **問題** | 先前 figure manifest 中存在大量碎圖與錯圖：總數達 `4159`，其中 `<20k area` 有 `2267` 張，低變異圖 `1759` 張，甚至單頁可噴出 `268` 張 figure。這會直接污染詳解 grounding 與未來出題 evidence。另一方面，strict Marker 全章節在本機 CPU-bound 環境成本過高，且單頁 smoke 可出現 `0` figures，不適合作為盲目全書重跑方案。 |
| **解決方案** | 在 asset-aware 中新增 Miller high-fidelity profile、Marker bbox crop fallback、PyMuPDF figure filtering 與 figure caption extraction document timeout；再用 `scripts/refresh_miller_figures.py` 對 87 章節做 figure-only refresh，最後用 `scripts/audit_miller_image_quality.py` 產出 before/after 報告。遇到 chapter 74/75 的 path 落盤殘留問題時，採 targeted rerun 修正到 `missing=0`。 |
| **影響** | 最新 audit 結果為 figure 總數 `4159 -> 867`、極小碎圖 `2267 -> 51`、低變異圖 `1759 -> 14`、最大單頁 figure 數 `268 -> 4`，且 missing/unreadable/old-root path 全部歸零。後續焦點應轉向少數章節 caption/evidence matching，而不是再全書重跑圖像。 |

## 2026-04-22

### DEC-041: `109/2020` 年答案鍵修復應採「校對後答案常數 + 單年受控更新腳本」，而不是直接在正式 DB 手工改值

| 項目 | 內容 |
|------|------|
| **決策** | 把 `109年筆試考題答案.pdf` 的官方答案表逐題校對後固化進 `scripts/import_written_past_exams.py`，並新增 `scripts/repair_109_written_answers.py` 對正式 DB 做單年、單來源、可備份的受控更新；不直接手工改 SQLite，也不以整份重匯入覆蓋整卷資料。 |
| **問題** | `2020` 年歷屆題在正式 DB 中曾出現 `100/100` 題 `correct_answer='BONUS'`。追查後發現這不是官方全卷送分，而是 `109年筆試考題答案.pdf` 的隱藏文字層錯誤，導致早期匯入腳本把整份答案檔誤判成 `本題送分`，再以 `BONUS` 覆寫全部答案鍵。這會直接破壞網站上的作答判分。 |
| **解決方案** | 先用原始答案頁影像作為真值來源逐題校對 `1-100` 題答案，讓 `prepare_109_exam()` 回到正常的 answer-map 路徑；正式修復時則只更新 `exam_year=2020` 且 `source_doc_id=doc_109______a9f9c7` 的 `100` 題 `correct_answer`，並在更新前自動建立 DB 備份、更新後輸出 before/after 驗證報告。 |
| **影響** | `109/2020` 年現在已恢復為可互動判分的 written 題庫，且之後若重跑 `scripts/import_written_past_exams.py --only 109`，不會再把答案鍵回滾成 `BONUS`。這次也建立了一個處理正式資料錯誤的模式：先找 root cause、再把修正落回可重現的 code path，最後才更新正式資料。 |

## 2026-04-21

### DEC-040: 第一批正式補寫詳解先落在 `2025` 年，而不是直接寫 `2020` 年；此判斷在當時成立，`2020` 年答案鍵已於 2026-04-22 修復

| 項目 | 內容 |
|------|------|
| **決策** | 第一批正式寫入 `data/questions.db` 的歷屆題詳解，先選 `2025` 年並以小批次 `10` 題落庫；`2020` 年暫時只拿來做 `Miller 9th` 知識 grounding 與乾跑驗證，不當作第一批互動演練資料。 |
| **問題** | 使用者希望 repo 能讓網站上的考古題演練真正可用，因此除了有詳解，還必須能正確判分。在當時的正式 DB 狀態下，`2020` 年 `100/100` 題的 `correct_answer` 都是 `BONUS`，若直接把這一年當成第一批網站題目，即使詳解生成完成，前台作答結果仍會失真。 |
| **解決方案** | 先把批次補寫腳本 `scripts/batch_fill_past_exam_explanations.py` 實際套用在答案鍵完整的 `2025` 年，並持續用 `data/2020 Miller's Anesthesia 9th.pdf` 的文字片段作知識校正。這樣能同時滿足「先有一批可上站互動」與「內容要有教材 grounding」兩個需求。 |
| **影響** | `2025` 年首批 `10` 題詳解已正式寫回，網站端已有一批可判分且有詳解的真實歷屆題。若之後要把 `2020` 年也納入互動練習，下一步優先順序應是修補 `correct_answer`，而不是先無限制批量補 explanation。 |

### DEC-039: 考古題詳解補寫先走「repo context + direct OpenAI-compatible fallback」，不要把網站互動能力綁死在 `opencode` CLI 是否已安裝

| 項目 | 內容 |
|------|------|
| **決策** | 新增 `src/application/services/past_exam_explanation_service.py`，由它負責從一般題庫/歷屆題庫中找相似且已有詳解的 reference questions，組 prompt 生成考古題詳解，並寫回 `past_exam_questions.explanation`。生成路徑優先用現成 provider；若 provider 不可用，則直接讀 `opencode.json` 的 custom OpenAI-compatible provider 設定，呼叫對應 endpoint。 |
| **問題** | 真實 DB 目前約有 900 題歷屆題、其中 800 題缺 explanation；網站雖已有作答與考古題瀏覽，但缺少內建補寫詳解的 use case。另一方面，這台機器目前沒有 `opencode` binary，若把整個功能綁死在 CLI，就算 `opencode.json` 設定正確也無法在站上操作。 |
| **解決方案** | 先做一條較窄、但對使用者立即有價值的能力：從歷屆題庫頁提供單題與小批次補寫詳解，context 主要來自 repo 內既有詳解題，不依賴完整 MCP tool-calling。provider 層補強 `opencode` custom provider/model 解析；UI 則在 provider unavailable 時自動退回 direct endpoint。 |
| **影響** | 這條路不取代完整的教材來源追蹤 generation pipeline，而是補足「考古題互動學習」缺的 explanation layer。後續若要做更嚴格的詳解品質治理，應在此服務上再加 reviewer workflow / provenance / versioning，而不是直接把這類輕量互動塞回 `exam_server.py` 或 Streamlit 頁面裡。 |

### DEC-038: `exam_server.py` 先採「handler registry + per-call application adapter」切出題庫型工具，同時保留 module-level wrappers 穩住既有測試與 monkeypatch 路徑

| 項目 | 內容 |
|------|------|
| **決策** | `src/infrastructure/mcp/exam_server.py` 的題庫型 MCP tools 先抽到 `src/application/services/exam_tool_application_service.py`，`call_tool` 改由 `src/infrastructure/mcp/exam_tool_handlers.py` 的 registry 分派；但 `exam_server.save_question()`、`list_questions()` 等 module-level wrappers 先保留。 |
| **問題** | `exam_server.py` 同時承擔 transport dispatch、題庫 CRUD/validation、generation guide、pipeline harness 與 past-exam workflow；現有 tests 又直接 import `exam_server.save_question()` 與 pipeline helpers，若一次粗暴搬空，容易把 refactor 直接變成介面破壞。 |
| **解決方案** | 先抽最有明確邊界的「題庫型工具」：save/list/create/stats/get/delete/validate/update/audit/search/restore/bulk。server 只保留 bootstrap、tool schema、registry wiring 與 legacy handlers。為了保留測試可 monkeypatch `exam_server.repo` 的能力，wrapper 每次 call 都依當前 module globals 建立 service，而不是綁死 singleton。 |
| **影響** | 下一刀可續拆 `get_generation_guide / get_topics` 或 past-exam adapters，而不必同時重寫 pipeline harness。這也確立了 MCP 層的新邊界：transport/dispatch 留在 infrastructure，題庫 use case 先往 application layer 收。 |

### DEC-037: Streamlit 生成頁先以「application review service + presentation controller/fragments」做局部切片，不直接把整條 prompt orchestration 一次拆爆

| 項目 | 內容 |
|------|------|
| **決策** | 針對 `src/presentation/streamlit/app.py` 的生成頁，先抽出「生成後審閱與正式入庫」這個局部切片：新增 `src/application/services/question_review_service.py` 承接 review payload 到正式題庫的 use case；在 presentation 層新增 `src/presentation/streamlit/generation/controller.py` 與 `fragments.py`，承接 review form 的 render 與 UI action dispatch。 |
| **問題** | `app.py` 原本把 source info render、review form、draft save、formal save、dict -> domain entity mapping 全塞在同一檔內，讓 presentation、use-case orchestration 與 persistence mapping 黏成一塊；若再往裡面堆功能，只會讓 rerun/state 耦合更難拆。 |
| **解決方案** | 不先動最重的 prompt orchestration，而是先切出 review/save slice，讓正式入庫回到 application layer，Streamlit 只保留頁面組裝與導覽 callback。這樣既能縮小 `app.py`，也不會在同一刀把 generation flow、session_state 與 UI layout 全部一起打散。 |
| **影響** | 後續若要再收斂 `app.py`，應延續這個 pattern：presentation 內再拆 controller / fragments；真正的 formal save、promote、查詢與 gate 判斷則盡量下沉到 application service。若下一刀改拆 `exam_server.py`，也應比照「transport handler -> application adapter」而不是讓 MCP tool 直接長成第二個胖 controller。 |

### DEC-036: 在維持 SQLite 的前提下，資料層改採 SQLAlchemy QueuePool + connection hardening；多 writer 路徑則統一升級為 `BEGIN IMMEDIATE`

| 項目 | 內容 |
|------|------|
| **決策** | `src/infrastructure/persistence/database.py` 不再每次裸開 `sqlite3.connect()`，而是改成 per-process SQLAlchemy `QueuePool`；所有 checkout 連線統一套用 `journal_mode=WAL`、`busy_timeout=15000ms`、`foreign_keys=ON`、`synchronous=NORMAL`、`wal_autocheckpoint` 等 PRAGMA。主要 writer repositories（question / past exam / scope request / draft）則在寫入入口升級成 `BEGIN IMMEDIATE`。 |
| **問題** | 單純每次直連 SQLite 雖然在低併發可用，但在「多個使用者同時操作 Web + heartbeat 背景寫入 + MCP agent 存題 + importer/批次工作常駐跑」的情境下，缺少成熟 pool manager、busy timeout 與明確的 writer transaction policy，容易讓 lock contention 行為漂移，也難以從 log 辨識實際連線狀態。 |
| **解決方案** | 引入 SQLAlchemy pool 做成熟的 per-process connection lifecycle 管理，同時保留現有 DBAPI repository 介面，避免整批重寫資料層。connection checkout 時額外做 DBAPI ping/retry；schema init 完成後會 dispose 既有 pool，確保後續 checkout 使用帶 hardening 的 fresh connections。另補 focused regression tests 鎖住 pool reuse、PRAGMA hardening 與同進程多執行緒 question writes。 |
| **影響** | 這能顯著提升單機多執行緒/多工作流程的穩定性，但不改變 SQLite「跨 process 同時間仍只有單一 writer」的物理限制。若後續需求再升到真正高併發多 writer，仍應評估 PostgreSQL；但在目前單機服務形態下，這次升級已比原本的裸連線模式穩健很多。 |

### DEC-035: Logging 必須由共用 bootstrap + contextvars 進行統一初始化；資料層讀寫採 debug/info 分流，避免長期服務被觀測訊號洗版

| 項目 | 內容 |
|------|------|
| **決策** | 新增 `src/infrastructure/logging/setup.py` 的共用 `bootstrap_logging()`，由 Web、MCP、CLI 與所有 Python scripts 統一初始化。logging 設定改為 env-driven，支援 `log level`、`debug switch`、`JSON console`、`rotation` 與 `run_id` context binding；database / repository / service / importer 全部走同一套結構化欄位。 |
| **問題** | 先前只有 Streamlit app 真的呼叫 `configure_logging()`，其他入口不是沒初始化，就是只有零散 `logger.info()`；這使得 `run_id / doc_id / question_id / provider` 無法沿著 workflow 穩定傳遞，也沒有 rotation 與 debug switch 可支撐長期服務除錯。 |
| **解決方案** | 抽出 idempotent bootstrap，利用 structlog contextvars 綁 `run_id` 與 workflow metadata；entrypoint 先綁 provider 與 run id，資料層讀操作打 `debug`、寫操作打 `info`、錯誤打 `exception`。同一輪順手把生成頁的長流程狀態聚合到 `st.status`，並把草稿箱低風險提示改用 `st.toast`，減少 UI 雜訊。 |
| **影響** | 後續新增任何 Python entrypoint、background script 或 repository/service 補點，都必須走 `bootstrap_logging()` 與 context binding，不要再各自手刻 logging 初始化。若要繼續收斂 Streamlit UX，優先使用 `st.fragment` / `st.dialog` 這類新版 API，把長流程拆成較小互動面。 |

## 2026-04-15

### DEC-030: 作答練習的考古題模式應以「年份區間 + 單份/多份考卷」建題池，並沿用同一套 scoring state；另外每次重開回合都必須先清 practice radio widget state

| 項目 | 內容 |
|------|------|
| **決策** | `✍️ 作答練習` 的歷屆來源不再停在單一 selectbox，而是升級成 `考古題模式`：先選 `起始年度 / 結束年度`，再決定 `多份混抽 / 單份考卷`，最後把選到的歷屆題目併成同一個 practice pool。提交後仍沿用既有 `practice_questions / practice_answers / practice_submitted` 這套 state，不另開平行 scoring flow；但每次開始新回合前必須先清掉 `q_<question_key>` radio widget state，避免同題重開時殘留上一輪答案。 |
| **問題** | 前一版只支援單份考古題，無法滿足多份混抽與年份區間需求；而 Streamlit radio widget 又會把上一輪的值留在 session state，若剛好抽到同一批題目，清空 `practice_answers` 仍不足以讓 UI 真正回到未作答狀態。 |
| **解決方案** | 在 practice 設定區新增 `考古題模式` 與 `練習方式 / 起始年度 / 結束年度 / 納入考卷` 控制，題池一律先在 app layer 組好，再沿用既有提交/計分流程。結果區若偵測來源為 past exam，額外顯示 `年度表現 / 考卷表現 / 題型與主題 / 錯題回顧`。session helper 則統一負責清掉 practice radio widget key，避免 stale widget state。 |
| **影響** | 後續若再擴成「弱點題再練一次」「跨回合錯題本」等功能，應繼續建立在單一 practice session state 與這個 past-exam pool builder 上，不要另建第二套作答頁或第二套 answer state。 |

### DEC-029: 作答練習的題目來源要明確分流；一般題庫 filter 不得直接套到歷屆考卷

| 項目 | 內容 |
|------|------|
| **決策** | `✍️ 作答練習` 現在明確提供 `一般題庫 / 指定考古題` 來源切換；若選考古題，練習頁只套 `題數 / 難度 / 主題 / 隨機順序`，不套用 `validated_only` 與 `exam_track`。 |
| **問題** | 先前作答練習只呼叫 `load_questions()`，實際上只會讀一般題庫；雖然 app 內已經有 `load_past_exam_catalog()` 與 `load_past_exam_questions()`，但完全沒接到 practice UI。若硬把一般題庫的審查/考試類型 filter 直接套到考古題，也會混淆兩個資料層的語意。 |
| **解決方案** | 在 practice 設定區增加來源切換與考古題 selectbox。一般題庫仍走 `load_questions(validated_only, exam_track)`；考古題則改走 `load_past_exam_questions(past_exam_id)`，再於 app layer 套用共用的難度/主題/隨機順序。 |
| **影響** | 後續若要再擴成 `多份考古題混合練習` 或 `歷屆年份篩選`，應沿用這個 source split，不要再把 past exam 當成一般題庫的一種 exam_track。 |

### DEC-028: Draft box 的 browser E2E 不應直接回寫 multiselect widget key；要用 test-mode selection override 穩定跨 rerun 保留 batch promote 對象

| 項目 | 內容 |
|------|------|
| **決策** | 在 `src/presentation/streamlit/app.py` 對草稿箱批次選取新增 `draft_batch_selection_override` 與 `draft_batch_selection_reset_pending`，並只在 `ANESTHESIA_EXAM_E2E_TEST_MODE=1` 下提供最小 test anchor `🧪 E2E 全選目前草稿`。 |
| **問題** | Playwright 實測顯示，Streamlit multiselect 一旦已經 instantiate，就不能在同一輪 script 中回寫同 key 的 `st.session_state`；否則會觸發 `StreamlitAPIException`，也讓 batch promote 的 button 在 rerun 過程中失去穩定的 selected ids。 |
| **解決方案** | 正式 UI 仍保留原本 multiselect；E2E mode 另外維持一份 selection override，讓 browser smoke 可在外部製造 partial failure（例如刪掉其中一個 draft）後，仍把原始 batch selection 傳進 promote。需要清空時只設 reset flag，下一輪在 widget mount 前再清除 widget-backed state。 |
| **影響** | 後續若還要補更多 Streamlit browser smoke，只要牽涉「先選取、再外部改資料、再按批次按鈕」這種 rerun-sensitive 路徑，都應沿用 override/reset-pending pattern，不要再次直接改 widget key。 |

### DEC-027: Streamlit E2E smoke 要用臨時 DB + 真瀏覽器執行，不得依賴現場 questions.db 或手動 browser session

| 項目 | 內容 |
|------|------|
| **決策** | 新增 `tests/test_streamlit_practice_browser.py`，以 Playwright 啟動真 Chromium，並透過 `ANESTHESIA_EXAM_DB_PATH` 注入暫時 SQLite DB 來 seed 固定題目。 |
| **問題** | 原本 `library -> practice` 與 `practice submit` 只有人工 browser smoke。若直接打現場 `data/questions.db`，測試結果會隨題庫內容漂移，且無法在 CI / 重跑時保證 deterministic。 |
| **解決方案** | 在 persistence 層增加 env-based DB override，讓 E2E server process 使用暫時 DB；測試自行 seed 題目後再啟動 Streamlit，確保題目內容、分數與跳頁行為可重現。 |
| **影響** | 之後任何 UI smoke 若牽涉到資料庫內容，都應優先沿用這個 temp DB pattern，而不是直接共享正式資料庫。 |

### DEC-025: Draft promote 的資料一致性要由 shared SQLite transaction 保證，不再依賴事後補償 rollback

| 項目 | 內容 |
|------|------|
| **決策** | `QuestionDraftService.promote_drafts()` 現在對每個 draft promotion 開單一 shared SQLite connection，並在同一 transaction 內完成 `question_repo.save_with_connection()` 與 `draft_repo.mark_promoted_with_connection()`。 |
| **問題** | 前一版雖已補「question 已入庫但 mark_promoted 失敗時回滾 soft delete」的補償機制，但本質上仍是兩段式 workflow；正式題目與草稿狀態的一致性仍不是由 DB transaction 本身保證。 |
| **解決方案** | 對 question repo / draft repo 新增內部的 connection-aware save / promote API，讓 service 在 `BEGIN IMMEDIATE` 下共用同一 SQLite transaction；任一步驟失敗就直接 rollback，不讓半成功資料落盤。 |
| **影響** | 後續若還要擴充 promote gate（QA / similarity override / reviewer approvals），都應沿用這條 shared transaction 路徑，不要退回分段寫入再補償修正。 |

### DEC-026: Streamlit 程式化跳頁不得直接回寫已實例化 widget 的 session_state；應由 current_page 驅動，render 前同步 widget state

| 項目 | 內容 |
|------|------|
| **決策** | `navigate_to()` 不再直接設定 `st.session_state.page_nav`；它只改 `current_page` 與 URL query params，sidebar radio 則在每輪 render 前用 `sync_nav_widget_state()` 依 `current_page` 回填。 |
| **問題** | 瀏覽器 smoke 實際抓到 `StreamlitAPIException: st.session_state.page_nav cannot be modified after the widget with key page_nav is instantiated`。也就是說，只要在同一輪 script 中先 render 出 radio，再透過某個按鈕 handler 去改 `page_nav`，就會在 runtime 爆掉。 |
| **解決方案** | 把 `page_nav` 降為 widget projection，不作為程式化跳頁的直接寫入目標；改由 `current_page` 作為單一導覽狀態，再於下一輪 render 前同步 radio checked state。 |
| **影響** | 後續新增任何 page-level quick action 或 CTA，只能呼叫 `navigate_to()` 或更新 `current_page`，不能再直接動 `page_nav`。 |

### DEC-024: Draft workflow 的 guard 問題優先以「輸入前驗證 + 失敗補償 + DB 串行化」收斂，而非一次重寫整個 transaction stack

| 項目 | 內容 |
|------|------|
| **決策** | 第二輪 audit 發現 draft workflow 的主要風險集中在三處：batch enum 轉換、promote 半成功、version snapshot race。這一輪不直接重做 repository 架構，而是優先補三種 guard：`bulk_update()` 在迴圈前先驗證 enum、`promote_drafts()` 在 `mark_promoted()` 失敗時補償回滾正式題目、`save()` 在版本號分配前先取 `BEGIN IMMEDIATE` transaction。 |
| **問題** | 若直接沿用原狀，非法 batch 參數會留下部分更新；draft promote 在正式題目已入庫但草稿標記失敗時會留下 orphan question；version snapshot 以 `MAX(version_number)+1` 分配時存在並發撞號風險。 |
| **解決方案** | 用最小修正先把三個 root cause 收斂：輸入在進入 loop 前就 fail fast、promotion failure 做補償式 delete、SQLite writer 在 `save()` 入口就串行化。再用 focused regression tests 鎖住這三條行為。 |
| **影響** | 後續若要再往上升級成完整跨 repository transaction，應建立在這些 guard 已存在的前提上；不要為了追求一次性重構而放任現場資料一致性風險持續存在。 |

### DEC-023: Streamlit 導航 state 必須同時收斂到單一 widget key，並持久化到 URL query params

| 項目 | 內容 |
|------|------|
| **決策** | `src/presentation/streamlit/app.py` 的左側導航不再以 `st.radio(index=PAGE_OPTIONS.index(current_page))` 驅動，而改採 `page_nav` widget key + callback 同步 `current_page`，所有程式化跳頁統一走 `navigate_to()`，並把 active page 寫入 URL `?page=` query param。 |
| **問題** | 原本的 `radio(index=...)` + `st.session_state.current_page = page` 模式在 rerun 時會讓 widget state 與 page state 互相覆寫；此外瀏覽器 refresh 會建立新 session，使 `current_page` 掉回預設頁，造成「點了會卡、refresh 會跳回」的 UX。 |
| **解決方案** | 導航 widget 使用固定 key，由 callback 負責同步 `current_page`；程式內任何跳頁都更新 `current_page` 與 `page_nav`，同時把對應頁面 slug 寫進 `st.query_params["page"]`。初始化時則先從 query param 還原頁面。 |
| **影響** | 後續若新增任何 sidebar/page 切換功能，不可再直接依賴動態 `index` 或只改 `current_page`；否則很容易重新引入 refresh reset 或 widget/content 不同步問題。 |

### DEC-022: Copilot/OpenClaw + MCP 仍是正式出題層；草稿模板/QA/版本歷史屬於生成後作者工作流層

| 項目 | 內容 |
|------|------|
| **決策** | 正式「產出考題」仍由 Copilot/OpenClaw 經 MCP pipeline（教材查詢、來源定位、生成、儲存）完成；草稿模板、QA checklist、相似題摘要與版本歷史則是生成後的 authoring/review layer，依附在 `question_drafts` 上。 |
| **問題** | 若把模板/QA/history 直接混進 MCP generation pipeline，會模糊「證據鏈生成」與「人工審閱整理」的責任邊界，也讓 UI/作者工具反過來污染 agent workflow。 |
| **解決方案** | 保持 MCP layer 專注在 evidence-backed generation；把草稿箱擴成 post-generation authoring workspace，承接 template、blueprint、QA、similarity 與 version snapshots。 |
| **影響** | 現在的方向是正確的，但仍不算完整：後續應補 promote override UX、版本回滾與更明確的 author gate，而不是把這些責任推回 MCP prompt orchestration。 |

### DEC-021: 題目模板必須直接建立在已正規化的歷史題庫上，並以 draft JSON metadata 承接 blueprint / QA

| 項目 | 內容 |
|------|------|
| **決策** | 草稿箱的題目模板不另建手寫模板表，也不讓 AI 自行幻想 skeleton；第一版直接從 `past_exam_questions` 依 `pattern` / `topics` / `concept_names` 萃取模板，並把模板引用、blueprint 摘要、QA checklist 存入 `question_drafts.template_data / blueprint_data / qa_metadata` 三個 JSON 欄位。 |
| **問題** | 使用者明確要求「題目模板應該要參考真的的歷史資料」；若模板只是 UI 側的假資料或零散欄位，之後很難追來源，也會讓作者工作流再次退化成沒有證據鏈的容器。 |
| **解決方案** | 新增 `QuestionTemplateService` 直接讀既有 `past_exam_questions` corpus 產生模板；建立模板草稿時同步帶入來源年份/題號、歷史 blueprint 摘要與 QA 初始欄位。metadata 先採 JSON 欄位承接，保留未來擴充 checklist / history / reviewer signal 的空間。 |
| **影響** | 後續若要做「套用模板到既有草稿」「promote 前摘要卡」「版本歷史」等作者工具，優先沿用這三組 metadata 擴充，不要再把臨時欄位塞回 `Question` 本體或 `app.py` session state。 |

### DEC-020: 相似題提醒先採 soft warning，不直接阻止作者送草稿或正式入庫

| 項目 | 內容 |
|------|------|
| **決策** | 先以 `QuestionSimilarityService` 做題幹文字正規化比對，於生成審閱區與草稿箱顯示 duplicate/similar warning；目前不在 save/promote 流程做 hard block。 |
| **問題** | 使用者希望先有相似題提醒，但若在第一版就直接阻止 promote/save，容易因簡單文字比對的誤判把作者流程卡死，也缺少「仍要覆寫入庫」的清楚 UX。 |
| **解決方案** | 用 SequenceMatcher + normalized text 對正式題庫與活動草稿做輕量比對，先把風險顯示在 UI；保留人工判斷空間，等之後有更穩定的 metric 與覆寫流程再考慮升級為阻擋。 |
| **影響** | 之後若要把相似題檢查移到 promote gate，必須同時設計人工覆寫、閾值調校與更可信的 similarity signal，不能只把 warning 直接改成 error。 |

### DEC-019: 題目作者工作流改為 draft-first，正式題庫只接收 promote 後的題目

| 項目 | 內容 |
|------|------|
| **決策** | AI 生成或審閱中的候選題，預設不直接寫入正式 `questions`，而是先進 `question_drafts` 草稿箱；使用者在草稿箱完成批次編修、加星、篩選與審查後，再執行 promote 送入正式題庫。 |
| **問題** | 目前 Web 對「生成候選題」與「正式題庫題目」的工作流界線過薄，容易讓低品質或尚未整理的題目直接污染正式 bank，也不利於之後加上相似題提醒、模板、版本歷史與 QA checklist。 |
| **解決方案** | 新增 `QuestionDraft` domain model、draft repository / service、`question_drafts` schema，並在 Streamlit 增加 `🗃️ 草稿箱` 頁；生成頁審閱區優先提供「送進草稿箱」，正式入庫則成為次路徑或 promote 動作。 |
| **影響** | 後續作者工作流功能應以草稿箱為核心擴充：相似題提醒、模板、blueprint、QA checklist、版本歷史等都應掛在 draft/promote 這條鏈上，而不是直接耦合到正式題庫 CRUD。 |

### DEC-018: 一般題庫的 UI read-model 應下沉到 application service，而非持續堆在 app.py

| 項目 | 內容 |
|------|------|
| **決策** | 一般題庫的統計整合、generated exam 檔案計數，以及 `validated_only / exam_track` 的 signature-aware 查詢邏輯，不再留在 `src/presentation/streamlit/app.py`，而是下沉到 `src/application/services/question_bank_query_service.py`。 |
| **問題** | 雖然歷屆題庫 aggregate 已先下沉到 repository，但一般題庫這邊若仍把 read-model、相容邏輯與 dict 轉換留在 `app.py`，Presentation 層還是會繼續膨脹，而且之後新增排序/搜尋/儀表板時很容易再長成第二坨 orchestration code。 |
| **解決方案** | 新增 query service，讓 `app.py` 的 `get_questions_stats()` / `load_questions()` 只作 facade；service 內統一整合 question repo、past exam repo 與 generated exam file count，並保留對舊版 repository signature 的容錯。 |
| **影響** | 後續一般題庫若要加複合搜尋、排序、分頁、儀表板摘要，應優先擴 `QuestionBankQueryService`；Presentation 層盡量只留 UI 狀態與 render logic。 |

### DEC-017: 歷屆題庫 aggregate 應下沉到 repository，Streamlit width API 應一次性遷移完畢

| 項目 | 內容 |
|------|------|
| **決策** | `past_exams` / `past_exam_questions` 的清單與統計查詢不再留在 `app.py` 直接寫 SQL，而是下沉到 `SQLitePastExamRepository`；同時把 `app.py` 全部 `use_container_width=True` 一次性換成 `width="stretch"`。 |
| **問題** | UI 直接持有 aggregate SQL 會讓 `app.py` 持續膨脹，也使資料口徑邏輯散落在呈現層；另外 Streamlit 已對 `use_container_width` 發出移除警告，若只修局部，後續還會持續在 terminal 噴 warning。 |
| **解決方案** | 在 past exam repository 補 `list_exam_catalog()`、`get_statistics()` 兩個 read API，讓 UI 只拿 summary data；width API 則採一次性全面替換，避免留下零星舊呼叫。 |
| **影響** | 後續若還要擴歷屆 dashboard / 篩選，應優先加在 repository/service，而不是回到 `app.py` 直寫 SQL；新增 UI 元件時也應直接使用新版 `width` 參數。 |

### DEC-016: 題庫 UI 必須明確分開一般題庫與歷屆題庫，且 repository 篩選需容忍 runtime signature 漂移

| 項目 | 內容 |
|------|------|
| **決策** | Streamlit 不再把 sidebar / 統計中的單一「題目數」當成全域內容量；改明確拆成一般題庫、歷屆題庫、歷屆考卷。另一方面，`load_questions()` 不直接假設底層 repo 一定支援 `validated_only` / `exam_track` 參數，而是在 UI 邊界做 signature-aware 相容處理。 |
| **問題** | 使用者看到 `23` 時會自然誤判 earlier past-exam import 失敗；同時現場也曾出現 `SQLiteQuestionRepository.list_all()` runtime 實作與目前 source signature 不一致，導致作答頁直接 `TypeError`。 |
| **解決方案** | `get_questions_stats()` 額外統計 `past_exams` / `past_exam_questions`，題庫管理改為「一般題庫 / 歷屆題庫 / 待審題目」tabs，作答頁對 `validated=0` 的 reviewed-only 篩選做 disabled + 說明；`load_questions()` 先 inspect `repo.list_all` parameters，再決定是否傳入 repo-level filters，否則於 app layer 補過濾。 |
| **影響** | 之後所有 Web 文案都應維持這組名詞口徑，不可再把歷屆題庫藏在單一「題目數」背後；若 repository 介面再演進，應優先維持 UI 邊界容錯，避免單一實作漂移導致整頁 crash。 |

### DEC-015: Web 啟動入口統一為 run_web.sh + systemd unit

| 項目 | 內容 |
|------|------|
| **決策** | 正式部署以 `scripts/run_web.sh` + `deploy/systemd/anesthesia-exam-web.service` 為單一啟動路徑；`main.py` 只保留為同命令的 Python 入口 |
| **問題** | 先前 README / instruction / `main.py` / 手動啟動方式彼此不一致，而且 `uv sync` 預設也不會帶入 Streamlit optional dependency，導致照文件操作不一定能啟動 Web |
| **解決方案** | 新增統一啟動腳本與 systemd 安裝腳本，`main.py` 改為呼叫目前 interpreter 的 `python -m streamlit`，並同步修正文檔與部署指引 |
| **影響** | 後續所有部署 / instruction / README 都應以 `scripts/run_web.sh` 與 `anesthesia-exam-web.service` 為準；若在非 systemd 容器內驗證，只能做 unit static verify，不能要求 `systemctl` 成功 |

## 2026-04-17

### DEC-033: 教材題必須把 `preview_only` 與 formal-save 當成兩個一級狀態，且 formal-save gate 必須同時落在 UI 與後端

| 項目 | 內容 |
|------|------|
| **決策** | textbook generation 現在明確拆成 `preview_only` 與 `formal-save-ready` 兩種狀態。Streamlit review UI 會顯示每題 gate 結果與原因；`exam_server.save_question()` 也會硬性拒絕 `preview_only=true` 或缺少 `stem_source / answer_source / explanation_sources` 的教材題目。 |
| **問題** | 先前即使 UI 提示某份教材只能 preview，仍可能被繞過前端後直接送進正式題庫；此外 evidence pack 若只在 UI 組裝、沒有後端驗證，會讓 formal-save 規則退化成「只是提醒，不是保證」。 |
| **解決方案** | 新增 `TextbookGenerationService` 負責標記 preview-only、組 evidence pack 與判定 `formal_save_ready`；UI 只負責呈現狀態與 disable 按鈕，真正的 save gate 則由 `exam_server` 再驗一次。 |
| **影響** | 後續若再加 reviewer override 或 pipeline artifact，必須建立在這個雙層 gate 上；不能退回只有前端提示、後端照存的弱規則。 |

### DEC-034: 教材 source readiness 的根據是可搜尋 blocks 與實際 source probe，不是 Marker/markdown 成功與否；若 Marker blocks 不可用，可接受共享層 fallback 合成 searchable blocks

| 項目 | 內容 |
|------|------|
| **決策** | 對教材型 PDF，`source_ready` 的判定標準是 `search_source_location` 能否在同一資料平面成功命中正文，且 `blocks.json` 需具備可搜尋文字與 line metadata。若 Marker 只吐出空的 `MarkdownOutput` shell，但 markdown 與 PDF page text 仍存在，asset-aware 允許在 shared infrastructure 層自動合成 searchable blocks。 |
| **問題** | Miller 的 root-plane doc 一開始雖有 `full.md` 與 manifest，卻因 `blocks.json` 幾乎是空殼，導致 source lookup 完全失效。若只看「Marker parse 成功」或「有 markdown」，會錯把 preview-ready 當成 formal-save-ready。 |
| **解決方案** | 在 `marker_adapter.py` 新增 markdown + PDF page text 的 block synthesis fallback，並把 `document_tools.search_source_location()` 補強到可回傳 line/snippet 資訊；此外 LightRAG working dir 也必須跟 root `data/` 平面一致，否則 KG 與 source lookup 會落在不同資料面。 |
| **影響** | 後續任何 textbook formal-save gate 都必須以 source probe 為真值來源。KG 可以輔助檢索，但不能替代 precise source evidence。 |

## 2026-04-16

### DEC-032: 教材型 generation 的正式入庫 gate 不可只看 markdown/manifest；必須驗證 `search_source_location` 真的能命中正文

| 項目 | 內容 |
|------|------|
| **決策** | 對教材型 PDF，`source_ready` 的定義從「已有 `full.md` / manifest / Marker ingest」提升為「同一個 doc_id 上 `search_source_location` readiness probe 可成功命中實際正文，且 `blocks.json` 含可搜尋文字 block」。若 probe 失敗，只能產出 preview/draft，不得正式入庫。 |
| **問題** | Miller `doc_2020_miller_s_anesthesia_9th_7481c2` 在 root `data/` 平面雖然有可讀的 `doc_id_full.md`，也可列到章節標題，但實際 `blocks.json` 只有兩個空的 `MarkdownOutput` shell，導致 `search_source_location` 對真實正文句子全部查無結果。若只看 markdown/manifest，就會誤判為「可正式引用」。 |
| **解決方案** | 將教材 evidence gate 明確分成兩層：1) 可讀層：`full.md` / chapter / section 可供 preview 草稿閱讀；2) 正式引用層：必須再通過 `search_source_location` probe 與 non-empty searchable blocks 檢查。若 KG (`consult_knowledge_graph`) 失敗，可退回 chapter/full_text 輔助閱讀，但仍不得跳過 source probe。 |
| **影響** | 後續 textbook/chapter generation workflow 必須把 readiness probe 寫成明確 phase gate；否則很容易再次把「Marker 成功 + markdown 可讀」誤當成已具備 page/line/bbox 級來源追蹤能力。 |

### DEC-031: Miller 這類大型教材先以 page-range 歸檔驗證為主；全書索引前必須先解決 LightRAG endpoint，且教材型出題不得沿用 past-exam extraction flow

| 項目 | 內容 |
|------|------|
| **決策** | 對 `2020 Miller's Anesthesia 9th.pdf` 這類大型教材，現階段先以 `asset-aware-mcp` 的 `page_ranges + marker_max_pages_per_chunk + extract_figures=False` 做章節/頁段級歸檔驗證，不直接整本 hard ingest；同時明確區分「教材 ETL」與「考古題 extraction」兩種流程。教材章節不能直接丟進 `run_past_exam_extraction()` 當成 numbered-question corpus。 |
| **問題** | 現場 Miller 檔案雖然只有 `107.36 MB`，但實際頁數達 `3336` 頁；asset-aware 端的大檔 ETL 已能處理局部頁段，但只要啟用 LightRAG 就會打到 `http://localhost:11434/api/embed` / `api/chat` 回 `404`。另外 exam 端目前的 `PastExamExtractionService` 是為「已有題號與答案」的文檔設計，對 textbook chapter 雖能讀 manifest/markdown，卻不會抽出任何題目。 |
| **解決方案** | 先在 `ENABLE_LIGHTRAG=false` 下驗證 PyMuPDF/Marker 兩條局部 ingest 路徑與歸檔產物；全書處理前先補通 Ollama/LightRAG endpoint，再決定是否批次分章索引。另一方面，對教材出題要另走 chapter/textbook generation workflow，不再誤用 past-exam extraction。這一輪並順手補了 `PastExamExtractionService.load_asset_document()` 對 asset-aware 舊命名 `manifest.json/content.md` 的相容讀取。 |
| **影響** | 後續若要讓 Miller 真正支撐教材出題，優先事項是：1) 補齊 KG/embedding 基礎設施；2) 設計教材型 chapter-level generation service / prompt；3) 若要做長書索引，採分頁段或分章批次 ETL，而不是一次整本同步處理。 |

## 2026-04-14

### DEC-014: 題目切分只看連續題號，不可再加「純選項標籤後禁止切題」的 blanket guard

| 項目 | 內容 |
|------|------|
| **決策** | `PastExamExtractionService` 的新題判斷維持「候選題號 = 上一題 + 1」即可，不再加入「若前一行是純 `(A)/(B)/...` 就不可切題」的 blanket guard |
| **問題** | 這個 guard 雖曾用來擋住圖題選項內容誤切，但在真實 `111` / `112` 題本裡，某些 image-style 題目本來就以純 `(D)` / `(E)` 收尾，結果會把下一題 `94` 或 `40` 整段吞掉 |
| **解決方案** | 移除 blanket guard，完全依賴 sequence-aware 題號判斷，並新增 regression test 覆蓋「圖題以純選項標籤結束後，下一題仍須正確切出」 |
| **影響** | `109-113` 五份 PDF 題本目前皆可穩定抽出並落庫 100/100 題；後續若再遇到圖題，先檢查題號序列，不要優先加 broad heuristic |

### DEC-013: 歷屆題本切題改採 sequence-aware 判斷，不再以「點號後不得接數字」硬切

| 項目 | 內容 |
|------|------|
| **決策** | `PastExamExtractionService` 的題目起始判斷改為 sequence-aware：只有在候選題號符合上一題 `+1`，且不是純選項標籤後面的續行時，才視為新題 |
| **問題** | 只用 regex 禁止 `.` 後面接數字雖能避開 `2.1 mmol/L`、`51.2kg` 這類誤切題，但會錯殺真實題幹如 `11.33 歲女性...` |
| **解決方案** | 放寬 `QUESTION_START_RE`，把誤判防線移到迴圈上下文：結合目前題號序列與 `OPTION_LABEL_ONLY_RE` 決定是否切題，並補 regression tests 覆蓋三種真實格式 |
| **影響** | 真實 `109` / `113` 題本已可穩定抽出 100/100 題；後續若擴更多年份，優先沿用上下文判斷而非再把 regex 調得更僵硬 |

### DEC-012: 已存在遠端 release tag 時不得重用版號，改順推下一個 patch

| 項目 | 內容 |
|------|------|
| **決策** | 發現 `asset-aware-mcp` 遠端已存在不同內容的 `v0.6.4` tag 時，不覆寫既有 tag，改把當前 release 順推為 `v0.6.5` |
| **問題** | 若直接 force-push 重寫既有 release tag，會破壞已對外發布的版本語意，也讓子模組 pointer、PyPI / extension metadata 與使用者安裝結果失去可追溯性 |
| **解決方案** | 保留遠端既有 `v0.6.4`，將 large-PDF/page-range ingestion 這批新內容升版為 `0.6.5`，重新同步 package metadata、CHANGELOG 與 extension 釘版參數 |
| **影響** | 主 repo、安裝指令與後續 release notes 都應以 `v0.6.5` 作為這批 page-range ingestion 修正的正式版本 |

### DEC-011: 大 PDF 採 subset + remap 策略，避免全本 ingestion 與頁碼失真

| 項目 | 內容 |
|------|------|
| **決策** | `asset-aware-mcp` 的 page-range ingestion 先 materialize `selected_pages.pdf` 處理指定頁段，再把 markdown / toc / table / image / Marker 輸出頁碼 remap 回原始 PDF 頁碼；另外在 Marker parse 內建 large-PDF auto strategy |
| **問題** | 直接 ingest 整本大型 PDF 容易造成記憶體與輸出量膨脹；若只做局部處理但不 remap 頁碼，來源追蹤會對不上原始 PDF；若 `doc_id` 不納入 page range，同一 PDF 不同頁段會 collision |
| **解決方案** | 頁數超過 800 頁自動 chunk、圖片量過高時自動停用 figure extraction；page-range ingestion 時產生 page map、重寫輸出頁碼，並讓 `doc_id` 帶入 page-range scope |
| **影響** | 之後上層 ingest / parse / UI 應優先暴露 `page_ranges`，並以 remapped original page numbers 作為精確來源顯示基準 |

### DEC-009: Heartbeat 改採 file-based job contract

| 項目 | 內容 |
|------|------|
| **決策** | `HeartbeatService` 不直接呼叫 agent；改為把補題需求寫成 `data/jobs/*.json` |
| **問題** | 使用者明確要求 heartbeat 產出的工作應讓外部 agent / OpenClaw 讀取，而非 UI 內直接執行 |
| **解決方案** | heartbeat 分析 coverage gap / scope request 後輸出 JSON job，並由 CLI / UI 顯示 pending / done / error 狀態 |
| **影響** | 新增 `scripts/run_heartbeat.py` 與 Streamlit 的 backlog 管理頁；job schema 需穩定且可被外部工具消費 |

### DEC-010: Source 序列化必須保留完整結構

| 項目 | 內容 |
|------|------|
| **決策** | `Question.source` 在 entity / repository / UI 之間一律使用 `Source.to_dict()` / `Source.from_dict()` |
| **問題** | 舊的 page/line flatten 寫法只保留 legacy 欄位，會丟失 `stem_source` / `answer_source` / `explanation_sources` |
| **解決方案** | 移除中途的扁平化轉換，改走完整 Source round-trip |
| **影響** | 題庫精確來源 badge、來源詳情與後續審查 UI 才能正確依據真實來源資料運作 |

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
| 2026-02-13 | 將 Streamlit 底層 Agent 從 Crush 單一綁定改為可插拔 Provider 架構（crush/opencode/copilot-sdk）。 | 降低單點依賴風險，讓 UI 成為可替換包裝層；可依環境與成本切換底層推理引擎，並保留既有 Crush + MCP 工作流相容性。 |
| 2026-05-13 | Miller figure assets 採 page-region crop 優先，不再把 raw XObject 當 primary artifact。 | raw XObject 常缺 PDF text overlays / labels / captions；page crop 可保留圖中文字與圖說。caption matching 以幾何硬 gate 為準，找不到安全配對時寧可空 caption，不做 FIFO 誤綁。 |
| 2026-05-13 | 全量 figure refresh 必須防 zero-figure overwrite 並有 per-fallback timeout。 | Chapter 30 暴露 PyMuPDF fast fallback 可卡住；refresh 不能先刪 images，也不能用 0 figures 覆蓋舊 manifest。全量更新應以 audit gate 驗收，而不是盲目重刷。 |
