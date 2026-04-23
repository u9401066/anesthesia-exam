#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
NODE_VERSION="${OPENCLAW_NODE_VERSION:-v24.15.0}"

case "$(uname -s)-$(uname -m)" in
    Linux-x86_64)
        NODE_DIST_BASENAME="node-${NODE_VERSION}-linux-x64"
        ;;
    Linux-aarch64 | Linux-arm64)
        NODE_DIST_BASENAME="node-${NODE_VERSION}-linux-arm64"
        ;;
    Darwin-arm64)
        NODE_DIST_BASENAME="node-${NODE_VERSION}-darwin-arm64"
        ;;
    Darwin-x86_64)
        NODE_DIST_BASENAME="node-${NODE_VERSION}-darwin-x64"
        ;;
    *)
        echo "目前腳本尚未支援此平台：$(uname -s)-$(uname -m)" >&2
        exit 1
        ;;
esac

NODE_BIN="$PROJECT_DIR/vendor/$NODE_DIST_BASENAME/bin/node"
OPENCLAW_BIN="$PROJECT_DIR/vendor/openclaw-runtime/node_modules/.bin/openclaw"
OPENCLAW_STATE_DIR="${OPENCLAW_STATE_DIR:-$PROJECT_DIR/vendor/openclaw-state}"
OPENCLAW_CONFIG_PATH="${OPENCLAW_CONFIG_PATH:-$OPENCLAW_STATE_DIR/openclaw.json}"

if [[ ! -x "$NODE_BIN" || ! -x "$OPENCLAW_BIN" ]]; then
    echo "尚未在 repo 內安裝 OpenClaw。" >&2
    echo "請先執行：$PROJECT_DIR/scripts/install_openclaw_local.sh" >&2
    exit 1
fi

mkdir -p "$OPENCLAW_STATE_DIR"
export PATH="$(dirname "$NODE_BIN"):$PROJECT_DIR/vendor/openclaw-runtime/node_modules/.bin:$PATH"
export OPENCLAW_STATE_DIR
export OPENCLAW_CONFIG_PATH
exec "$OPENCLAW_BIN" "$@"
