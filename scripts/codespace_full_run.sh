#!/bin/bash
# Backwards-compatible wrapper — calls setup then runtime.
# New projects should use codespace_setup.sh (postCreate) and codespace_runtime.sh (postStart).
set -u
echo "=== codespace_full_run.sh (wrapper) ==="
bash scripts/codespace_setup.sh
echo ""
bash scripts/codespace_runtime.sh
