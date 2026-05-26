# HEARTBEAT.md

OpenClaw heartbeat worker 的任務說明。

## Schedule

- systemd timer: `anesthesia-exam-openclaw-worker.timer`
- default cadence: boot 後 5 分鐘開始，之後每 15 分鐘執行一次
- worker command: `scripts/run_openclaw_heartbeat_worker.py --max-jobs 1 --heartbeat-max-requests 5`

## Duties

- 掃描出題需求與 coverage gaps。
- 將缺口寫成 `data/jobs/heartbeat_*.json`。
- 消費 pending heartbeat jobs。
- 有 `source_request_id` 的 job 交給 `ScopeRequestDispatchService`，由 OpenClaw 使用 repo MCP 完成補題。
- 沒有 `source_request_id` 的 auto coverage job 預設只保留為 backlog，不自動派工；需要手動加 `--process-auto-coverage` 才會讓 OpenClaw 處理。

## Safety Rules

- 每輪預設只處理 1 個 pending job。
- 正式教材出題必須使用 `asset-aware__consult_knowledge_graph`、`asset-aware__search_source_location`、`exam-generator__exam_save_question`。
- 若來源查不到或 evidence pack 不完整，標記 job error 或回報 blocked，不可正式入庫。
- 不刪除 job 檔；完成只標記 `done`，失敗只標記 `error`。

## Manual Commands

```bash
# 查看但不派工
.venv/bin/python scripts/run_openclaw_heartbeat_worker.py --dry-run

# 只處理有 source_request_id 的既有 pending jobs，不新增 heartbeat jobs
.venv/bin/python scripts/run_openclaw_heartbeat_worker.py --no-generate-jobs --max-jobs 1

# 手動允許處理 auto coverage job
.venv/bin/python scripts/run_openclaw_heartbeat_worker.py --no-generate-jobs --max-jobs 1 --process-auto-coverage

# 安裝 user-level timer
bash scripts/install_openclaw_worker_timer.sh --user
```
