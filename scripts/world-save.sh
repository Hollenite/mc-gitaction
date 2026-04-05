#!/bin/bash
# world-save.sh - Save world to Google Drive via rclone

echo "[WORLD] Saving world..."

# Write service account key from env var
echo "$GDRIVE_SERVICE_ACCOUNT_JSON" > /tmp/sa-key.json

# Create rclone config
mkdir -p ~/.config/rclone
cat > ~/.config/rclone/rclone.conf << EOF
[gdrive]
type = drive
scope = drive
service_account_file = /tmp/sa-key.json
root_folder_id = ${GDRIVE_FOLDER_ID}
EOF

# Tar the world folders
cd server-run
tar czf /tmp/world.tar.gz world/ world_nether/ world_the_end/ 2>/dev/null || \
tar czf /tmp/world.tar.gz world/ 2>/dev/null
cd ..

FILESIZE=$(stat -c%s /tmp/world.tar.gz 2>/dev/null || echo "0")
echo "[WORLD] World archive size: $((FILESIZE / 1024 / 1024)) MB"

# Upload to Google Drive (overwrites existing)
echo "[WORLD] Uploading to Google Drive..."
rclone copy /tmp/world.tar.gz gdrive: --progress

echo "[WORLD] World saved to Google Drive!"
rm -f /tmp/world.tar.gz
