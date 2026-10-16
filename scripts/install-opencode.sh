#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

usage() {
  cat <<'EOF'
Internal OpenCode release helper:
  install-opencode.sh resolve [MAJOR]
  install-opencode.sh stage VERSION DIRECTORY [MAJOR]
  install-opencode.sh install CANDIDATE_BINARY VERSION [MAJOR]
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
    major="${2:-$(python3 "$ROOT/scripts/runtime.py" policy | python3 -c 'import json,sys; print(json.load(sys.stdin)["opencode"]["default_major"])')}"
    case "$major" in
      1) python3 "$ROOT/scripts/opencode_v1_release.py" resolve ;;
      2) python3 "$ROOT/scripts/opencode_release.py" resolve ;;
      *) anvil_error "Unsupported OpenCode runtime major: $major"; exit 2 ;;
    esac
    ;;
  stage)
    [[ $# -ge 3 && $# -le 4 ]] || { usage >&2; exit 2; }
    anvil_need python3 tar
    version="$(candidate_version "$2")"
    stage_dir="$3"
    major="${4:-${version%%.*}}"
    [[ "${version%%.*}" == "$major" ]] || { anvil_error "OpenCode $version does not belong to requested major $major."; exit 2; }
    [[ -n "$stage_dir" && "$stage_dir" != / ]] || { anvil_error 'Invalid staging directory.'; exit 2; }
    mkdir -p -- "$stage_dir"
    case "$major" in
      1)
        archive="$stage_dir/opencode-${version}.archive"
        python3 "$ROOT/scripts/opencode_v1_release.py" download --version "$version" --destination "$archive" > "$stage_dir/release.json"
        python3 - "$archive" "$stage_dir/opencode" <<'PY'
import os,sys,tarfile,zipfile
from pathlib import Path
archive,target=map(Path,sys.argv[1:])
if zipfile.is_zipfile(archive):
    with zipfile.ZipFile(archive) as package:
        candidates=[item for item in package.infolist() if not item.is_dir() and Path(item.filename).name in {"opencode","opencode.exe"}]
        if len(candidates)!=1: raise SystemExit("official OpenCode 1 archive must contain one opencode executable")
        data=package.read(candidates[0])
else:
    with tarfile.open(archive,"r:*") as package:
        candidates=[item for item in package.getmembers() if item.isfile() and Path(item.name).name in {"opencode","opencode.exe"}]
        if len(candidates)!=1: raise SystemExit("official OpenCode 1 archive must contain one opencode executable")
        stream=package.extractfile(candidates[0])
        if stream is None: raise SystemExit("official OpenCode 1 archive executable could not be read")
        data=stream.read()
target.write_bytes(data)
os.chmod(target,0o755)
PY
        ;;
      2)
        archive="$stage_dir/opencode-${version}.tgz"
        python3 "$ROOT/scripts/opencode_release.py" download --version "$version" --destination "$archive" > "$stage_dir/release.json"
        tar -xzf "$archive" -C "$stage_dir" package/bin/opencode
        [[ -f "$stage_dir/package/bin/opencode" ]] || {
          anvil_error 'Official npm package did not contain package/bin/opencode.'
          exit 1
        }
        mv -- "$stage_dir/package/bin/opencode" "$stage_dir/opencode"
        rm -rf -- "$stage_dir/package"
        ;;
      *) anvil_error "Unsupported OpenCode runtime major: $major"; exit 2 ;;
    esac
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
    [[ $# -ge 3 && $# -le 4 ]] || { usage >&2; exit 2; }
    candidate="$2"
    version="$(candidate_version "$3")"
    major="${4:-${version%%.*}}"
    [[ "${version%%.*}" == "$major" ]] || { anvil_error "OpenCode $version does not belong to requested major $major."; exit 2; }
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
