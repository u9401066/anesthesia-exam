#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="anesthesia-exam-web.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_UNIT="$PROJECT_DIR/deploy/systemd/$SERVICE_NAME"
TARGET_UNIT="/etc/systemd/system/$SERVICE_NAME"

if [[ ! -f "$SOURCE_UNIT" ]]; then
    echo "找不到 unit 檔案: $SOURCE_UNIT" >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "找不到 systemctl，無法安裝 systemd 服務。" >&2
    exit 1
fi

install -m 0644 "$SOURCE_UNIT" "$TARGET_UNIT"

if command -v systemd-analyze >/dev/null 2>&1; then
    systemd-analyze verify "$TARGET_UNIT"
fi

systemctl daemon-reload
systemctl enable --now "$SERVICE_NAME"
systemctl status "$SERVICE_NAME" --no-pager