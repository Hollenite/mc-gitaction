#!/bin/bash
# world-load.sh - Download world from Google Drive via rclone

echo "[WORLD] Setting up rclone for Google Drive..."

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
team_drive =
EOF

echo "[WORLD] Checking for world backup on Google Drive..."

# List files in drive folder
rclone ls gdrive: 2>/dev/null | head -5

# Check if world.tar.gz exists on drive
if rclone lsf gdrive: 2>/dev/null | grep -q "world.tar.gz"; then
    echo "[WORLD] Found world backup, downloading..."
    rclone copy gdrive:world.tar.gz /tmp/ --progress --drive-acknowledge-abuse

    if [ -f /tmp/world.tar.gz ] && [ $(stat -c%s /tmp/world.tar.gz) -gt 1000 ]; then
        echo "[WORLD] Extracting world..."
        cd server-run
        tar xzf /tmp/world.tar.gz
        cd ..
        rm /tmp/world.tar.gz
        echo "[WORLD] World loaded successfully!"
        ls -la server-run/world/ 2>/dev/null | head -5
    else
        echo "[WORLD] Download failed or file too small, starting fresh."
    fi
else
    echo "[WORLD] No world backup found on Drive. Starting with fresh world."
fi
