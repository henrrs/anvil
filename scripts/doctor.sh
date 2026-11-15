#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3

observation="$(python3 "$ROOT/scripts/lifecycle_resolver.py")"
lifecycle_text="$(python3 -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import lifecycle_state; print(lifecycle_state._human(json.load(sys.stdin)["current"]["lifecycle"]))' "$ROOT/scripts" <<<"$observation")"
record_file="$ANVIL_DATA_DIR/installation.json"
summary="$(python3 -c '
import json,sys
from pathlib import Path
root=Path(sys.argv[1]); sys.path.insert(0,str(root/"scripts"))
import runtime
current=json.load(sys.stdin)["current"]
selected=current["active_runtime"].get("runtime") or {}
capability=runtime.capabilities(observed_runtime=selected)["runtime"]
try: record=json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
except (OSError,ValueError): record={}
if not isinstance(record,dict): record={}
policy=json.loads((root/"config/runtime-policy.json").read_text(encoding="utf-8"))["opencode"]
for value in (root.joinpath("VERSION").read_text(encoding="utf-8").strip(),
              current["lifecycle"]["lifecycle"], policy["minimum_versions"]["1"],
              selected.get("executable") or "", record.get("version") or "",
              record.get("anvil_version") or "", record.get("runtime_major",record.get("generation")) or "",
              capability.get("version") or "unknown", capability.get("major") or "",
              str(capability.get("supported")), capability.get("minimum_version") or "",
              "yes" if selected.get("path_ready") else "no"):
    print(value)
' "$ROOT" "$record_file" <<<"$observation")"
mapfile -t fields <<<"$summary"
expected_anvil="${fields[0]}" lifecycle_status="${fields[1]}" policy_minimum="${fields[2]}" binary="${fields[3]}"
recorded_opencode="${fields[4]}" recorded_anvil="${fields[5]}" recorded_major="${fields[6]}"
normalized="${fields[7]}" major="${fields[8]}" supported="${fields[9]}" minimum="${fields[10]}"
runtime_path_ready="${fields[11]}"

printf '%s\n' 'Anvil Doctor' '────────────'
printf '%s\n' "$lifecycle_text"
printf '\n'
databricks_probe_status=0
if [[ "${ANVIL_DOCTOR_LOCAL:-0}" == 1 ]]; then
  databricks_status="$(python3 -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import databricks; state=json.load(sys.stdin)["current"]["databricks"]; print("Databricks\n  Overall              INVALID\n  Recovery             Review the Anvil-owned Databricks state before setup." if state.get("overall")=="INVALID" else databricks.status_text(state))' "$ROOT/scripts" <<<"$observation")" || databricks_probe_status=$?
else
  databricks_status="$(python3 "$ROOT/scripts/databricks.py" status --format text 2>&1)" || databricks_probe_status=$?
fi
printf '%s\n' "$databricks_status"
printf 'Anvil version          %s' "$expected_anvil"
if [[ "$recorded_anvil" == "$expected_anvil" ]]; then
  printf ' (installed)\n'
else
  printf ' (installed %s)\n' "${recorded_anvil:-not recorded}"
fi

