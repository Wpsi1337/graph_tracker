#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$( cd -- "$( dirname -- "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
VENV_DIR="${SCRIPT_DIR}/.venv"

if [[ ! -d "${VENV_DIR}" ]]; then
  echo "Virtual environment not found at ${VENV_DIR}. Run 'python -m venv .venv' first." >&2
  exit 1
fi

if [[ ! -x "${VENV_DIR}/bin/python" ]]; then
  echo "Python executable missing from virtual environment (${VENV_DIR}/bin/python)." >&2
  exit 1
fi

source "${VENV_DIR}/bin/activate"
cd "${SCRIPT_DIR}"
exec python -m poe_tracker "$@"
