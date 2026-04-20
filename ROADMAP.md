# Roadmap

專案發展路線圖與功能規劃。

## 已完成 ✅

### 核心基礎
- [x] DDD 分層架構（Domain / Infrastructure / Presentation）
- [x] SQLite 題庫儲存與審計追蹤
- [x] `exam-generator` MCP 基礎工具（CRUD / search / validate / stats）
- [x] `asset-aware-mcp` 文獻解析與精確來源定位整合
- [x] Copilot Prompt Workflows 基礎版（generate / import / explain / manage）

### 品質保證型出題骨架
- [x] `exam_get_generation_guide` 出題指引工具
- [x] `exam_bulk_save` 批次儲存
- [x] Multi-phase pipeline harness 核心工具
- [x] Pipeline run 持久化（可跨對話恢復）
- [x] Phase gate 驗證與 artifacts / metrics 記錄

### Web MVP（已實際驗證）
- [x] 作答練習頁：可從題庫抽題、作答、即時計分、展開詳解與來源
- [x] 生成頁：可指定題數、難度、主題、已索引教材與章節範圍
- [x] ETL UI：已支援 `page_ranges`、大檔分塊頁數與圖像 asset 擷取控制
- [x] 正式來源追蹤 / preview 草稿模式分流，缺少 Marker blocks 會阻擋正式入庫
- [x] 生成後題目審閱與編輯，再儲存到 SQLite 題庫
- [x] 題庫管理頁：支援關鍵字 / 難度 / 主題篩選，並可直接切換成練習
- [x] Systemd 部署資產：已提供啟動腳本、unit 與安裝腳本

## 進行中 🚧

### 1. 考古題萃取與藍圖化
- [ ] 掃描 PDF → OCR / 結構化題目抽取 pipeline
- [ ] 考古題題型分類（知識點 / 題型 / 難度 / 出題套路）
- [ ] 歷年考古題高頻概念趨勢分析
- [ ] 產出 `reference pack / blueprint` 供 Copilot 出題直接參考

### 2. 品質保證型出題閉環
- [ ] 生成候選題 → 驗證 → 入庫 → 人工審閱 的 closed-loop review
- [ ] 題目與考古題相似度檢查，避免變成近似抄題
- [ ] 來源完整度分級與缺漏警告
- [ ] Prompt workflows 全面切換為 pipeline-aware

### 3. Web App / MCP 分離與產品化
- [x] Web App 已具備題庫管理、練習、教材/章節選擇式出題入口
- [ ] Web App 組卷結果持久化為 `exam session / blueprint`
- [ ] MCP pipeline run / phase artifacts 顯示到 Web dashboard
- [ ] 共用 SQLite 與未來 reference pack storage

### 4. Web 需求補完（依 2026-04-14 驗收）
- [x] 題庫新增 `validated_only` 與管理者審查按鈕，使用者可選只用已審查題
- [ ] 將考古題題目納入同一題庫、審查與練習流程
- [x] 建立第一階段 `exam_track` taxonomy（ITE / PGY / clerk / specialist / board / custom）並接上前台篩選
- [ ] 將題型模板庫與 past-exam blueprint 串到 Web 組卷介面
- [x] 建立使用者 `scope request` 提案頁與 backlog
- [x] 建立 file-based heartbeat job emission，依題庫缺口輸出外部 agent 可讀 jobs
- [ ] 補上 heartbeat scheduler / 外部 agent done-error 回寫與管理 UI

### 5. 題目作者工作流（2026-04-15 新增）

#### 第一優先：直接提升出題效率的核心功能
- [ ] 題目草稿箱：生成結果先進草稿區，再進正式題庫
- [ ] 批次編修：可批次修改難度 / 主題 / exam_track / 審查狀態
- [ ] 去重 / 相似題提醒：生成或編修時先比對最相近題目
- [ ] 題目模板：常見題型可一鍵套用骨架

#### 第二優先：直接提升題目品質的功能
- [ ] 出題 blueprint：定義題數、主題占比、難度占比、題型占比後自動補齊
- [ ] 題目 QA checklist：來源、詳解、選項平衡、語氣風險等品質旗標
- [ ] 來源可信度分級：精確來源 / 全文來源 / 無來源草稿
- [ ] 題目版本歷史：可查看修改前版本與差異

#### 第三優先：直接提升日常使用體驗的 UI/UX
- [ ] 全域搜尋列：可搜題目、主題、教材、歷屆考卷
- [ ] 固定工作模式切換：寫題 / 審題 / 組卷 / 練習
- [ ] 題目 detail drawer：列表不跳頁即可看題目詳情
- [ ] 快捷操作列：複製 / 改寫 / 標記待補來源 / 加入考卷 / 送審
- [ ] 常用篩選 preset：待審、本週新增、無精確來源、ITE 題、藥理題

## 計劃中 📋

### 短期目標
- [ ] 題目草稿箱第一版：持久化草稿、批次編修、批次送入正式題庫
- [ ] 去重 / 相似題提醒 MVP（先從題庫近似比對開始）
- [ ] 題目模板與 blueprint 的前台入口整併
- [ ] 建立考古題 concept taxonomy 與關聯表
- [ ] 建立 `past-exam-analyzer` 與 `past-exam-matcher` 的實際工具實作
- [ ] 新增 `exam_generate_from_blueprint` facade tool
- [ ] 新增 pipeline dashboard / run history UI
- [x] 新增 reviewed-only practice / exam mode
- [x] 完成 `scope request` persistence 與管理頁
- [x] 完成題庫 `exam_track` migration
- [ ] 補 audience / origin_type facets 與更完整 taxonomy

### 中期目標
- [ ] 題型模板庫（病例題 / 藥理比較 / 生理機轉 / 圖片題）
- [ ] 題目品質 hooks（distractor quality, blooms level, evidence coverage）
- [ ] past-exam reference pack 自動更新
- [ ] heartbeat scheduler 與自動補題 queue
- [ ] heartbeat job completion / error handling 回寫到 Web 管理頁
- [ ] REST API mode / VS Code extension integration

### 長期目標
- [ ] 自我演化的 exam generation constraints
- [ ] 跨教材 / 跨考古題的知識圖譜出題
- [ ] 多專案 / 多科別題庫隔離與同步
- [ ] 完整 VS Code Extension + Dashboard 統合體驗

## 產品方向

### 主要目標
- 任何通用型 agent 都能透過 MCP 正確出題，而不是憑記憶亂出題。
- 題目必須可追溯到教材或考古題 evidence。
- 考古題不是只拿來存檔，而是要被萃取成「題型藍圖 + 高頻概念 + 出題套路」。

### 目前架構方向
- Web App：題庫管理 / 練習 / 組卷
- Exam MCP：多 phase harness / 出題 / 審計 / quality gates
- Asset-Aware MCP：教材與考古題的 parsing / section / source location

Legend: ✅ Complete | 🚧 In Progress | 📋 Planned