if [[ -z "$binary" || ! -x "$binary" ]]; then
  printf 'OpenCode runtime       not installed\n'
  printf 'Runtime policy         OpenCode 1.x (minimum %s)\n' "$policy_minimum"
  if python3 "$ROOT/scripts/version_docs.py" >/dev/null 2>&1; then
    printf 'Release artifacts      valid\n'
  else
    anvil_warn 'Release documentation does not match this checkout.'
  fi
  if (( databricks_probe_status != 0 )); then
    anvil_warn "Databricks status could not be completed (exit $databricks_probe_status)."
  fi
  case "$lifecycle_status" in
    UNSUPPORTED)
      anvil_error 'Installed Anvil/runtime state is outside the supported migration policy; use a compatible checkout and runtime.'
      printf '\nStatus: UNSUPPORTED\n'
      exit 1 ;;
    RECOVERY_REQUIRED)
      anvil_warn 'A lifecycle transaction was interrupted. Close OpenCode and rerun the interrupted lifecycle command to restore its verified snapshot.'
      printf '\nStatus: RECOVERY REQUIRED\n'
      exit 2 ;;
    TRANSITION_IN_PROGRESS)
      anvil_warn 'An Anvil lifecycle command is still running. Wait for it to finish before starting another operation.'
      printf '\nStatus: TRANSITION IN PROGRESS\n'
      exit 2 ;;
    CORRUPTED)
      anvil_error 'Managed Anvil state is corrupted; review the lifecycle findings above before using it.'
      printf '\nStatus: BROKEN\n'
      exit 1 ;;
    PARTIALLY_INSTALLED)
      printf '\nStatus: PARTIALLY INSTALLED\n'
      exit 2 ;;
    *)
      anvil_warn "Anvil can be configured on first use; run 'make reforge' to install the approved runtime."
      printf '\nStatus: NOT INSTALLED\n'
      exit 0 ;;
  esac
fi

printf 'OpenCode version        %s\n' "$normalized"
printf 'OpenCode runtime        %s (%s)\n' "${major:-unknown}" "${major:+opencode-v$major}"
printf 'Runtime policy          OpenCode 1.x (minimum %s)\n' "$policy_minimum"
if [[ "$lifecycle_status" == UNSUPPORTED ]]; then
  anvil_error 'Installed Anvil/runtime state is outside the supported migration policy; automatic downgrade or migration is blocked.'
  printf '\nStatus: UNSUPPORTED\n'
  exit 1
elif [[ "$lifecycle_status" == RECOVERY_REQUIRED ]]; then
  anvil_warn 'A lifecycle transaction was interrupted. Close OpenCode and rerun the interrupted lifecycle command to restore its verified snapshot.'
  printf '\nStatus: RECOVERY REQUIRED\n'
  exit 2
elif [[ "$lifecycle_status" == TRANSITION_IN_PROGRESS ]]; then
  anvil_warn 'An Anvil lifecycle command is still running. Wait for it to finish before starting another operation.'
  printf '\nStatus: TRANSITION IN PROGRESS\n'
  exit 2
fi
if [[ "$lifecycle_status" == PARTIALLY_INSTALLED && ! -f "$ANVIL_CONFIG_DIR/opencode.jsonc" ]]; then
  anvil_warn "OpenCode $normalized is present but the managed Anvil config is missing. Run 'make reforge' to complete installation."
  printf '\nStatus: PARTIALLY INSTALLED\n'
  exit 2
fi
broken=0
warning=0
if [[ "$lifecycle_status" == CORRUPTED ]]; then broken=1; fi
if [[ "$lifecycle_status" == DEGRADED ]]; then warning=1; fi
if (( databricks_probe_status != 0 )); then warning=1; fi
if [[ "$supported" != True ]]; then
  anvil_error "OpenCode runtime major ${major:-unknown} is not supported by this Anvil release."
  broken=1
fi
if [[ -n "$minimum" && "$normalized" != unknown ]]; then
  if ! python3 - "$normalized" "$minimum" <<'PY'
import sys
def version(s): return tuple(int(x) for x in s.split('.'))
raise SystemExit(0 if version(sys.argv[1]) >= version(sys.argv[2]) else 1)
PY
  then
    anvil_error "OpenCode $normalized is below the Anvil-supported minimum $minimum."
    broken=1
  fi
fi

if [[ -L "$ANVIL_CONFIG_DIR/opencode.jsonc" ]]; then
  anvil_error 'The managed OpenCode profile is a symbolic link; doctor will not follow it.'
  printf '\nStatus: BROKEN\n'
  exit 1
fi

