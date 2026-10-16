#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

binary="$(anvil_open_code_binary || true)"
version="unknown"
method="not detected"
if [[ -n "$binary" && -x "$binary" ]]; then
  version="$("$binary" --version 2>/dev/null | head -n 1 || printf 'unknown')"
  case "$binary" in
    "$ANVIL_INSTALL_BIN"/*) method='official OpenCode installer directory' ;;
    *Homebrew*|*/Cellar/*|*/homebrew/*) method='Homebrew-managed path' ;;
    /usr/bin/*|/bin/*) method='system package or administrator-managed path' ;;
    *) method='custom/user-managed path' ;;
  esac
fi

printf '%s\n' 'Anvil Inspect (read-only)' '────────────────────────'
printf 'OpenCode binary        %s\n' "${binary:-not found}"
printf 'OpenCode version       %s\n' "$version"
printf 'Installation method    %s\n' "$method"
printf 'Global config          %s\n' "$ANVIL_CONFIG_DIR"
printf 'CLI config             %s\n' "$ANVIL_CLI_CONFIG"
printf 'Data directory         %s\n' "$ANVIL_DATA_HOME/opencode"
printf 'State directory        %s\n' "$ANVIL_STATE_DIR"
printf '\n'
python3 "$ROOT/scripts/inspect_data.py" \
  --home "$ANVIL_HOME_DIR" --config "$ANVIL_CONFIG_DIR" \
  --data "$ANVIL_DATA_HOME" --state "$ANVIL_STATE_HOME" --cwd "$PWD"
