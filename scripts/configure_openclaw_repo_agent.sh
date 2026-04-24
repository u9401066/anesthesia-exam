#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_BIN="$PROJECT_DIR/scripts/openclaw.sh"
MODEL_SETUP_SCRIPT="$PROJECT_DIR/scripts/configure_openclaw_gb10.sh"
WORKSPACE_DIR="${OPENCLAW_WORKSPACE_DIR:-$PROJECT_DIR}"
DATA_DIR="${OPENCLAW_ASSET_AWARE_DATA_DIR:-$PROJECT_DIR/data}"
ENABLE_LIGHTRAG="${OPENCLAW_ASSET_AWARE_ENABLE_LIGHTRAG:-false}"
ETL_PROFILE_JSON="${OPENCLAW_ASSET_AWARE_ETL_PROFILE_JSON:-$PROJECT_DIR/configs/asset-aware/miller_marker_hq.json}"

if [[ ! -x "$OPENCLAW_BIN" ]]; then
    echo "找不到 OpenClaw wrapper：$OPENCLAW_BIN" >&2
    echo "請先執行：$PROJECT_DIR/scripts/install_openclaw_local.sh" >&2
    exit 1
fi

if [[ -x "$MODEL_SETUP_SCRIPT" ]]; then
    "$MODEL_SETUP_SCRIPT" >/dev/null
fi

EXPECTED_SKILLS_TARGET="$(realpath "$PROJECT_DIR/.claude/skills")"
SKILLS_LINK="$PROJECT_DIR/skills"
if [[ -L "$SKILLS_LINK" ]]; then
    ln -sfn .claude/skills "$SKILLS_LINK"
elif [[ ! -e "$SKILLS_LINK" ]]; then
    ln -s .claude/skills "$SKILLS_LINK"
elif [[ "$(realpath "$SKILLS_LINK")" != "$EXPECTED_SKILLS_TARGET" ]]; then
    echo "已存在 skills 路徑且不是 repo 的 .claude/skills：$SKILLS_LINK" >&2
    exit 1
fi

EXAM_GENERATOR_JSON="$(cat <<JSON
{
  "name": "exam-generator",
  "command": "uv",
  "args": ["run", "python", "-m", "src.infrastructure.mcp.exam_server"],
  "cwd": "$PROJECT_DIR"
}
JSON
)"

ASSET_AWARE_JSON="$(cat <<JSON
{
  "name": "asset-aware",
  "command": "uv",
  "args": ["--directory", "libs/asset-aware-mcp", "run", "python", "-m", "src.presentation.server"],
  "cwd": "$PROJECT_DIR",
  "env": {
    "DATA_DIR": "$DATA_DIR",
    "ENABLE_LIGHTRAG": "$ENABLE_LIGHTRAG",
    "ETL_PROFILE_JSON": "$ETL_PROFILE_JSON"
  }
}
JSON
)"

"$OPENCLAW_BIN" config set agents.defaults.workspace "\"$WORKSPACE_DIR\"" --strict-json
"$OPENCLAW_BIN" mcp set exam-generator "$EXAM_GENERATOR_JSON"
"$OPENCLAW_BIN" mcp set asset-aware "$ASSET_AWARE_JSON"
"$OPENCLAW_BIN" config validate

echo "已設定 OpenClaw repo agent workspace：$WORKSPACE_DIR"
echo "已註冊 MCP servers：exam-generator, asset-aware"
echo "目前 workspace：$("$OPENCLAW_BIN" config get agents.defaults.workspace)"
"$OPENCLAW_BIN" mcp list