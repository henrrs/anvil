#!/usr/bin/env bash

set -Eeuo pipefail

ANVIL_ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/../.." && pwd -P)"
# shellcheck source=paths.sh
source "$ANVIL_ROOT/scripts/lib/paths.sh"

anvil_log() { printf 'INFO  %s\n' "$*" >&2; }
anvil_warn() { printf 'WARN  %s\n' "$*" >&2; }
anvil_error() { printf 'ERROR %s\n' "$*" >&2; }
anvil_ok() { printf 'OK    %s\n' "$*" >&2; }

anvil_need() {
  local cmd
  for cmd in "$@"; do
    if ! command -v "$cmd" >/dev/null 2>&1; then
      anvil_error "Required command not found: $cmd"
      return 1
    fi
  done
}

anvil_sha256() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum -- "$1" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    shasum -a 256 -- "$1" | awk '{print $1}'
  else
    anvil_error 'Need sha256sum or shasum to verify backups.'
    return 1
  fi
}

anvil_safe_managed_path() {
  local candidate="$1" expected="$2" canonical
  [[ -n "$candidate" && -n "$expected" ]] || return 1
  [[ "$candidate" == "$expected" ]] || return 1
  [[ "$candidate" != / && "$candidate" != "$ANVIL_HOME_DIR" ]] || return 1
  [[ "$(dirname -- "$candidate")" != / ]] || return 1
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$candidate")"
  [[ "$canonical" == "$expected" ]] || return 1
  [[ "$(basename -- "$candidate")" == opencode ]] || return 1
}

anvil_remove_managed_tree() {
  local candidate="$1" expected="$2"
  if ! anvil_safe_managed_path "$candidate" "$expected"; then
    anvil_error "Refusing to remove a path outside the validated OpenCode roots: $candidate"
    return 1
  fi
  if [[ -L "$candidate" || -f "$candidate" ]]; then
    rm -f -- "$candidate"
  elif [[ -d "$candidate" ]]; then
    rm -rf -- "$candidate"
  fi
}

anvil_open_code_binary() {
  if command -v opencode >/dev/null 2>&1; then
    command -v opencode
  elif [[ -x "$ANVIL_INSTALLED_BINARY" ]]; then
    printf '%s\n' "$ANVIL_INSTALLED_BINARY"
  fi
}

anvil_open_code_version() {
  local bin
  bin="$(anvil_open_code_binary || true)"
  if [[ -n "$bin" && -x "$bin" ]]; then
    "$bin" --version 2>/dev/null | head -n 1 || true
  fi
}
