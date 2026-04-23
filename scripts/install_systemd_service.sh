#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="anesthesia-exam-web.service"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SOURCE_UNIT="$PROJECT_DIR/deploy/systemd/$SERVICE_NAME"
INSTALL_SCOPE="${1:-system}"

if [[ "$INSTALL_SCOPE" != "system" && "$INSTALL_SCOPE" != "--user" ]]; then
    echo "用法: bash scripts/install_systemd_service.sh [--user]" >&2
    exit 1
fi

if [[ "$INSTALL_SCOPE" == "--user" ]]; then
    TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    TARGET_UNIT="$TARGET_DIR/$SERVICE_NAME"
    SYSTEMCTL=(systemctl --user)
    INSTALL_CMD=(install)
    RUN_USER="$(id -un)"
    RUN_GROUP="$(id -gn)"
    USER_MODE=1
else
    TARGET_UNIT="/etc/systemd/system/$SERVICE_NAME"
    if [[ "${EUID:-$(id -u)}" -eq 0 ]]; then
        SUDO=()
        RUN_USER="${RUN_USER:-${SUDO_USER:-root}}"
    else
        SUDO=(sudo)
        RUN_USER="${RUN_USER:-$(id -un)}"
    fi

    RUN_GROUP="${RUN_GROUP:-$(id -gn "$RUN_USER" 2>/dev/null || id -gn)}"
    SYSTEMCTL=("${SUDO[@]}" systemctl)
    INSTALL_CMD=("${SUDO[@]}" install)
    USER_MODE=0
fi

if [[ ! -f "$SOURCE_UNIT" ]]; then
    echo "找不到 unit 檔案: $SOURCE_UNIT" >&2
    exit 1
fi

if ! command -v systemctl >/dev/null 2>&1; then
    echo "找不到 systemctl，無法安裝 systemd 服務。" >&2
    exit 1
fi

TARGET_DIR="$(dirname "$TARGET_UNIT")"
if [[ "$USER_MODE" -eq 1 ]]; then
    mkdir -p "$TARGET_DIR"
else
    "${SUDO[@]}" mkdir -p "$TARGET_DIR"
fi

TMP_UNIT="$(mktemp)"
trap 'rm -f "$TMP_UNIT"' EXIT

if [[ "$USER_MODE" -eq 1 ]]; then
    sed \
        -e '/^User=/d' \
        -e '/^Group=/d' \
        -e 's|WantedBy=multi-user.target|WantedBy=default.target|g' \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__RUN_USER__|$RUN_USER|g" \
        -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
        "$SOURCE_UNIT" > "$TMP_UNIT"
else
    sed \
        -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
        -e "s|__RUN_USER__|$RUN_USER|g" \
        -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
        "$SOURCE_UNIT" > "$TMP_UNIT"
fi

"${INSTALL_CMD[@]}" -m 0644 "$TMP_UNIT" "$TARGET_UNIT"

if command -v systemd-analyze >/dev/null 2>&1; then
    if ! systemd-analyze verify "$TMP_UNIT"; then
        echo "警告: systemd-analyze verify 失敗，略過驗證並繼續安裝。" >&2
    fi
fi

"${SYSTEMCTL[@]}" daemon-reload
"${SYSTEMCTL[@]}" enable --now "$SERVICE_NAME"
"${SYSTEMCTL[@]}" status "$SERVICE_NAME" --no-pager