config_major=""
audit_suffix=""
if [[ "$recorded_anvil" != "$expected_anvil" ]]; then audit_suffix="-compatible"; fi
if python3 "$ROOT/scripts/configure.py" "audit${audit_suffix}" "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  config_major=1
else
  anvil_error 'Global config is not a valid Anvil OpenCode 1 profile.'
  broken=1
fi
if [[ -n "$config_major" && "$config_major" != "$major" ]]; then
  anvil_error "OpenCode $major executable does not match the OpenCode $config_major Anvil config; run 'make reforge' to rebuild the current runtime profile."
  broken=1
fi
if [[ -n "$recorded_opencode" && "$normalized" != "$recorded_opencode" ]]; then
  anvil_warn "Installed OpenCode reports $normalized; installation metadata records $recorded_opencode."
  warning=1
fi
if [[ -n "$recorded_major" && "$recorded_major" != "$major" ]]; then
  anvil_warn "Runtime metadata records OpenCode $recorded_major; the active executable is OpenCode $major."
  warning=1
fi

if [[ "$lifecycle_status" == RECOVERABLE ]]; then
  printf 'Runtime profile        opencode-v%s config is valid and supported\n' "$major"
  anvil_warn 'An Anvil-managed file has a checksum-pinned replacement in the target release. Run make upgrade; the current file will be preserved for rollback.'
  printf '\nStatus: UPGRADE AVAILABLE (managed drift is recoverable)\n'
  exit 0
fi

# A valid prior Anvil config remains usable. Explain the product upgrade before
# comparing a legacy installation record with the checkout's release version.
if (( broken == 0 )) && [[ "$recorded_anvil" != "$expected_anvil" ]]; then
  printf 'Runtime profile        opencode-v%s config is valid and supported\n' "$major"
  anvil_warn "This checkout can upgrade Anvil from ${recorded_anvil:-the unrecorded V1 baseline} without changing OpenCode $major. Run 'make upgrade' when ready."
  printf '\nStatus: UPGRADE AVAILABLE\n'
  exit 0
fi

if (( broken == 0 )); then
  data_status=0
  python3 "$ROOT/scripts/doctor_data.py" --config-dir "$ANVIL_CONFIG_DIR" \
    --data-dir "$ANVIL_DATA_HOME" --cwd "$PWD" \
    --observation-stdin <<<"$observation" || data_status=$?
  case "$data_status" in
    1) broken=1 ;;
    2) warning=1 ;;
    *) ;;
  esac
fi

path_binary="$(type -P opencode 2>/dev/null || true)"
if [[ -n "$path_binary" && "$path_binary" != "$ANVIL_INSTALLED_BINARY" && "$binary" == "$ANVIL_INSTALLED_BINARY" ]]; then
  anvil_warn "PATH resolves OpenCode to $path_binary instead of the Anvil-managed executable"
  warning=1
fi
if [[ "$runtime_path_ready" == no ]]; then
  anvil_warn "OpenCode is usable through its validated absolute path but its directory is not in this session's PATH."
  warning=1
fi

if (( broken == 0 )) && [[ "${ANVIL_SKIP_RUNTIME_PROBE:-0}" != 1 ]]; then
  printf '\nRuntime smoke test\n'
  if bash "$ROOT/scripts/validate-candidate.sh" "$binary" "$ANVIL_CONFIG_DIR" "$normalized"; then
    printf '  runtime adapter       active\n'
  else
    anvil_error "OpenCode $major could not load the configured Anvil profile, commands and skills."
    broken=1
  fi
else
  printf '\nRuntime smoke test     skipped\n'
  if [[ "${ANVIL_SKIP_RUNTIME_PROBE:-0}" != 1 ]]; then warning=1; fi
fi

if (( broken )); then
  printf '\nStatus: BROKEN\n'
  exit 1
elif (( warning )); then
  printf '\nStatus: WARNING\n'
  exit 2
fi
printf '\nStatus: HEALTHY\n'
