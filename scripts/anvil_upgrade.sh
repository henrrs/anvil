#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
source "$ROOT/scripts/lib/install.sh"
source "$ROOT/scripts/lib/backup.sh"
source "$ROOT/scripts/lib/lifecycle-operation.sh"
anvil_need python3 tar cp mv install chmod date

[[ $# == 0 ]] || { anvil_error 'make upgrade accepts DRY_RUN=1 only; use make update-runtime or make migrate-runtime for OpenCode changes.'; exit 2; }
ANVIL_VERSION="$(cat "$ROOT/VERSION")"

anvil_recover_pending
if ! anvil_require_installed; then
  python3 "$ROOT/scripts/lifecycle_state.py" inspect --format json 2>/dev/null | python3 -c '
import json,sys
try: state=json.load(sys.stdin)
except (ValueError,IndexError): raise SystemExit(0)
drift=state.get("managed_config",{}).get("drift") or {}
if drift.get("classification") in {"UNSAFE_MANAGED_DRIFT","UNKNOWN_DRIFT"}:
    findings=drift.get("findings") or [{"path":"unknown","ownership":"unknown"}]
    for item in findings:
        print(json.dumps({"event":"unsafe_drift_blocked","path":item.get("path"),
                          "ownership":item.get("ownership"),
                          "classification":drift["classification"],
                          "installed_release":drift.get("installed_release"),
                          "target_release":drift.get("target_release")},sort_keys=True))
'
  exit 1
fi
if ! python3 "$ROOT/scripts/release_authority.py" verify; then
  anvil_error 'Upgrade stopped before snapshot or dependency staging because the target release is not authoritative.'
  exit 2
fi
if ! plan_json="$(python3 "$ROOT/scripts/lifecycle_plan.py" upgrade --format json)"; then
  python3 "$ROOT/scripts/lifecycle_plan.py" upgrade --format text || true
  exit 2
fi
if [[ -L "$ANVIL_CONFIG_DIR" || -L "$ANVIL_INSTALL_ROOT" || -L "$ANVIL_INSTALL_BIN" ]] || \
   ! anvil_safe_managed_path "$ANVIL_CONFIG_DIR" "$ANVIL_CONFIG_DIR" || \
   [[ "$ANVIL_INSTALL_ROOT" != "$ANVIL_HOME_DIR/.opencode" || "$ANVIL_INSTALL_ROOT" == / || "$ANVIL_INSTALL_ROOT" == "$ANVIL_HOME_DIR" ]]; then
  anvil_error 'Managed config/install paths did not pass the safety check.'
  exit 1
fi

runtime_json="$(anvil_runtime_json)"
IFS=$'\t' read -r binary runtime_version major adapter supported < <(python3 - "$runtime_json" <<'PY'
import json,sys
r=json.loads(sys.argv[1]).get("runtime") or {}
print("\t".join(str(r.get(k) or "") for k in ("executable","version","generation","adapter","supported")))
PY
)
if [[ -z "$binary" || ! -x "$binary" ]]; then
  anvil_error 'A usable OpenCode runtime was not found. Install one with make reforge before upgrading Anvil.'
  exit 1
fi
if [[ "$supported" != True ]]; then
  anvil_error "OpenCode ${runtime_version:-unknown} is outside the supported runtime policy. Use make update-runtime for a supported version in the same major, or make migrate-runtime OPENCODE_MAJOR=N for a major change."
  exit 1
fi

if python3 "$ROOT/scripts/configure.py" audit-v1-compatible "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=1
  python3 "$ROOT/scripts/configure.py" audit-v1-compatible "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null
elif python3 "$ROOT/scripts/configure.py" audit-compatible "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  from_generation=2
  python3 "$ROOT/scripts/configure.py" audit-compatible "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null
else
  anvil_error 'Current global config is not a supported Anvil OpenCode profile; use make reforge to rebuild it.'
  exit 1
fi
old_anvil_version="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
if not isinstance(value,dict): value={}
print(value.get("anvil_version") or "not recorded")
PY
)"
ready_config="$(mktemp -d "${TMPDIR:-/tmp}/anvil-config.XXXXXX")"
chmod 700 -- "$ready_config"
tmp_root="$(mktemp -d "${TMPDIR:-/tmp}/anvil-anvil-upgrade.XXXXXX")"
chmod 700 -- "$tmp_root"
plan_file="$tmp_root/change-plan.json"
printf '%s\n' "$plan_json" > "$plan_file"
chmod 600 -- "$plan_file"
anvil_lifecycle_validate_plan anvil-upgrade "$plan_file" >/dev/null
backup_dir=""
transaction_active=0
runtime_stopped=0
drift_file=""
drift_count=0

cleanup() {
  for target in "$ready_config" "$tmp_root"; do
    python3 - "$target" "${TMPDIR:-/tmp}" <<'PY'
import os,shutil,sys
path,base=map(os.path.abspath,sys.argv[1:])
if path != base and os.path.commonpath((path,base)) == base and os.path.basename(path).startswith(("anvil-config.","anvil-anvil-upgrade.")):
    shutil.rmtree(path,ignore_errors=True)
PY
  done
}
on_error() {
  local status=$?
  trap - ERR INT TERM
  if (( transaction_active )) && [[ -n "$backup_dir" ]]; then
    if (( drift_count > 0 )); then
      python3 - "$drift_file" "$status" <<'PY' >&2
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (ValueError,IndexError): value={}
for item in value.get("findings",[]):
    print(json.dumps({"event":"managed_drift_repair_failed","path":item.get("path"),
                      "ownership":item.get("ownership"),"classification":item.get("classification"),
                      "installed_release":item.get("installed_release"),
                      "target_release":item.get("target_release"),"exit_status":int(sys.argv[2])},sort_keys=True))
PY
    fi
    anvil_error "Anvil upgrade failed after config replacement (exit $status); restoring the Anvil-only snapshot."
    python3 "$ROOT/scripts/lifecycle_transaction.py" phase recovery-restoring || {
      anvil_error "Could not persist rollback progress; the verified snapshot remains at $backup_dir."
      cleanup
      exit "$status"
    }
    if ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal; then
      python3 "$ROOT/scripts/lifecycle_transaction.py" phase recovery-verified || {
        anvil_error "Baseline restored, but recovery verification could not be journaled. Snapshot remains at $backup_dir."
        cleanup
        exit "$status"
      }
      python3 "$ROOT/scripts/lifecycle_transaction.py" clear || anvil_error 'Automatic rollback completed, but the recovery journal could not be cleared.'
      anvil_ok 'Automatic Anvil rollback completed; the OpenCode runtime and data were preserved.'
    else
      anvil_error "Automatic rollback failed. Verified snapshot remains at $backup_dir"
    fi
  fi
  if (( runtime_stopped )); then
    anvil_warn 'OpenCode remains stopped after the failed Anvil upgrade. Start it normally when ready.'
  fi
  cleanup
  exit "$status"
}
trap on_error ERR INT TERM
trap cleanup EXIT

anvil_build_config "$ready_config/generated" "$ANVIL_CONFIG_DIR" yes "$major" "$old_anvil_version" no yes
manifest_sha256="$(python3 - "$ANVIL_DATA_DIR/installation.json" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
if not isinstance(value,dict): value={}
print(value.get("managed_config_manifest_sha256") or "")
PY
)"
drift_file="$tmp_root/managed-drift.json"
python3 "$ROOT/scripts/managed_config.py" classify --root "$ANVIL_CONFIG_DIR" \
  --installed-version "$old_anvil_version" --target-version "$ANVIL_VERSION" \
  --manifest-sha256 "$manifest_sha256" > "$drift_file"
