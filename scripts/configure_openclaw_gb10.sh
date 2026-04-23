#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
OPENCLAW_BIN="$PROJECT_DIR/scripts/openclaw.sh"

if [[ ! -x "$OPENCLAW_BIN" ]]; then
    echo "找不到 OpenClaw wrapper：$OPENCLAW_BIN" >&2
    echo "請先執行：$PROJECT_DIR/scripts/install_openclaw_local.sh" >&2
    exit 1
fi

GB10_PROVIDER_ID="${OPENCLAW_GB10_PROVIDER_ID:-gb10}"
GB10_BASE_URL="${OPENCLAW_GB10_BASE_URL:-http://192.168.1.145:8081/v1}"
GB10_MODEL_ID="${OPENCLAW_GB10_MODEL_ID:-Qwen3.5-122B-A10B-Q5_K_M-00001-of-00003.gguf}"
GB10_MODEL_NAME="${OPENCLAW_GB10_MODEL_NAME:-GB10 Qwen3.5 122B A10B Q5_K_M 72K in 24K out}"
GB10_CONTEXT_WINDOW="${OPENCLAW_GB10_CONTEXT_WINDOW:-73728}"
GB10_MAX_TOKENS="${OPENCLAW_GB10_MAX_TOKENS:-24576}"
GB10_API_KEY="${OPENCLAW_GB10_API_KEY:-local-gb10-token}"

PROVIDER_JSON="$(cat <<JSON
{
  "baseUrl": "$GB10_BASE_URL",
  "apiKey": "$GB10_API_KEY",
  "api": "openai-completions",
  "request": {
    "allowPrivateNetwork": true
  },
  "models": [
    {
      "id": "$GB10_MODEL_ID",
      "name": "$GB10_MODEL_NAME",
      "api": "openai-completions",
      "contextWindow": $GB10_CONTEXT_WINDOW,
      "maxTokens": $GB10_MAX_TOKENS,
      "input": ["text"]
    }
  ]
}
JSON
)"

"$OPENCLAW_BIN" config set models.mode '"replace"' --strict-json
"$OPENCLAW_BIN" config set "models.providers.${GB10_PROVIDER_ID}" "$PROVIDER_JSON" --strict-json
"$OPENCLAW_BIN" models set "${GB10_PROVIDER_ID}/${GB10_MODEL_ID}"
"$OPENCLAW_BIN" config validate

AGENT_MODELS_CACHE="$PROJECT_DIR/vendor/openclaw-state/agents/main/agent/models.json"
if [[ -f "$AGENT_MODELS_CACHE" ]]; then
    rm -f "$AGENT_MODELS_CACHE"
fi

echo "已設定 OpenClaw 預設模型為：${GB10_PROVIDER_ID}/${GB10_MODEL_ID}"
echo "目前 config 檔案：$("$OPENCLAW_BIN" config file)"
echo "可用檢查：$OPENCLAW_BIN models status --plain"
