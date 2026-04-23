#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VENDOR_DIR="$PROJECT_DIR/vendor"
OPENCLAW_HOME="$VENDOR_DIR/openclaw-runtime"
OPENCLAW_STATE_DIR="$VENDOR_DIR/openclaw-state"

NODE_VERSION="${OPENCLAW_NODE_VERSION:-v24.15.0}"
NODE_DIST_BASENAME=""

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

NODE_ARCHIVE="${NODE_DIST_BASENAME}.tar.xz"
NODE_DOWNLOAD_BASE="https://nodejs.org/download/release/latest-krypton"
NODE_ARCHIVE_URL="${NODE_DOWNLOAD_BASE}/${NODE_ARCHIVE}"
NODE_SHASUMS_URL="${NODE_DOWNLOAD_BASE}/SHASUMS256.txt"
NODE_INSTALL_DIR="$VENDOR_DIR/$NODE_DIST_BASENAME"
NODE_BIN="$NODE_INSTALL_DIR/bin/node"
NPM_BIN="$NODE_INSTALL_DIR/bin/npm"
OPENCLAW_BIN="$OPENCLAW_HOME/node_modules/.bin/openclaw"

mkdir -p "$VENDOR_DIR"

if [[ ! -x "$NODE_BIN" ]]; then
    TMP_DIR="$(mktemp -d)"
    trap 'rm -rf "$TMP_DIR"' EXIT

    echo "下載本地 Node.js runtime: $NODE_ARCHIVE"
    curl -fsSL "$NODE_ARCHIVE_URL" -o "$TMP_DIR/$NODE_ARCHIVE"
    curl -fsSL "$NODE_SHASUMS_URL" -o "$TMP_DIR/SHASUMS256.txt"

    (
        cd "$TMP_DIR"
        grep " ${NODE_ARCHIVE}\$" SHASUMS256.txt | sha256sum -c -
    )

    rm -rf "$NODE_INSTALL_DIR"
    mkdir -p "$NODE_INSTALL_DIR"
    tar -xJf "$TMP_DIR/$NODE_ARCHIVE" -C "$VENDOR_DIR"

    if [[ ! -x "$NODE_BIN" ]]; then
        echo "Node.js 解壓後找不到可執行檔：$NODE_BIN" >&2
        exit 1
    fi
fi

mkdir -p "$OPENCLAW_HOME"
mkdir -p "$OPENCLAW_STATE_DIR"
if [[ ! -f "$OPENCLAW_HOME/package.json" ]]; then
    cat > "$OPENCLAW_HOME/package.json" <<'JSON'
{
  "name": "anesthesia-exam-openclaw-runtime",
  "private": true,
  "description": "Local OpenClaw runtime for anesthesia-exam",
  "license": "UNLICENSED"
}
JSON
fi

echo "使用本地 Node: $("$NODE_BIN" -v)"
echo "安裝 / 更新 repo 內 OpenClaw..."
export PATH="$NODE_INSTALL_DIR/bin:$PATH"
"$NPM_BIN" install --prefix "$OPENCLAW_HOME" openclaw@latest

if [[ ! -x "$OPENCLAW_BIN" ]]; then
    echo "OpenClaw 安裝完成但找不到執行檔：$OPENCLAW_BIN" >&2
    exit 1
fi

echo "OpenClaw 已安裝到：$OPENCLAW_HOME"
echo "OpenClaw state 目錄：$OPENCLAW_STATE_DIR"
echo "可用指令：$PROJECT_DIR/scripts/openclaw.sh --help"
