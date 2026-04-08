#!/bin/sh

set -eu

PACKAGE_SPEC=${SSM_TUNNEL_PACKAGE_SPEC:-ssm-tunnel-manager}
TMP_LOG=""

cleanup() {
    if [ -n "$TMP_LOG" ] && [ -f "$TMP_LOG" ]; then
        rm -f "$TMP_LOG"
    fi
}

require_command() {
    if ! command -v "$1" >/dev/null 2>&1; then
        printf "Install error: required command '%s' is not available in PATH.\n" "$1" >&2
        exit 1
    fi
}

print_log() {
    if [ -z "$TMP_LOG" ] || [ ! -f "$TMP_LOG" ]; then
        return
    fi

    while IFS= read -r line; do
        printf '%s\n' "$line" >&2
    done <"$TMP_LOG"
}

run_step() {
    step_name=$1
    shift

    : >"$TMP_LOG"
    if "$@" >"$TMP_LOG" 2>&1; then
        return 0
    fi

    printf 'Install error: %s failed.\n' "$step_name" >&2
    print_log
    exit 1
}

for command_name in sh uname mktemp chmod rm; do
    require_command "$command_name"
done

if [ -z "$PACKAGE_SPEC" ]; then
    printf 'Install error: package spec cannot be empty.\n' >&2
    exit 1
fi

if ! command -v uv >/dev/null 2>&1; then
    printf "Install error: 'uv' is required in PATH to install ssm-tunnel-manager.\n" >&2
    exit 1
fi

uname >/dev/null 2>&1

TMP_LOG=$(mktemp "${TMPDIR:-/tmp}/ssm-tunnel-install.XXXXXX")
chmod 600 "$TMP_LOG"
trap cleanup EXIT HUP INT TERM

if command -v ssm-tunnel >/dev/null 2>&1; then
    run_step "uv tool install --reinstall $PACKAGE_SPEC" \
        uv tool install --reinstall "$PACKAGE_SPEC"
else
    run_step "uv tool install $PACKAGE_SPEC" \
        uv tool install "$PACKAGE_SPEC"
fi

if ! command -v ssm-tunnel >/dev/null 2>&1; then
    printf "Install error: 'ssm-tunnel' is still not available after uv install.\n" >&2
    exit 1
fi

run_step "ssm-tunnel install" env SSM_TUNNEL_SKIP_SELF_INSTALL=1 ssm-tunnel install