drift_count="$(python3 - "$drift_file" <<'PY'
import json,sys
value=json.load(open(sys.argv[1],encoding="utf-8"))
if value.get("classification") not in {"CLEAN","REPAIRABLE_MANAGED_DRIFT"}:
    raise SystemExit("upgrade cannot safely repair managed state: "+str(value.get("reason")))
print(len(value.get("findings",[])))
PY
)"
if (( drift_count > 0 )); then
  printf '\nAn Anvil-managed file differs from the version originally installed.\n'
  printf 'The target release has a verified replacement; the current file will be preserved for rollback.\n'
  python3 - "$drift_file" <<'PY' >&2
import json,sys
for item in json.load(open(sys.argv[1],encoding="utf-8")).get("findings",[]):
    for event in ("managed_drift_detected","managed_drift_classified"):
        print(json.dumps({"event":event,"path":item.get("path"),"ownership":item.get("ownership"),
                          "classification":item.get("classification"),
                          "installed_release":item.get("installed_release"),
                          "target_release":item.get("target_release"),
                          "expected_hash":item.get("expected_hash"),"current_hash":item.get("current_hash"),
                          "target_hash":item.get("target_hash")},sort_keys=True))
PY
fi
if [[ "$major" == 1 ]]; then
  python3 "$ROOT/scripts/configure.py" audit-v1 "$ready_config/generated/opencode.jsonc" >/dev/null
