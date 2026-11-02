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
  local runtime_major="${12:-}" stage_fn="${13:-}" preverify_fn="${14:-}" status phase_profile operation_id

  [[ -n "$plan_file" ]] || { anvil_error 'Lifecycle executor requires the planned ChangePlan.'; return 2; }
  phase_profile="$(anvil_lifecycle_validate_plan "$operation" "$plan_file" "$runtime_major")" || return $?
  python3 "$ANVIL_ROOT/scripts/state.py" verify "$backup" >/dev/null
  operation_id="$(python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" begin \
    --operation "$operation" --backup "$backup" \
    --source-version "$source_version" --target-version "$target_version" --owner-pid "$$" --print-id)"
  transaction_active=1
  ANVIL_LIFECYCLE_OPERATION_ID="$operation_id"
  export ANVIL_LIFECYCLE_OPERATION_ID
  ANVIL_LIFECYCLE_PLAN_FILE="$plan_file"
  export ANVIL_LIFECYCLE_PLAN_FILE

  if [[ -n "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase staging
    if "$stage_fn"; then
      :
    else
      status=$?
      python3 "$ANVIL_ROOT/scripts/analytics_dependencies.py" abort \
        --data-root "$ANVIL_DATA_HOME" --operation-id "$operation_id" >/dev/null 2>&1 || true
      python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase staging-failed || true
      if python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" clear; then
        anvil_error "Upgrade failed during staging (operation $operation_id). The active installation was not changed; installed release remains $source_version."
      else
        anvil_error "Upgrade failed during staging (operation $operation_id). Active files were not changed; pre-activation journal cleanup failed and will be handled on the next lifecycle command. Snapshot: $backup"
      fi
      transaction_active=0
      return "$status"
    fi
    ANVIL_ANALYTICS_RUNTIME_STAGED=1
    export ANVIL_ANALYTICS_RUNTIME_STAGED
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase pre-activation-verification
    if "$preverify_fn"; then
      :
    else
      status=$?
      python3 "$ANVIL_ROOT/scripts/analytics_dependencies.py" abort \
        --data-root "$ANVIL_DATA_HOME" --operation-id "$operation_id" >/dev/null 2>&1 || true
      python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase pre-activation-failed || true
      if python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" clear; then
        anvil_error "Upgrade pre-activation verification failed (operation $operation_id). The active installation was not changed; installed release remains $source_version."
      else
        anvil_error "Upgrade pre-activation verification failed (operation $operation_id). Active files were not changed; pre-activation journal cleanup failed. Snapshot: $backup"
      fi
      transaction_active=0
      return "$status"
    fi
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase activating
  fi

  if [[ "$phase_profile" == config && -z "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase applying-config
  fi
  "$apply_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }
  if [[ "$phase_profile" == config && -n "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase activation-completed
  elif [[ "$phase_profile" == config ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase config-applied
  fi
  if [[ -n "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase post-activation-verification
  else
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase before-installation-metadata
  fi

  anvil_lifecycle_require_plan_operation VerifyInstallation || return $?
  "$verify_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }
  anvil_lifecycle_require_plan_operation CommitInstallationRecord || return $?
  if [[ -n "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase committing
  fi
  "$commit_fn" || {
    status=$?
    anvil_lifecycle_fail "$status" "$backup" "$rollback_fn" "$rollback_message" "$failure_message"
    return "$status"
  }

  if [[ -n "$stage_fn" ]]; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase completed
  else
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase postflight-validated
  fi
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
  python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase recovery-restoring || {
    anvil_error 'Could not persist the recovery phase; the verified snapshot remains available for retry.'
    transaction_active=0
    return
  }
  if "$rollback_fn"; then
    python3 "$ANVIL_ROOT/scripts/lifecycle_transaction.py" phase recovery-verified || {
      anvil_error "Baseline restoration completed, but operation journal verification could not be recorded. Snapshot remains at $backup."
      transaction_active=0
      return
    }
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
