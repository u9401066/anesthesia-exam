# 智慧考卷生成系統 (Anesthesia Exam Generator)

> AI Agent 驅動的醫學專科考試 Web 工作台

## 功能特色

- 🎯 **教材導向出題** - 可指定已索引教材、章節、題數、難度與主題生成題目
- 📥 **PDF ETL 索引** - Web 直接觸發 `ingest_documents`，支援 `page_ranges`、大檔分塊與圖像擷取
- 🧭 **正式 / preview 來源模式分流** - 缺少 Marker blocks 的文件會阻擋正式入庫，改走 preview 草稿
- ✍️ **線上作答練習** - 從剛生成題組或既有題庫立即開始作答、批改與查看詳解
- 🧠 **考古題詳解補寫** - 可在歷屆題庫頁搜尋缺詳解題，參考 repo 既有題庫脈絡後生成詳解並直接寫回 SQLite
- 📚 **題庫治理** - 支援關鍵字 / 難度 / 主題 / 考試類型 / reviewed-only 篩選
- 📋 **出題需求 backlog** - 使用者可提出補題需求，heartbeat 會把缺口寫成 `data/jobs/*.json`
- 🤖 **多 Agent Provider** - Sidebar 可切換 `crush`、`opencode`、`copilot-sdk`

## 系統架構

```
┌──────────────────┬─────────────────────────────┬────────────────────────────┐
│     Sidebar      │        Main Area            │       Right Panel          │
│  ─ 功能切換      │  ─ 考題作答區               │  ─ Crush 對話區            │
│  ─ 出題設定      │  ─ 對答案/詳解區            │  ─ 即時問答互動            │
└──────────────────┴─────────────────────────────┴────────────────────────────┘
```

### 題目來源

| 來源類型 | 說明 |
| -------- | ---- |
| **Streaming** | Crush Agent 即時流式生成 |
| **Batch** | 題庫批次取得 |

## 技術架構

| 層次 | 技術選型 |
| ---- | -------- |
| Agent | Crush / OpenCode / Copilot SDK（透過 provider abstraction 切換） |
| 前端 UI | Streamlit 工作台（生成 / 練習 / 題庫 / 需求 / 統計） |
| MCP Server | `exam-generator`（13 tools） + `asset-aware-mcp` |
| PDF 解析 | `asset-aware-mcp` + Marker 模式 |
| 持久化 | SQLite + `data/jobs/*.json` heartbeat 工作檔 |
| Python 管理 | uv |

### Skills 架構

```
.claude/skills/
├── 主編排器: exam-orchestrator
├── 知識處理層: knowledge-indexer, scope-analyzer, knowledge-extractor
├── 出題生成層: mcq-generator, essay-generator, question-set-generator, image-question-generator
├── 品質控制層: question-validator, difficulty-classifier, duplicate-checker, source-tracker
├── 考古題層: past-exam-analyzer, past-exam-matcher
├── 輸出層: explanation-generator, exam-assembler, export-formatter
└── 開發工具: git-precommit, code-reviewer, memory-updater, ...
```

## 快速開始

```bash
# 建立虛擬環境
uv venv
uv sync --extra webapp --dev

# 初始化 submodule
git submodule update --init --recursive

# 啟動 Web
./scripts/run_web.sh

# 或使用 Python 入口
uv run python main.py
```

## Systemd 部署

專案已提供 systemd unit 與安裝腳本：

```bash
# 安裝 / 啟用 / 啟動 systemd service
./scripts/install_systemd_service.sh

# unit template 或環境變數更新後，也用同一支腳本刷新並重啟服務
./scripts/install_systemd_service.sh

# 查看狀態
systemctl status anesthesia-exam-web.service --no-pager

# 重新啟動
systemctl restart anesthesia-exam-web.service
```

相關檔案：

- `deploy/systemd/anesthesia-exam-web.service`
- `scripts/install_systemd_service.sh`
- `scripts/run_web.sh`

systemd unit 預設使用 `EXAM_AGENT_PROVIDER=openclaw`、`EXAM_OPENCLAW_MODE=agent` 與 repo-local OpenClaw 設定。第一次部署或重建 OpenClaw 設定後，先執行：

```bash
./scripts/install_openclaw_local.sh
./scripts/configure_openclaw_repo_agent.sh
./scripts/install_systemd_service.sh
```

若部署路徑不是目前 repo 位置，請先調整 unit 內的 `WorkingDirectory`、`ExecStart` 與 `User`。

#### 選用：OpenClaw 背景 worker 與 Telegram 管理服務

除了 Web 服務外，可另外安裝 OpenClaw backlog worker 與 Telegram 管理／狀態回報服務：

```bash
# OpenClaw backlog worker（timer 定時處理待辦，依 job_id 分流 session）
./scripts/install_openclaw_worker_timer.sh

# Telegram 管理 bot 與定時狀態回報
./scripts/install_openclaw_telegram_services.sh
```

相關檔案：

- `deploy/systemd/anesthesia-exam-openclaw-worker.service` / `.timer`
- `deploy/systemd/anesthesia-exam-telegram-bot.service`
- `deploy/systemd/anesthesia-exam-telegram-status.service` / `.timer`
- `scripts/run_openclaw_heartbeat_worker.py`、`scripts/run_telegram_admin_bot.py`、`scripts/run_telegram_status_report.py`

Telegram `/ask` 入口會依 `chat_id` 分流 OpenClaw session；相關環境變數見 `.env.example`（`TELEGRAM_*`、`OPENCLAW_GATEWAY_PUBLIC_URL`）。

### 重要：初始化子模組（asset-aware-mcp）

