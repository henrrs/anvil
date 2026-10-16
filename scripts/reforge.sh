#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
ANVIL_VERSION="$(cat "$ROOT/VERSION")"

anvil_need python3 tar cp mv install chmod date ps
python3 - <<'PY'
import sys
if sys.version_info < (3, 11):
    raise SystemExit("ERROR Anvil requires Python 3.11 or newer.")
PY

if ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR"; then
  anvil_error 'Global config path did not pass the managed-path check.'
  exit 1
fi
if [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" ]]; then
  anvil_error 'OpenCode installer directory did not pass the managed-path check.'
  exit 1
fi
if [[ -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]]; then
  anvil_error 'The OpenCode installer directory or bin directory is a symlink; refusing to install through it.'
  exit 1
fi
python3 "$ROOT/scripts/active-opencode.py" || {
  anvil_error 'Close OpenCode before reforge so its database can be backed up consistently.'
  exit 1
}

previous_anvil_version=""
previous_opencode_version=""
from_generation=0
if [[ -f "$ANVIL_DATA_DIR/installation.json" ]]; then
  IFS=$'\t' read -r previous_anvil_version previous_opencode_version < <(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(f"{value.get('anvil_version','')}\t{value.get('version','')}")
PY
)
fi
if python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=1
elif python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=2
fi

tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-reforge.XXXXXX")"
chmod 700 -- "$tmp_root"
backup_dir=""
transaction_active=0
candidate=""
candidate_version=""
release_json="$tmp_root/release.json"
runtime_action="reuse"
path_result='{"added":false,"manual_required":false}'
target_major=""

cleanup_temp() {
  local base canonical
  base="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "${TMPDIR:-/tmp}")/anvil-reforge."
  canonical="$(python3 -c 'import os,sys; print(os.path.abspath(sys.argv[1]))' "$tmp_root")"
  if [[ -d "$canonical" && "$canonical" == "$base"* && "$canonical" != / ]]; then rm -rf -- "$canonical"; fi
}
on_error() {
  local status=$?
  trap - ERR INT TERM
  if (( transaction_active )) && [[ -n "$backup_dir" ]]; then
    anvil_error "Reforge failed after Anvil config replacement (exit $status); attempting rollback."
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
      anvil_ok 'Automatic rollback completed.'
    else
      anvil_error "Automatic rollback failed. Verified backup remains at $backup_dir"
    fi
  fi
  cleanup_temp
  exit "$status"
}
trap on_error ERR INT TERM
trap cleanup_temp EXIT

runtime_json="$(anvil_runtime_json)"
read -r binary version major supported usable installed < <(python3 - "$runtime_json" <<'PY'
import json,sys
d=json.loads(sys.argv[1]); r=d.get("runtime") or {}
present=any(bool(item.get("installed")) for item in d.get("candidates",[]) if isinstance(item,dict))
print("\t".join(str(v if v is not None else "") for v in
                 (r.get("executable"),r.get("version"),r.get("generation"),r.get("supported"),r.get("usable"),present)))
PY
)
if [[ "$usable" == True || "$installed" == True ]]; then
  if [[ "$supported" != True ]]; then
    if [[ "$usable" == True && "$major" =~ ^[12]$ ]]; then
      anvil_error "OpenCode ${version:-unknown} is installed but not policy-compliant. Run make update-runtime to update within OpenCode $major, or make migrate-runtime OPENCODE_MAJOR=N for an explicit major change."
    else
      anvil_error 'An OpenCode executable exists but is unhealthy or unsupported. Repair or remove it explicitly before provisioning another runtime.'
    fi
    exit 1
  fi
  candidate="$binary"
  candidate_version="$version"
  target_major="$major"
  [[ -n "$previous_anvil_version" ]] || previous_anvil_version='Anvil version not recorded'
  anvil_log "Reforge will reuse the exact validated OpenCode $version runtime at $binary."
else
  runtime_action="install"
  target_major="$(python3 "$ROOT/scripts/runtime.py" policy | python3 -c 'import json,sys; print(json.load(sys.stdin)["opencode"]["default_major"])')"
  anvil_log "No OpenCode runtime was found; first-install policy selects OpenCode $target_major."
  if [[ "${ANVIL_TEST_MODE:-0}" == 1 ]]; then
    candidate="${ANVIL_TEST_CANDIDATE_BINARY:-}"
    [[ -n "$candidate" && -x "$candidate" ]] || { anvil_error 'Test mode requires ANVIL_TEST_CANDIDATE_BINARY.'; exit 2; }
    candidate_version="$(env -i PATH="${PATH:-/usr/bin:/bin}" HOME="$tmp_root" "$candidate" --version 2>/dev/null | head -n 1)"
    candidate_version="${candidate_version#opencode }"
    candidate_version="${candidate_version#v}"
    python3 - "$release_json" "$candidate_version" <<'PY'
import json,sys
with open(sys.argv[1],"w",encoding="utf-8") as stream:
    json.dump({"version":sys.argv[2],"channel":"latest","published_at":None,
               "release_url":"isolated test fixture","asset":{"name":"fixture","integrity":"sha512-fixture"}},stream)
PY
  else
    if ! bash "$ROOT/scripts/install-opencode.sh" resolve "$target_major" > "$release_json"; then
      anvil_error 'Fresh OpenCode provisioning could not resolve an approved release. No Anvil or runtime files were changed; check access to the official release source and retry.'
      exit 1
    fi
    candidate_version="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8"))["version"])' "$release_json")"
    if ! candidate="$(bash "$ROOT/scripts/install-opencode.sh" stage "$candidate_version" "$tmp_root/candidate" "$target_major")"; then
      anvil_error 'Fresh OpenCode download/validation failed. No Anvil or runtime files were changed; retry when the official release source is reachable.'
      exit 1
    fi
    cp -- "$tmp_root/candidate/release.json" "$release_json"
  fi
  candidate_version="${candidate_version#opencode }"
  candidate_version="${candidate_version#v}"
  [[ "$candidate_version" =~ ^${target_major}\.[0-9]+\.[0-9]+$ ]] || { anvil_error "Invalid stable OpenCode $target_major version: $candidate_version"; exit 1; }
