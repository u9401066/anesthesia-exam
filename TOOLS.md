# TOOLS.md

## 本 repo 常用命令

- Python / 測試：uv run ...
- OpenClaw wrapper：scripts/openclaw.sh
- OpenClaw repo bootstrap：scripts/configure_openclaw_repo_agent.sh

## Repo-local agent stack

- 工作目錄：repo root
- skills：skills -> .claude/skills
- 題庫 MCP：uv run python -m src.infrastructure.mcp.exam_server
- asset-aware MCP：uv --directory libs/asset-aware-mcp run python -m src.presentation.server

## 重要資料

- 題庫資料：data/
- 上傳教材：data/sources/uploads/
- ETL profile：configs/asset-aware/miller_marker_hq.json
- Log：logs/