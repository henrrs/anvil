#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"
anvil_need python3

expected_anvil="$(cat "$ROOT/VERSION")"
binary=""
if [[ -x "$ANVIL_INSTALLED_BINARY" ]]; then
  binary="$ANVIL_INSTALLED_BINARY"
else
  binary="$(command -v opencode 2>/dev/null || true)"
fi
record_file="$ANVIL_DATA_DIR/installation.json"
recorded_opencode=""
recorded_anvil=""
if [[ -f "$record_file" ]]; then
  IFS=$'\t' read -r recorded_opencode recorded_anvil < <(python3 - "$record_file" <<'PY'
import json,sys
try:
    value=json.load(open(sys.argv[1],encoding="utf-8"))
except (OSError,ValueError):
    value={}
print(f"{value.get('version', '')}\t{value.get('anvil_version', '')}")
PY
)
fi

broken=0
warning=0
printf '%s\n' 'Anvil Doctor' '────────────'
printf 'Anvil version          %s' "$expected_anvil"
if [[ "$recorded_anvil" != "$expected_anvil" ]]; then
  printf ' (recorded %s)\n' "${recorded_anvil:-missing}"
  anvil_error 'installed Anvil version record does not match this repository release'
  broken=1
else
  printf ' (installed)\n'
fi
if [[ -z "$binary" || ! -x "$binary" ]]; then
  printf 'OpenCode version        missing\nOpenCode generation     missing\n'
  anvil_error 'OpenCode executable not found'
  broken=1
else
  version="$("$binary" --version 2>/dev/null | head -n 1)"
  normalized="${version#opencode }"
  normalized="${normalized#v}"
  major="${normalized%%.*}"
  printf 'OpenCode version        %s\nOpenCode generation     %s\n' "$normalized" "${major:-unknown}"
  if [[ "$major" != 2 ]]; then
    anvil_error 'Anvil 2 requires OpenCode 2'
    broken=1
  fi
  if [[ -z "$recorded_opencode" || "$normalized" != "$recorded_opencode" ]]; then
    anvil_error 'installed OpenCode version differs from installation.json'
    broken=1
  fi
fi

if ! python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc"; then
  broken=1
fi
printf '\n'
doctor_data_status=0
python3 "$ROOT/scripts/doctor_data.py" --config-dir "$ANVIL_CONFIG_DIR" \
  --data-dir "$ANVIL_DATA_HOME" --cwd "$PWD" || doctor_data_status=$?
case "$doctor_data_status" in
  1) broken=1 ;;
  2) warning=1 ;;
  *) ;;
esac

path_binary="$(type -P opencode 2>/dev/null || true)"
if [[ -n "$path_binary" && "$path_binary" != "$ANVIL_INSTALLED_BINARY" ]]; then
  anvil_warn "PATH resolves OpenCode to $path_binary instead of the Anvil-managed executable"
  warning=1
fi

if [[ -n "$binary" && -x "$binary" && "${ANVIL_SKIP_RUNTIME_PROBE:-0}" != 1 ]]; then
  printf '\nRuntime smoke test\n'
  if bash "$ROOT/scripts/validate-candidate.sh" "$binary" "$ANVIL_CONFIG_DIR" "$normalized"; then
    printf '  plugin/tool runtime   active\n'
  else
    anvil_error 'OpenCode could not load the configured Anvil agent, plugin, commands, skills and reference'
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
