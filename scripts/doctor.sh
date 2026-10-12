#!/usr/bin/env bash

set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
source "$ROOT/scripts/lib/common.sh"

printf '%s\n' 'Anvil Doctor' '────────────────────────────────'
binary=""
if [[ -x "$ANVIL_INSTALLED_BINARY" ]]; then
  binary="$ANVIL_INSTALLED_BINARY"
else
  binary="$(command -v opencode 2>/dev/null || true)"
fi
if [[ -z "$binary" || ! -x "$binary" ]]; then
  printf 'OpenCode\n  version             missing\n  executable          not found\n  supported           no\n\nStatus: BROKEN\n'
  exit 1
fi
version="$("$binary" --version 2>/dev/null | head -n 1)"
version="${version#v}"
version_file="$ANVIL_DATA_DIR/installation.json"
recorded=""
if [[ -f "$version_file" ]]; then
  recorded="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1],encoding="utf-8")).get("version", ""))' "$version_file")"
fi
printf 'OpenCode\n  version             %s\n  executable          %s\n  supported           %s\n' \
  "$version" "$binary" "$([[ -n "$recorded" && "$version" == "$recorded" ]] && printf yes || printf no)"

config_errors=0
if ! python3 "$ROOT/scripts/configure.py" audit "$ANVIL_CONFIG_DIR/opencode.jsonc"; then
  config_errors=1
fi
printf '\n'
doctor_data_status=0
python3 "$ROOT/scripts/doctor_data.py" --config-dir "$ANVIL_CONFIG_DIR" \
  --data-dir "$ANVIL_DATA_HOME" --cwd "$PWD" || doctor_data_status=$?

if [[ -n "$recorded" && "$version" != "$recorded" ]]; then
  printf 'ERROR installed OpenCode version differs from the tested version in installation.json\n'
  config_errors=1
elif [[ -z "$recorded" ]]; then
  printf 'WARN  no Anvil installation record found; run make reforge to establish a verified baseline\n'
  (( doctor_data_status == 0 )) && doctor_data_status=2
fi
path_binary="$(type -P opencode 2>/dev/null || true)"
if [[ "$path_binary" != "$ANVIL_INSTALLED_BINARY" ]]; then
  printf 'WARN  PATH resolves OpenCode to %s instead of the Anvil-managed executable\n' "${path_binary:-nothing}"
  (( doctor_data_status == 0 )) && doctor_data_status=2
fi

if (( config_errors )); then exit 1; fi
exit "$doctor_data_status"
