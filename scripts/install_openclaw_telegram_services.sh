#!/usr/bin/env bash
set -euo pipefail

BOT_SERVICE_NAME="anesthesia-exam-telegram-bot.service"
STATUS_SERVICE_NAME="anesthesia-exam-telegram-status.service"
STATUS_TIMER_NAME="anesthesia-exam-telegram-status.timer"
PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
INSTALL_SCOPE="${1:---user}"

if [[ "$INSTALL_SCOPE" != "system" && "$INSTALL_SCOPE" != "--user" ]]; then
    echo "用法: bash scripts/install_openclaw_telegram_services.sh [--user|system]" >&2
    exit 1
fi

env_has_value() {
    local key="$1"
    if [[ -n "${!key:-}" ]]; then
        return 0
    fi
    [[ -f "$PROJECT_DIR/.env" ]] && grep -Eq "^[[:space:]]*(export[[:space:]]+)?${key}[[:space:]]*=[[:space:]]*[^#[:space:]]+" "$PROJECT_DIR/.env"
}

telegram_enabled() {
    if [[ "${TELEGRAM_ENABLED:-}" =~ ^(1|true|yes|on)$ ]]; then
        return 0
    fi
    [[ -f "$PROJECT_DIR/.env" ]] && grep -Eiq "^[[:space:]]*(export[[:space:]]+)?TELEGRAM_ENABLED[[:space:]]*=[[:space:]]*['\"]?(1|true|yes|on)['\"]?([[:space:]]*(#.*)?)?$" "$PROJECT_DIR/.env"
}

telegram_configured() {
    telegram_enabled && env_has_value TELEGRAM_BOT_TOKEN && env_has_value TELEGRAM_ADMIN_CHAT_IDS
}

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

render_unit "$PROJECT_DIR/deploy/systemd/$BOT_SERVICE_NAME" "$TARGET_DIR/$BOT_SERVICE_NAME"
render_unit "$PROJECT_DIR/deploy/systemd/$STATUS_SERVICE_NAME" "$TARGET_DIR/$STATUS_SERVICE_NAME"
render_unit "$PROJECT_DIR/deploy/systemd/$STATUS_TIMER_NAME" "$TARGET_DIR/$STATUS_TIMER_NAME"

"${SYSTEMCTL[@]}" daemon-reload

if telegram_configured; then
    "${SYSTEMCTL[@]}" enable --now "$BOT_SERVICE_NAME"
    "${SYSTEMCTL[@]}" enable --now "$STATUS_TIMER_NAME"
    "${SYSTEMCTL[@]}" status "$BOT_SERVICE_NAME" --no-pager || true
    "${SYSTEMCTL[@]}" list-timers "$STATUS_TIMER_NAME" --no-pager
else
    echo "Telegram units installed to $TARGET_DIR but not enabled."
    echo "Set TELEGRAM_ENABLED=true, TELEGRAM_BOT_TOKEN, and TELEGRAM_ADMIN_CHAT_IDS in .env, then rerun this installer."
fi
