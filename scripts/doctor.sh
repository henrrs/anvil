#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3

expected_anvil="$(cat "$ROOT/VERSION")"
binary="$(anvil_open_code_binary || true)"
record_file="$ANVIL_DATA_DIR/installation.json"
recorded_opencode=""
recorded_anvil=""
recorded_major=""
if [[ -f "$record_file" ]]; then
  IFS=$'\t' read -r recorded_opencode recorded_anvil recorded_major < <(python3 - "$record_file" <<'PY'
import json,sys
try: value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError): value={}
print(f"{value.get('version', '')}\t{value.get('anvil_version', '')}\t{value.get('runtime_major', value.get('generation', ''))}")
PY
)
fi

printf '%s\n' 'Anvil Doctor' '────────────'
printf 'Anvil version          %s' "$expected_anvil"
if [[ "$recorded_anvil" == "$expected_anvil" ]]; then
  printf ' (installed)\n'
else
  printf ' (installed %s)\n' "${recorded_anvil:-not recorded}"
fi

if [[ -z "$binary" || ! -x "$binary" ]]; then
  printf 'OpenCode runtime       not installed\n'
  anvil_warn "Anvil can be configured on first use; run 'make reforge' to install the approved runtime."
  printf '\nStatus: NOT INSTALLED\n'
  exit 0
fi

capability_json="$(python3 "$ROOT/scripts/runtime.py" capabilities --binary "$binary")"
read -r normalized major supported minimum policy_major < <(python3 - "$capability_json" <<'PY'
import json,sys
d=json.loads(sys.argv[1]); r=d['runtime']; p=d['policy']
print(r.get('version') or 'unknown', r.get('major') or '', str(r.get('supported')), r.get('minimum_version') or '', p['default_major'])
PY
)
printf 'OpenCode version        %s\n' "$normalized"
printf 'OpenCode runtime        %s (%s)\n' "${major:-unknown}" "${major:+opencode-v$major}"
printf 'Approved policy major   %s\n' "$policy_major"
broken=0
warning=0
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

config_major=""
if python3 "$ROOT/scripts/configure.py" audit-v1 "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  config_major=1
elif python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc" >/dev/null 2>&1; then
  config_major=2
else
  anvil_error 'Global config is neither a valid Anvil OpenCode 1 profile nor a valid OpenCode 2 profile.'
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
    --data-dir "$ANVIL_DATA_HOME" --cwd "$PWD" --runtime-major "$major" || data_status=$?
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

if (( broken == 0 )) && [[ "${ANVIL_SKIP_RUNTIME_PROBE:-0}" != 1 ]]; then
  printf '\nRuntime smoke test\n'
  if bash "$ROOT/scripts/validate-candidate.sh" "$binary" "$ANVIL_CONFIG_DIR" "$normalized" "$major"; then
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
