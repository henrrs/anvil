#!/usr/bin/env bash

# Common transaction runner for product and runtime lifecycle adapters.
# Adapters supply only the domain-specific apply, verify, commit and rollback
# callbacks; ordering, journaling and failure recovery stay here.

anvil_lifecycle_validate_plan() {
  local operation="$1" plan_file="$2" runtime_major="${3:-}"
  local args=(--operation "$operation" --plan-file "$plan_file")
  [[ -z "$runtime_major" ]] || args+=(--runtime-major "$runtime_major")
  python3 "$ANVIL_ROOT/scripts/lifecycle_executor.py" \
    "${args[@]}"
}

anvil_lifecycle_require_plan_operation() {
  local kind="$1"
  python3 - "$ANVIL_LIFECYCLE_PLAN_FILE" "$kind" <<'PY'
import json,sys
try:
    value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError):
    print("ERROR LIFECYCLE_EXECUTOR: the accepted ChangePlan is unavailable",file=sys.stderr)
    raise SystemExit(2)
if not any(isinstance(item,dict) and item.get("kind")==sys.argv[2]
           for item in value.get("operations",[])):
    print(f"ERROR LIFECYCLE_EXECUTOR: adapter requested unplanned operation {sys.argv[2]}",file=sys.stderr)
    raise SystemExit(2)
PY
}

anvil_lifecycle_execute() {
  local operation="$1" backup="$2" source_version="$3" target_version="$4"
  local apply_fn="$5" verify_fn="$6" commit_fn="$7" rollback_fn="$8"
  local rollback_message="$9" failure_message="${10}" plan_file="${11:-}"
  local runtime_major="${12:-}" status phase_profile

  [[ -n "$plan_file" ]] || { anvil_error 'Lifecycle executor requires the planned ChangePlan.'; return 2; }
  phase_profile="$(anvil_lifecycle_validate_plan "$operation" "$plan_file" "$runtime_major")" || return $?
  python3 "$ANVIL_ROOT/scripts/state.py" verify "$backup" >/dev/null
  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" begin \
    --operation "$operation" --backup "$backup" \
    --source-version "$source_version" --target-version "$target_version" --owner-pid "$$"
  transaction_active=1

  if [[ "$phase_profile" == config ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase applying-config
  fi
  ANVIL_LIFECYCLE_PLAN_FILE="$plan_file"
  export ANVIL_LIFECYCLE_PLAN_FILE
  "$apply_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }
  if [[ "$phase_profile" == config ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase config-applied
  fi
  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase before-installation-metadata

  anvil_lifecycle_require_plan_operation VerifyInstallation || return $?
  "$verify_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }
  anvil_lifecycle_require_plan_operation CommitInstallationRecord || return $?
  "$commit_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }

  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase postflight-validated
  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" clear
  transaction_active=0
}

anvil_lifecycle_fail() {
  local status="$1" backup="$2" rollback_fn="$3" rollback_message="$4" failure_message="$5"
  local journal operation_id failed_phase
  if declare -F anvil_lifecycle_failure_detail >/dev/null; then
    anvil_lifecycle_failure_detail "$status"
  fi
  anvil_error "$failure_message (exit $status); restoring the verified snapshot."
  if "$rollback_fn"; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" clear || {
      journal="$(python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" inspect 2>/dev/null || printf '{}')"
      read -r operation_id failed_phase < <(python3 - "$journal" <<'PY'
import json,sys
try: value=json.loads(sys.argv[1])
except (ValueError,TypeError): value={}
print(value.get("operation_id") or "unknown", value.get("phase") or "unknown")
PY
)
      anvil_error "Automatic rollback completed, but operation $operation_id journal cleanup failed at phase $failed_phase. Snapshot remains at $backup."
      transaction_active=0
      return
    }
    transaction_active=0
    anvil_ok "$rollback_message"
  else
    journal="$(python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" inspect 2>/dev/null || printf '{}')"
    read -r operation_id failed_phase < <(python3 - "$journal" <<'PY'
import json,sys
try: value=json.loads(sys.argv[1])
except (ValueError,TypeError): value={}
print(value.get("operation_id") or "unknown", value.get("phase") or "unknown")
PY
)
    transaction_active=0
    anvil_error "Automatic rollback failed for operation $operation_id at phase $failed_phase. Verified snapshot remains at $backup"
  fi
}