fi

printf '%s\n' 'Anvil Reforge' '─────────────'
printf 'Global config          %s\n' "$ANVIL_CONFIG_DIR"
printf 'OpenCode executable    %s\n' "$candidate"
printf 'OpenCode version       %s\n' "$candidate_version"
printf 'Runtime action         %s\n' "$( [[ "$runtime_action" == reuse ]] && printf 'PRESERVE EXACT RUNTIME' || printf 'INSTALL APPROVED FIRST-USE RUNTIME')"
bash "$ROOT/scripts/inspect.sh"

ready_config="$tmp_root/global-config"
anvil_build_config "$ready_config" "$ANVIL_CONFIG_DIR" no "$target_major"
if [[ "$target_major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ready_config/opencode.jsonc"
else
  python3 "$ROOT/scripts/configure.py" audit "$ready_config/opencode.jsonc"
fi
if [[ "$runtime_action" == install ]]; then
  candidate_state="$(python3 "$ROOT/scripts/runtime_state.py" discover --binary "$candidate" --format json)"
  if ! python3 - "$candidate_state" <<'PY'
import json,sys
runtime=json.loads(sys.argv[1]).get("runtime") or {}
raise SystemExit(0 if runtime.get("supported") else 1)
PY
  then
    anvil_error "OpenCode $candidate_version does not meet Anvil's minimum supported runtime policy; no files were changed."
    exit 1
  fi
fi
if [[ "$runtime_action" == reuse ]]; then
  bash "$ROOT/scripts/validate-candidate.sh" "$candidate" "$ready_config" "$candidate_version" "$target_major"
else
  bash "$ROOT/scripts/validate-candidate.sh" "$candidate" "$ready_config" "$candidate_version" "$target_major"
  path_plan="$(python3 "$ROOT/scripts/path_edit.py" plan \
    --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
    --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"
fi

if [[ "$runtime_action" == reuse ]]; then
  backup_scope=anvil
  path_plan='{"file":"","line":"","added":false,"file_preexisted":false}'
else
  backup_scope=runtime
fi
backup_dir="$(anvil_backup_create "$candidate_version" "$path_plan" "$backup_scope" | tail -n 1)"
python3 "$ROOT/scripts/state.py" verify "$backup_dir"

if [[ "${ANVIL_YES:-0}" != 1 ]]; then
  if [[ ! -t 0 ]]; then
    anvil_error 'Reforge needs confirmation in an interactive terminal; set ANVIL_YES=1 only after reviewing the plan.'
    exit 2
  fi
  if [[ "$runtime_action" == reuse ]]; then
    printf '\nThis will rebuild Anvil configuration and preserve OpenCode %s exactly. Snapshot:\n%s\n' "$candidate_version" "$backup_dir"
  else
    printf '\nThis will install OpenCode %s and rebuild the global Anvil harness. Snapshot:\n%s\n' "$candidate_version" "$backup_dir"
  fi
  read -r -p 'Continue with Anvil reforge? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Reforge cancelled; no live state was changed.'
    exit 0
  }
fi

transaction_active=1
anvil_apply_config "$ready_config"
if [[ "$runtime_action" == install ]]; then
  bash "$ROOT/scripts/install-opencode.sh" install "$candidate" "$candidate_version" "$target_major"
  path_result="$(python3 "$ROOT/scripts/path_edit.py" apply \
    --home "$ANVIL_HOME_DIR" --xdg-config-home "$ANVIL_CONFIG_HOME" \
    --install-dir "$ANVIL_INSTALL_BIN" --shell "${SHELL:-bash}" --path "$PATH")"
  export PATH="$ANVIL_INSTALL_BIN:$PATH"
fi
XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null

if [[ "$runtime_action" == reuse ]]; then
  python3 "$ROOT/scripts/installation.py" \
    --destination "$ANVIL_DATA_DIR/installation.json" --opencode-version "$candidate_version" \
    --anvil-version "$ANVIL_VERSION" --opencode-major "$target_major" \
    --binary "$candidate" --anvil-only --migration-status reforge \
    --previous-anvil-version "$previous_anvil_version" --previous-opencode-version "$previous_opencode_version" \
    --from-generation "$from_generation" --backup "$backup_dir"
else
  python3 "$ROOT/scripts/installation.py" \
    --destination "$ANVIL_DATA_DIR/installation.json" --opencode-version "$candidate_version" \
    --anvil-version "$ANVIL_VERSION" --opencode-major "$target_major" \
    --binary "$ANVIL_INSTALLED_BINARY" --release-json "$release_json" \
    --migration-status reforge --previous-anvil-version "$previous_anvil_version" \
    --previous-opencode-version "$previous_opencode_version" --from-generation "$from_generation" \
    --backup "$backup_dir"
fi
recorded_binary="$candidate"
if [[ "$runtime_action" == install ]]; then recorded_binary="$ANVIL_INSTALLED_BINARY"; fi
python3 "$ROOT/scripts/runtime_state.py" record --binary "$recorded_binary" >/dev/null

doctor_status=0
bash "$ROOT/scripts/doctor.sh" || doctor_status=$?
if (( doctor_status == 1 || doctor_status > 2 )); then
  anvil_error 'Postflight doctor reported a broken installation.'
  false
elif (( doctor_status == 2 )); then
  anvil_warn 'Reforge completed with project or environment override warnings.'
fi

transaction_active=0
anvil_ok "Anvil $ANVIL_VERSION installed with OpenCode $candidate_version."
anvil_ok "Verified $backup_scope-scope backup: $backup_dir"
if [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("added",False))' "$path_result")" == True ]]; then
  anvil_log "Added $ANVIL_INSTALL_BIN to the selected shell startup file; open a new shell to refresh PATH."
elif [[ "$(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("manual_required",False))' "$path_result")" == True ]]; then
  anvil_warn "Could not safely edit $(python3 -c 'import json,sys; print(json.loads(sys.argv[1]).get("file", "the shell startup file"))' "$path_result"). Add $ANVIL_INSTALL_BIN to PATH manually."
fi
anvil_offer_databricks_setup
