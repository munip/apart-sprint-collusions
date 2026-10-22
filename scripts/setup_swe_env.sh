#!/usr/bin/env bash
# Creates the isolated FastAPI checkout + test venv used by the SWE scenario.
# The venv is separate from the project env so agents' code never runs inside the monitor's interpreter.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CACHE="${CLAB_CACHE:-$ROOT/.cache}"
mkdir -p "$CACHE"
[ -d "$CACHE/fastapi/.git" ] || git clone --filter=blob:none https://github.com/fastapi/fastapi "$CACHE/fastapi"
python3 -m venv "$CACHE/fapi-venv"
cd "$CACHE/fastapi"
git checkout -q 43f46fb14feeee78f4077a55eb3f95f792b7cd9d
"$CACHE/fapi-venv/bin/pip" install -q --upgrade pip
"$CACHE/fapi-venv/bin/pip" install -q --group tests pytest-timeout
"$CACHE/fapi-venv/bin/pip" install -q -e . && "$CACHE/fapi-venv/bin/pip" uninstall -y -q fastapi
git checkout -q master
echo "SWE env ready: $CACHE"
