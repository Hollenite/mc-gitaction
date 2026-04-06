#!/bin/bash
# world-load.sh - Download world from Google Drive with corruption guard

echo "[WORLD] Setting up Google Drive access..."
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json
pip install -q google-api-python-client google-auth

echo "[WORLD] Checking for world backup..."
python3 scripts/gdrive.py download /tmp/world.tar.gz

if [ -f /tmp/world.tar.gz ] && [ $(stat -c%s /tmp/world.tar.gz) -gt 1000 ]; then
    # Verify tar integrity before extracting
    echo "[WORLD] Verifying archive integrity..."
    if gzip -t /tmp/world.tar.gz 2>/dev/null; then
        echo "[WORLD] Archive OK. Extracting..."
        cd server-run
        tar xzf /tmp/world.tar.gz
        # Verify world folder exists after extraction
        if [ -d "world" ] && [ -f "world/level.dat" ]; then
            echo "[WORLD] ✅ World loaded successfully!"
            ls -la world/ | head -5
        else
            echo "[WORLD] ⚠️ Extraction succeeded but world/level.dat missing. Starting fresh."
        fi
        cd ..
    else
        echo "[WORLD] ❌ Archive is CORRUPTED! Starting with fresh world to avoid data loss."
        echo "[WORLD] The corrupted file will be overwritten on next save."
    fi
    rm -f /tmp/world.tar.gz
else
    echo "[WORLD] No backup found. Starting with fresh world."
fi
