#!/usr/bin/env bash
# Runs every check that does not need a device or an emulator.
#
#   tools/run-tests.sh
#
# Covers the embedded Python modules, the WebView JavaScript, and a debug
# build with Android Lint. Set PYTHON to point at a CPython 3.13 if it is not
# on PATH as python3.13.
set -euo pipefail

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-python3.13}"

echo "== Python engine =="
"$PYTHON" tools/test_runtime.py

echo
echo "== WebView JavaScript =="
node tools/test_js.js

echo
echo "== Build and lint =="
./gradlew :app:assembleDebug :app:lintDebug --console=plain

echo
echo "All checks passed."