else
  python3 "$ROOT/scripts/configure.py" audit "$ready_config/generated/opencode.jsonc" >/dev/null
fi
bash "$ROOT/scripts/rehearse-upgrade.sh" "$binary" "$runtime_version" "$major" "$major" no "$ready_config/generated"

# Check backup prerequisites before interrupting the user's runtime. This is
# read-only: backup creation itself remains after quiescence and final approval.
if ! python3 "$ROOT/scripts/backup_preflight.py"; then
  anvil_error 'Upgrade preflight failed; OpenCode is still running and no live files were changed.'
  exit 1
fi
process_json="$(python3 "$ROOT/scripts/runtime_processes.py" --binary "$binary" --format json)"
read -r process_count process_uncertain self_ancestor < <(python3 - "$process_json" <<'PY'
import json,sys
value=json.loads(sys.argv[1])
print(value["count"], str(value["uncertain"]), str(value["self_ancestor"]))
PY
)
if [[ "$process_uncertain" == True && "${DRY_RUN:-0}" != 1 ]]; then
  anvil_error 'OpenCode process identity could not be fully verified; refusing to create a potentially inconsistent backup.'
  exit 1
fi

printf '%s\n' 'Anvil Upgrade Plan' '────────────────────────────────'
printf 'Anvil installed       %s\n' "$old_anvil_version"
printf 'Anvil repository      %s\n' "$ANVIL_VERSION"
printf 'Anvil action          %s\n' "$( [[ "$old_anvil_version" == "$ANVIL_VERSION" ]] && printf 'REINSTALL CURRENT RELEASE' || printf 'UPGRADE')"
printf '\nOpenCode\n'
printf '  executable          %s\n' "$binary"
printf '  installed           %s\n' "$runtime_version"
printf '  generation          %s\n' "$major"
printf '  action              PRESERVE EXACT VERSION\n'
printf '  active processes    %s running\n' "$process_count"
if [[ "$process_uncertain" == True ]]; then
  printf '  identity check      incomplete; a real upgrade will stop safely before signaling\n'
fi
if [[ "$self_ancestor" == True ]]; then
  printf '  process ancestry    upgrade is running inside OpenCode; a real upgrade will abort\n'
fi
printf '\nRuntime adapter\n'
printf '  current             %s\n' "$adapter"
printf '  target              %s\n' "$adapter"
printf '\nNetwork required      NO\n'
printf 'Databricks state      PRESERVE\n'
printf 'Rehearsal             passed using the exact local runtime and copied user state\n'
printf '\nUpgrade behavior\n'
printf '  countdown           %ss\n' "${ANVIL_UPGRADE_COUNTDOWN_SECONDS:-5}"
printf '  graceful shutdown   enabled (SIGTERM first)\n'
printf '  force termination   fallback only\n'
anvil_print_config_plan "$ANVIL_CONFIG_DIR" "$ready_config/generated" "$old_anvil_version" "$ANVIL_VERSION" no yes
anvil_print_analytics_plan "$ready_config/generated"

if [[ "${DRY_RUN:-0}" == 1 ]]; then
  python3 "$ROOT/scripts/lifecycle_plan.py" --render-file "$plan_file"
  printf '\nNo changes performed.\nNo processes stopped.\nNo files changed.\n'
  exit 0
fi
if [[ "$self_ancestor" == True ]]; then
  anvil_error 'This upgrade is running from inside OpenCode. Anvil cannot safely stop its own parent runtime; run the upgrade from an external terminal.'
  exit 1
fi
if [[ "${ANVIL_YES:-0}" != 1 ]]; then
  if [[ ! -t 0 ]]; then
    anvil_error 'Upgrade needs one confirmation in an interactive terminal; set ANVIL_YES=1 only after reviewing the local plan.'
    exit 2
  fi
  read -r -p 'Upgrade Anvil files while preserving OpenCode exactly? [y/N] ' answer
  [[ "$answer" == y || "$answer" == Y || "$answer" == yes || "$answer" == YES ]] || {
    anvil_log 'Upgrade cancelled; no live files were changed.'
    exit 0
  }
