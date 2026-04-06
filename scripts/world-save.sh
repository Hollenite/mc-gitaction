#!/bin/bash
# world-save.sh - Save world to Google Drive (with pre-upload verification + two-file swap)

echo "[WORLD] Saving world..."
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json

# Create tar from world folders
cd server-run
tar czf /tmp/world.tar.gz world/ world_nether/ world_the_end/ 2>/dev/null || \
tar czf /tmp/world.tar.gz world/ 2>/dev/null
cd ..

FILESIZE=$(stat -c%s /tmp/world.tar.gz 2>/dev/null || echo "0")
echo "[WORLD] Archive: $((FILESIZE / 1024 / 1024)) MB"

# Upload with verification + swap (handled by gdrive.py)
echo "[WORLD] Uploading to Google Drive (safe two-file swap)..."
python3 scripts/gdrive.py upload /tmp/world.tar.gz

if [ $? -eq 0 ]; then
    echo "[WORLD] ✅ World saved!"
else
    echo "[WORLD] ❌ Save failed! Previous backup on Drive is still intact."
fi

rm -f /tmp/world.tar.gz
