#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

usage() {
  cat <<'EOF'
Internal OpenCode release helper:
  install-opencode.sh resolve
  install-opencode.sh stage VERSION DIRECTORY
  install-opencode.sh install CANDIDATE_BINARY VERSION
EOF
}

candidate_version() {
  local value="$1"
  value="${value#opencode }"
  value="${value#v}"
  printf '%s\n' "$value"
}

isolated_version() {
  local binary="$1" check_root output status
  check_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-version-check.XXXXXX")"
  chmod 700 -- "$check_root"
  mkdir -p -- "$check_root/home" "$check_root/config" "$check_root/data" "$check_root/state"
  status=0
  output="$(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$check_root/home" \
    XDG_CONFIG_HOME="$check_root/config" XDG_DATA_HOME="$check_root/data" \
    XDG_STATE_HOME="$check_root/state" "$binary" --version 2>/dev/null | head -n 1)" || status=$?
  python3 - "$check_root" "${TMPDIR:-/tmp}" <<'PY'
import os,shutil,sys
root,base=map(os.path.abspath,sys.argv[1:])
if os.path.commonpath((root,base)) == base and root != base:
    shutil.rmtree(root,ignore_errors=True)
PY
  (( status == 0 )) || return "$status"
  printf '%s\n' "$output"
}

case "${1:-}" in
  resolve)
    anvil_need python3
    python3 "$ROOT/scripts/opencode_release.py" resolve
    ;;
  stage)
    [[ $# -eq 3 ]] || { usage >&2; exit 2; }
    anvil_need python3 tar
    version="$(candidate_version "$2")"
    stage_dir="$3"
    [[ -n "$stage_dir" && "$stage_dir" != / ]] || { anvil_error 'Invalid staging directory.'; exit 2; }
    mkdir -p -- "$stage_dir"
    archive="$stage_dir/opencode-${version}.tgz"
    python3 "$ROOT/scripts/opencode_release.py" download --version "$version" --destination "$archive" > "$stage_dir/release.json"
    tar -xzf "$archive" -C "$stage_dir" package/bin/opencode
    [[ -f "$stage_dir/package/bin/opencode" ]] || {
      anvil_error 'Official npm package did not contain package/bin/opencode.'
      exit 1
    }
    mv -- "$stage_dir/package/bin/opencode" "$stage_dir/opencode"
    rm -rf -- "$stage_dir/package"
    chmod 755 -- "$stage_dir/opencode"
    candidate="$stage_dir/opencode"
    [[ -f "$candidate" && -x "$candidate" ]] || {
      anvil_error 'Official release archive did not contain an executable named opencode.'
      exit 1
    }
    actual="$(candidate_version "$(isolated_version "$candidate")")"
    [[ "$actual" == "$version" ]] || {
      anvil_error "Candidate reports version $actual; expected $version."
      exit 1
    }
    printf '%s\n' "$candidate"
    ;;
  install)
    [[ $# -eq 3 ]] || { usage >&2; exit 2; }
    candidate="$2"
    version="$(candidate_version "$3")"
    [[ -f "$candidate" && -x "$candidate" ]] || { anvil_error 'Validated candidate binary is unavailable.'; exit 1; }
    actual="$(candidate_version "$(isolated_version "$candidate")")"
    [[ "$actual" == "$version" ]] || { anvil_error "Refusing to install $actual; validated release was $version."; exit 1; }
    mkdir -p -- "$ANVIL_INSTALL_BIN"
    tmp="$ANVIL_INSTALL_BIN/.opencode.anvil.$$"
    trap 'rm -f -- "${tmp:-}"' EXIT
    install -m 0755 -- "$candidate" "$tmp"
    mv -f -- "$tmp" "$ANVIL_INSTALLED_BINARY"
    trap - EXIT
    [[ "$(candidate_version "$(isolated_version "$ANVIL_INSTALLED_BINARY")")" == "$version" ]] || {
      anvil_error 'Installed executable did not retain the validated version.'
      exit 1
    }
    anvil_ok "Installed OpenCode $version at $ANVIL_INSTALLED_BINARY"
    ;;
  -h|--help|help)
    usage
    ;;
  *)
    usage >&2
    exit 2
    ;;
esac
