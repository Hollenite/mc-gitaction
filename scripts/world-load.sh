#!/bin/bash
# world-load.sh - Download world from Google Drive

echo "[WORLD] Setting up Google Drive access..."
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json
pip install -q google-api-python-client google-auth

echo "[WORLD] Checking for world backup..."
python3 scripts/gdrive.py download /tmp/world.tar.gz

if [ -f /tmp/world.tar.gz ] && [ $(stat -c%s /tmp/world.tar.gz) -gt 1000 ]; then
    echo "[WORLD] Extracting world..."
    cd server-run
    tar xzf /tmp/world.tar.gz
    cd ..
    rm /tmp/world.tar.gz
    echo "[WORLD] World loaded!"
    ls -la server-run/world/ 2>/dev/null | head -5
else
    echo "[WORLD] No backup found. Starting with fresh world."
fi
