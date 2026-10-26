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
  python3 "$ANVIL_ROOT/scripts/runtime_state.py" discover --format path 2>/dev/null || true
}

anvil_open_code_version() {
  local bin
  bin="$(anvil_open_code_binary || true)"
  if [[ -n "$bin" && -x "$bin" ]]; then
    "$bin" --version 2>/dev/null | head -n 1 || true
  fi
}

anvil_runtime_json() {
  python3 "$ANVIL_ROOT/scripts/runtime_state.py" discover --format json
}

anvil_runtime_record() {
  python3 "$ANVIL_ROOT/scripts/runtime_state.py" record --format json
}

anvil_lifecycle_state() {
  python3 "$ANVIL_ROOT/scripts/lifecycle_state.py" "$@"
}

anvil_require_installed() {
  anvil_lifecycle_state require-installed
}

anvil_recover_pending() {
  if [[ "${ANVIL_SKIP_PENDING_RECOVERY:-0}" == 1 ]]; then return 0; fi
  local transaction pending valid backup backup_valid error
  transaction="$(python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" inspect)" || return 1
  local -a fields=()
  mapfile -d '' -t fields < <(python3 - "$transaction" <<'PY'
import json,sys
obj=json.loads(sys.argv[1])
for key in ("pending","valid","backup","backup_valid","backup_error"):
    value=obj.get(key)
    sys.stdout.buffer.write((str(value) if value is not None else "").encode()+b"\0")
PY
)
  pending="${fields[0]:-}"; valid="${fields[1]:-}"; backup="${fields[2]:-}"
  backup_valid="${fields[3]:-}"; error="${fields[4]:-}"
  [[ "$pending" == True ]] || return 0
  local owner_active
  owner_active="$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("owner_active",False))' "$transaction")"
  if [[ "$owner_active" == True ]]; then
    anvil_error 'Another Anvil lifecycle command is still running. Wait for it to finish before retrying.'
    return 1
  fi
  if [[ -L "$ANVIL_CONFIG_DIR" || -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]]; then
    anvil_error 'A managed config or installer path became a symlink after interruption. Automatic recovery stopped for manual review.'
    return 1
  fi
  if [[ "${DRY_RUN:-0}" == 1 ]]; then
    anvil_error 'A lifecycle recovery is pending; DRY_RUN is read-only and did not restore the snapshot. Rerun the operation without DRY_RUN to recover safely.'
    return 1
  fi
  anvil_warn 'An interrupted Anvil lifecycle transaction was found; attempting snapshot recovery before continuing.'
  if [[ "$valid" != True || "$backup_valid" != True || -z "$backup" ]]; then
    anvil_error "Automatic recovery is unavailable: ${error:-the transaction journal or snapshot is invalid}. Preserve the current state and inspect the lifecycle journal and backups."
    return 1
  fi
  if ! python3 "$ANVIL_ROOT/scripts/active-opencode.py"; then
    anvil_error 'Close OpenCode before retrying; recovery needs exclusive access to its configured data paths.'
    return 1
  fi
  if ! ANVIL_INTERNAL_MODE=1 ANVIL_SKIP_PENDING_RECOVERY=1 \
      bash "$ANVIL_ROOT/scripts/rollback.sh" --backup "$backup" --internal; then
    anvil_error "Snapshot recovery failed. The transaction journal remains for a safe retry; verified snapshot: $backup"
    return 1
  fi
  python3 - "$ANVIL_CONFIG_DIR" <<'PY'
import shutil,sys
from pathlib import Path
root=Path(sys.argv[1])
for prefix in (".anvil-config-stage.", ".anvil-config-previous-"):
    for path in root.parent.glob(prefix+"*"):
        if path.is_dir() and not path.is_symlink():
            shutil.rmtree(path)
PY
  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" clear || return 1
  anvil_ok "Interrupted operation recovered from $backup."
  export ANVIL_RECOVERED_PENDING=1
}