`asset-aware-mcp` 為 Git submodule，若未初始化會導致 `ingest_documents` 無法使用。

```bash
# 第一次 clone（建議）
git clone --recursive <repo-url>

# 已 clone 專案時
git submodule update --init --recursive
```

## Agent Provider 切換（Crush / OpenCode / Copilot SDK）

Streamlit 現在是 UI 包裝層，底層 Agent 可切換：

- `crush`
- `opencode`（CLI 模式）
- `copilot-sdk`（HTTP API 模式）
- `codex`（OpenAI API 模式，適合聊天頁 / 詳解生成 / 出題工作台）
- `openclaw`（repo-local CLI + MCP agent 模式；systemd 預設）

透過環境變數設定：

```bash
# 選擇 provider
export EXAM_AGENT_PROVIDER=crush

# 可選：Crush 路徑（未設會嘗試用 PATH 的 crush）
export EXAM_CRUSH_PATH=/usr/local/bin/crush

# 可選：OpenCode 命令模板（需包含 {prompt}）
export EXAM_OPENCODE_COMMAND='opencode run "{prompt}"'

# 可選：Copilot SDK API endpoint
export EXAM_COPILOT_SDK_ENDPOINT='http://localhost:8080/generate'
export EXAM_COPILOT_SDK_TOKEN='your-token'

# 可選：Codex / OpenAI API
export EXAM_AGENT_PROVIDER=codex
export EXAM_OPENAI_API_KEY='sk-...'
export EXAM_CODEX_MODEL='gpt-5.3-codex'
# 若未設定，預設會用 https://api.openai.com/v1
export EXAM_OPENAI_BASE_URL='https://api.openai.com/v1'
```

說明：

- `EXAM_AGENT_PROVIDER=opencode` 時，會呼叫 `EXAM_OPENCODE_COMMAND`。
- `EXAM_AGENT_PROVIDER=copilot-sdk` 時，會 POST 到 `EXAM_COPILOT_SDK_ENDPOINT`。
- `EXAM_AGENT_PROVIDER=codex` 時，聊天頁、考古題詳解生成、出題工作台會走 OpenAI API；ETL 仍不支援 Codex。
- Sidebar 會顯示目前固定 provider 與連線狀態。

## Web 工作台頁面

目前 Web 介面包含五個主頁面：

- `📝 生成考題`：教材索引、出題設定、正式/preview 模式分流、生成後審閱
- `✍️ 作答練習`：依難度 / 主題 / 題數抽題、提交後即時計分
- `📚 題庫管理`：搜尋、篩選、審查、從篩選結果切換成練習，並可對歷屆題目補寫詳解
- `📋 出題需求`：提出補題需求、管理 backlog、觸發 heartbeat job emission
- `📊 統計`：查看題庫規模、難度分布與高頻主題

## MCP ETL 流程（PDF → 索引）

在 `📝 生成考題` 頁面已加入 ETL 區塊：

1. 上傳 PDF
2. 輸入教材標題
3. 視需要填入 `頁段範圍（page_ranges）`
4. 視需要調整 `大檔分塊頁數` 與 `擷取圖像 assets`
5. 點擊 `執行 ETL（ingest_documents）`
6. Agent 會呼叫 `asset-aware` 的 `ingest_documents`
7. 成功後可在「參考教材（已索引）」下拉選單看到文件

前提：

- Provider 需支援 MCP 工具呼叫（目前建議使用 `crush` 或 `opencode`；`codex` 不走這條）
- `libs/asset-aware-mcp` 必須有可執行內容（目錄不可為空）
- 若要做正式來源追蹤，請開啟 Marker 模式，讓文件保留 `blocks.json`
- 若是 Miller 教材這類需要可靠 figure extraction 的教材，建議直接使用：
  `uv run python scripts/ingest_miller_chapters.py --high-fidelity-marker ...`
  這會強制走 strict Marker、載入 `configs/asset-aware/miller_marker_hq.json`，並避免靜默退回 PyMuPDF 圖像 fallback。

### Crush Agent 設定

```bash
# 設定 crush.json
{
  "skills_paths": [".claude/skills"],
  "mcpServers": {
    "exam-generator": {
      "command": "uv",
      "args": ["run", "python", "-m", "src.infrastructure.mcp.exam_server"]
    }
  }
}
```

## 大型 PDF 處理

針對大型教材（如 Miller's Anesthesia 9th）：

1. 先用 `頁段範圍` 聚焦需要的章節，而不是一開始就整本 ingest
2. 若使用 Marker，透過 `大檔分塊頁數` 控制每批處理頁數
3. 圖像很多的 PDF 可先關閉 `擷取圖像 assets`，優先保住文字 / blocks
4. 正式來源追蹤依賴 Marker blocks；若文件只有摘要或低品質 OCR，系統會降級成 preview 模式

## 文檔

| 文件 | 說明 |
| ---- | ---- |
| [SPEC.md](SPEC.md) | 完整規格書 |
| [ARCHITECTURE.md](ARCHITECTURE.md) | 架構設計 |
| [CHANGELOG.md](CHANGELOG.md) | 變更記錄 |
| [ROADMAP.md](ROADMAP.md) | 開發路線圖 |
| [CONSTITUTION.md](CONSTITUTION.md) | 專案最高原則 |

## Memory Bank

跨對話的專案記憶系統：

| 文件 | 用途 |
| ---- | ---- |
| `memory-bank/activeContext.md` | 當前工作焦點 |
| `memory-bank/progress.md` | 進度追蹤 |
| `memory-bank/decisionLog.md` | 決策記錄 |

## 授權

MIT License
