#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-$PROJECT_DIR/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
    echo "找不到可執行的 Python: $PYTHON_BIN" >&2
    echo "請先在專案根目錄執行: uv sync --extra webapp --dev" >&2
    exit 1
fi

cd "$PROJECT_DIR"

exec "$PYTHON_BIN" -m streamlit run src/presentation/streamlit/app.py \
    --server.port "${STREAMLIT_SERVER_PORT:-8501}" \
    --server.address "${STREAMLIT_SERVER_ADDRESS:-0.0.0.0}" \
    --server.headless=true \
    "$@"