fi

path_plan='{"file":"","line":"","added":false,"file_preexisted":false}'
if ! python3 "$ROOT/scripts/runtime_quiesce.py" --binary "$binary" \
    --countdown "${ANVIL_UPGRADE_COUNTDOWN_SECONDS:-5}" \
    --grace-timeout "${ANVIL_OPEN_CODE_GRACE_SECONDS:-10}"; then
  exit 1
fi
if (( process_count > 0 )); then runtime_stopped=1; fi
post_quiesce="$(python3 "$ROOT/scripts/runtime_processes.py" --binary "$binary" --format json)"
read -r remaining_count remaining_uncertain < <(python3 - "$post_quiesce" <<'PY'
import json,sys
value=json.loads(sys.argv[1])
print(value["count"], str(value["uncertain"]))
PY
)
if [[ "$remaining_uncertain" == True || "$remaining_count" != 0 ]]; then
  anvil_error 'OpenCode could not be verified as fully stopped; no backup will be created.'
  exit 1
fi
backup_dir="$(ANVIL_PREVIOUS_ANVIL_VERSION="$old_anvil_version" anvil_backup_create "$runtime_version" "$path_plan" anvil | tail -n 1)"
python3 "$ROOT/scripts/state.py" verify "$backup_dir" >/dev/null
if [[ "${ANVIL_TEST_FAIL_AFTER_BACKUP:-0}" == 1 ]]; then
  anvil_error 'Injected failure after backup verification and before live mutation.'
  exit 1
fi

anvil_lifecycle_failure_detail() {
  local status="$1"
  if (( drift_count > 0 )); then
    python3 - "$drift_file" "$status" <<'PY' >&2
import json,sys
for item in json.load(open(sys.argv[1],encoding="utf-8")).get("findings",[]):
    print(json.dumps({"event":"managed_drift_repair_failed","path":item.get("path"),
                      "ownership":item.get("ownership"),"classification":item.get("classification"),
                      "installed_release":item.get("installed_release"),
                      "target_release":item.get("target_release"),"exit_status":int(sys.argv[2])},sort_keys=True))
PY
  fi
}

stage_upgrade() {
  local target_lock="$ready_config/generated/runtime/analytics-requirements.lock"
  [[ -f "$target_lock" ]] || return 0
  anvil_lifecycle_require_plan_operation InstallAnalyticsDependencies || return $?
  if [[ "${ANVIL_TEST_MODE:-0}" == 1 && -z "${ANVIL_TEST_FAIL_ANALYTICS_PACKAGE:-}" ]]; then
    anvil_log 'Offline lifecycle fixture: Analytics packages are represented by the staged release lock.'
    return 0
  fi
  python3 "$ROOT/scripts/analytics_dependencies.py" stage \
    --lock "$target_lock" --data-root "$ANVIL_DATA_HOME" \
    --operation-id "$ANVIL_LIFECYCLE_OPERATION_ID" >/dev/null
}

preverify_upgrade() {
  python3 "$ROOT/scripts/lifecycle_baseline.py" verify-plan \
    --backup "$backup_dir" --target-config "$ready_config/generated" >/dev/null
  if [[ -f "$ready_config/generated/runtime/analytics-requirements.lock" ]]; then
    anvil_lifecycle_require_plan_operation InstallAnalyticsDependencies || return $?
    anvil_lifecycle_require_plan_operation EnsureAnalyticsService || return $?
  fi
  python3 "$ROOT/scripts/lifecycle_verify.py" --phase pre-activation \
    --config "$ready_config/generated" --memory "$ANVIL_DATA_DIR/memory" --binary "$binary" \
    --product-version "$ANVIL_VERSION" --runtime-version "$runtime_version" --runtime-major "$major"
}

