#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
cd "$SCRIPT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python}"
DEFAULT_LEAGUE="${POE_LEAGUE:-Rise of the Abyssal}"
DEFAULT_CATEGORY="${POE_CATEGORY:-Currency}"
DEFAULT_GAME="${POE_GAME:-poe2}"
DEFAULT_LIMIT="${POE_LIMIT:-40}"
DEFAULT_INTERVAL="${POE_INTERVAL:-120}"
DEFAULT_COOKIE="${POE_NINJA_COOKIE:-${POE_COOKIE:-}}"

ARGS=(
  "--league" "${DEFAULT_LEAGUE}"
  "--category" "${DEFAULT_CATEGORY}"
  "--game" "${DEFAULT_GAME}"
  "--limit" "${DEFAULT_LIMIT}"
  "--interval" "${DEFAULT_INTERVAL}"
)

if [[ -n "$DEFAULT_COOKIE" ]]; then
  ARGS+=( "--ninja-cookie" "$DEFAULT_COOKIE" )
fi

exec "$PYTHON_BIN" -m poe_tracker "${ARGS[@]}" "$@"
