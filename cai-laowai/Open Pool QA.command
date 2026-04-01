#!/bin/bash
# Double-click this in Finder to open the manual pool reviewer in your browser.
# Serves this folder (cai-laowai) so photos under assets/ load correctly.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"
PORT="${POOL_QA_PORT:-8765}"
echo "Serving $DIR on http://127.0.0.1:${PORT}/"
echo "Close this window when you're done reviewing."
(sleep 0.5 && open "http://127.0.0.1:${PORT}/pool-qa.html") &
exec python3 -m http.server "$PORT"