apply_upgrade() {
  anvil_lifecycle_require_plan_operation ReplaceManagedArtifacts || return $?
  if [[ -f "$ready_config/generated/runtime/analytics-requirements.lock" ]]; then
    anvil_lifecycle_require_plan_operation InstallAnalyticsDependencies || return $?
    anvil_lifecycle_require_plan_operation EnsureAnalyticsService || return $?
  fi
  if (( drift_count > 0 )); then
    printf 'Repairing %s Anvil-managed drifted artifact(s)...\n' "$drift_count"
    python3 - "$drift_file" <<'PY' >&2
import json,sys
for item in json.load(open(sys.argv[1],encoding="utf-8")).get("findings",[]):
    print(json.dumps({"event":"managed_drift_repair_started","path":item.get("path"),
                      "ownership":item.get("ownership"),"classification":item.get("classification"),
                      "installed_release":item.get("installed_release"),
                      "target_release":item.get("target_release")},sort_keys=True))
PY
  fi
  anvil_apply_config "$ready_config/generated" || return $?
  if [[ "${ANVIL_TEST_MIGRATE_CONTEXT_DB:-0}" == 1 ]]; then
    [[ "${ANVIL_TEST_MODE:-0}" == 1 ]] || {
      anvil_error 'Context database migration injection is reserved for isolated lifecycle tests.'
      return 2
    }
    PYTHONPATH="$ANVIL_CONFIG_DIR" python3 -c \
      'from scripts.analytics.store import ContextStore; ContextStore()' || return $?
  fi
  if [[ "${ANVIL_TEST_FAIL_AFTER_CONFIG:-0}" == 1 ]]; then
    anvil_error 'Injected failure after Anvil config replacement.'
    return 1
  fi
  XDG_DATA_HOME="$ANVIL_DATA_HOME" python3 "$ANVIL_CONFIG_DIR/scripts/memory.py" init >/dev/null || return $?
}

verify_upgrade() {
  if [[ "${ANVIL_TEST_FAIL_BEFORE_METADATA:-0}" == 1 ]]; then
    anvil_error 'Injected failure before installation metadata was written.'
    return 1
  fi
  if [[ "${ANVIL_TEST_FAIL_DOCTOR:-0}" == 1 ]]; then
    anvil_error 'Injected post-apply verification failure.'
    return 1
  fi
  python3 "$ROOT/scripts/lifecycle_verify.py" \
    --config "$ANVIL_CONFIG_DIR" --memory "$ANVIL_DATA_DIR/memory" --binary "$binary" \
    --product-version "$ANVIL_VERSION" --runtime-version "$runtime_version" --runtime-major "$major"
}

commit_upgrade() {
  python3 "$ROOT/scripts/installation.py" \
    --destination "$ANVIL_DATA_DIR/installation.json" \
    --config-dir "$ANVIL_CONFIG_DIR" \
    --opencode-version "$runtime_version" --anvil-version "$ANVIL_VERSION" \
    --opencode-major "$major" --binary "$binary" --anvil-only \
    --migration-status anvil-upgrade --previous-anvil-version "$old_anvil_version" --backup "$backup_dir" || return $?
  python3 "$ROOT/scripts/runtime_state.py" record >/dev/null || return $?
  if [[ -f "$ready_config/generated/runtime/analytics-requirements.lock" &&
        "${ANVIL_TEST_MODE:-0}" != 1 ]]; then
    python3 "$ROOT/scripts/analytics_dependencies.py" finalize \
      --data-root "$ANVIL_DATA_HOME" --operation-id "$ANVIL_LIFECYCLE_OPERATION_ID" >/dev/null || return $?
  fi
}

rollback_upgrade() {
  ANVIL_INTERNAL_MODE=1 bash "$ROOT/scripts/rollback.sh" --backup "$backup_dir" --internal
}

# The shared runner owns journal order, verify-before-commit and rollback.
anvil_lifecycle_execute anvil-upgrade "$backup_dir" "$old_anvil_version" "$ANVIL_VERSION" \
  apply_upgrade verify_upgrade commit_upgrade rollback_upgrade \
  'Automatic Anvil rollback completed; the OpenCode runtime and data were preserved.' \
  'Anvil upgrade failed after activation' "$plan_file" "" stage_upgrade preverify_upgrade
anvil_ok "Anvil $ANVIL_VERSION installed; OpenCode $runtime_version was preserved exactly."
anvil_ok "Anvil-only rollback snapshot: $backup_dir"
if (( drift_count > 0 )); then
  python3 - "$drift_file" <<'PY' >&2
import json,sys
for item in json.load(open(sys.argv[1],encoding="utf-8")).get("findings",[]):
    print(json.dumps({"event":"managed_drift_repair_completed","path":item.get("path"),
                      "ownership":item.get("ownership"),"classification":item.get("classification"),
                      "installed_release":item.get("installed_release"),
                      "target_release":item.get("target_release")},sort_keys=True))
PY
fi
if (( runtime_stopped )); then
  anvil_log 'OpenCode was stopped during the upgrade. Start it normally when ready.'
fi
