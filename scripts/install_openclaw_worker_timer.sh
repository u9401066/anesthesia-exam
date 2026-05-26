#!/usr/bin/env bash
set -euo pipefail

SERVICE_NAME="anesthesia-exam-openclaw-worker.service"
TIMER_NAME="anesthesia-exam-openclaw-worker.timer"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SCOPE="${1:---user}"

if [[ "$INSTALL_SCOPE" != "system" && "$INSTALL_SCOPE" != "--user" ]]; then
    echo "用法: bash scripts/install_openclaw_worker_timer.sh [--user|system]" >&2
    exit 1
fi

if [[ "$INSTALL_SCOPE" == "--user" ]]; then
    TARGET_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
    SYSTEMCTL=(systemctl --user)
    INSTALL_CMD=(install)
    RUN_USER="$(id -un)"
    RUN_GROUP="$(id -gn)"
    USER_MODE=1
else
    TARGET_DIR="/etc/systemd/system"
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

mkdir -p "$TARGET_DIR"

render_unit() {
    local source_unit="$1"
    local target_unit="$2"
    local tmp_unit
    tmp_unit="$(mktemp)"
    if [[ "$USER_MODE" -eq 1 ]]; then
        sed \
            -e '/^User=/d' \
            -e '/^Group=/d' \
            -e 's|WantedBy=multi-user.target|WantedBy=default.target|g' \
            -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
            -e "s|__RUN_USER__|$RUN_USER|g" \
            -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
            "$source_unit" > "$tmp_unit"
    else
        sed \
            -e "s|__PROJECT_DIR__|$PROJECT_DIR|g" \
            -e "s|__RUN_USER__|$RUN_USER|g" \
            -e "s|__RUN_GROUP__|$RUN_GROUP|g" \
            "$source_unit" > "$tmp_unit"
    fi
    "${INSTALL_CMD[@]}" -m 0644 "$tmp_unit" "$target_unit"
    rm -f "$tmp_unit"
}

render_unit "$PROJECT_DIR/deploy/systemd/$SERVICE_NAME" "$TARGET_DIR/$SERVICE_NAME"
render_unit "$PROJECT_DIR/deploy/systemd/$TIMER_NAME" "$TARGET_DIR/$TIMER_NAME"

"${SYSTEMCTL[@]}" daemon-reload
"${SYSTEMCTL[@]}" enable --now "$TIMER_NAME"
"${SYSTEMCTL[@]}" list-timers "$TIMER_NAME" --no-pager
