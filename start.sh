#!/usr/bin/env bash
# Starts the API. The browser (Chromium + Xvfb) is launched by the app itself
# so it shares this container, this process tree and this egress IP.
set -euo pipefail

echo "starting perchance-mcp on :${PORT:-8080}"
exec python -m app.main
