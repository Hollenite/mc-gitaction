#!/bin/bash
# world-load.sh - Download world from Google Drive (with corruption fallback)

echo "[WORLD] Setting up Google Drive..."
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json

echo "[WORLD] Downloading world..."
python3 scripts/gdrive.py download /tmp/world.tar.gz

if [ $? -eq 0 ] && [ -f /tmp/world.tar.gz ]; then
    echo "[WORLD] Extracting..."
    cd server-run
    tar xzf /tmp/world.tar.gz
    if [ -d "world" ] && [ -f "world/level.dat" ]; then
        echo "[WORLD] ✅ World loaded!"
        ls -la world/ | head -5
    else
        echo "[WORLD] ⚠️ level.dat missing after extraction. Starting fresh."
    fi
    cd ..
    rm -f /tmp/world.tar.gz
else
    echo "[WORLD] No valid backup found. Starting fresh."
fi
