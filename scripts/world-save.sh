#!/bin/bash
# world-save.sh - Save world to GitHub Release

echo "[WORLD] Saving world..."

# Tar the world folders
cd server-run
tar czf /tmp/world.tar.gz world/ world_nether/ world_the_end/ 2>/dev/null || \
tar czf /tmp/world.tar.gz world/ 2>/dev/null
cd ..

FILESIZE=$(stat -c%s /tmp/world.tar.gz 2>/dev/null || echo "0")
echo "[WORLD] World archive size: $((FILESIZE / 1024 / 1024)) MB"

# Check if release exists
RELEASE_INFO=$(curl -s -H "Authorization: token ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/${REPO}/releases/tags/world-backup")

RELEASE_ID=$(echo "$RELEASE_INFO" | grep -oP '"id":\s*\K\d+' | head -1)

if [ -z "$RELEASE_ID" ] || [ "$RELEASE_ID" = "null" ]; then
    echo "[WORLD] Creating new release..."
    RELEASE_INFO=$(curl -s -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/json" \
        "https://api.github.com/repos/${REPO}/releases" \
        -d '{
            "tag_name": "world-backup",
            "name": "World Backup",
            "body": "Automatic world backup from Minecraft server",
            "draft": false,
            "prerelease": false
        }')
    RELEASE_ID=$(echo "$RELEASE_INFO" | grep -oP '"id":\s*\K\d+' | head -1)
    echo "[WORLD] Created release ID: $RELEASE_ID"
else
    echo "[WORLD] Found existing release ID: $RELEASE_ID"
    # Delete old asset
    ASSET_ID=$(echo "$RELEASE_INFO" | grep -oP '"id":\s*\K\d+' | tail -1)
    OLD_ASSETS=$(curl -s -H "Authorization: token ${GITHUB_TOKEN}" \
        "https://api.github.com/repos/${REPO}/releases/${RELEASE_ID}/assets")
    
    # Delete all old assets
    echo "$OLD_ASSETS" | grep -oP '"id":\s*\K\d+' | while read aid; do
        curl -s -X DELETE \
            -H "Authorization: token ${GITHUB_TOKEN}" \
            "https://api.github.com/repos/${REPO}/releases/assets/${aid}"
        echo "[WORLD] Deleted old asset $aid"
    done
fi

# Upload new asset
if [ -n "$RELEASE_ID" ]; then
    echo "[WORLD] Uploading world backup..."
    curl -s -X POST \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/gzip" \
        --data-binary @/tmp/world.tar.gz \
        "https://uploads.github.com/repos/${REPO}/releases/${RELEASE_ID}/assets?name=world.tar.gz"
    echo ""
    echo "[WORLD] World saved successfully!"
else
    echo "[WORLD] ERROR: Could not create/find release!"
fi
