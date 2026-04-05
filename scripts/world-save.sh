#!/bin/bash
# world-save.sh - Save world to Google Drive

echo "[WORLD] Saving world..."
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json

# Tar the world folders
cd server-run
tar czf /tmp/world.tar.gz world/ world_nether/ world_the_end/ 2>/dev/null || \
tar czf /tmp/world.tar.gz world/ 2>/dev/null
cd ..

FILESIZE=$(stat -c%s /tmp/world.tar.gz 2>/dev/null || echo "0")
echo "[WORLD] World archive: $((FILESIZE / 1024 / 1024)) MB"

# Upload (UPDATES existing file, keeps user's ownership = no quota issue)
echo "[WORLD] Uploading to Google Drive..."
python3 scripts/gdrive.py upload /tmp/world.tar.gz

rm -f /tmp/world.tar.gz
echo "[WORLD] World saved!"
