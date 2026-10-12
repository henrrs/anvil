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

candidate_version() { printf '%s\n' "${1#v}"; }

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
    archive_name="$(python3 -c 'import sys; sys.path.insert(0,sys.argv[1]); import opencode_release; print(opencode_release.asset_name())' "$ROOT/scripts")"
    archive="$stage_dir/$archive_name"
    python3 "$ROOT/scripts/opencode_release.py" download --version "$version" --destination "$archive" > "$stage_dir/release.json"
    case "$archive" in
      *.tar.gz) tar -xzf "$archive" -C "$stage_dir" ;;
      *.zip) anvil_need unzip; unzip -q "$archive" -d "$stage_dir" ;;
      *) anvil_error "Unsupported candidate archive: $archive"; exit 1 ;;
    esac
    candidate="$stage_dir/opencode"
    [[ -f "$candidate" && -x "$candidate" ]] || {
      anvil_error 'Official release archive did not contain an executable named opencode.'
      exit 1
    }
    actual="$(candidate_version "$("$candidate" --version 2>/dev/null | head -n 1)")"
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
    actual="$(candidate_version "$("$candidate" --version 2>/dev/null | head -n 1)")"
    [[ "$actual" == "$version" ]] || { anvil_error "Refusing to install $actual; validated release was $version."; exit 1; }
    mkdir -p -- "$ANVIL_INSTALL_BIN"
    tmp="$ANVIL_INSTALL_BIN/.opencode.anvil.$$"
    trap 'rm -f -- "${tmp:-}"' EXIT
    install -m 0755 -- "$candidate" "$tmp"
    mv -f -- "$tmp" "$ANVIL_INSTALLED_BINARY"
    trap - EXIT
    [[ "$(candidate_version "$("$ANVIL_INSTALLED_BINARY" --version 2>/dev/null | head -n 1)")" == "$version" ]] || {
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
