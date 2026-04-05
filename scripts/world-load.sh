#!/bin/bash
# world-load.sh - Download world from GitHub Release

echo "[WORLD] Checking for world backup..."

# Try to download from the latest release tagged 'world-backup'
RELEASE_INFO=$(curl -s -H "Authorization: token ${GITHUB_TOKEN}" \
    "https://api.github.com/repos/${REPO}/releases/tags/world-backup")

ASSET_URL=$(echo "$RELEASE_INFO" | grep -oP '"browser_download_url":\s*"\K[^"]+world\.tar\.gz')

if [ -n "$ASSET_URL" ]; then
    echo "[WORLD] Found world backup, downloading..."
    curl -L -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Accept: application/octet-stream" \
        -o /tmp/world.tar.gz \
        "$ASSET_URL"

    if [ -f /tmp/world.tar.gz ] && [ $(stat -c%s /tmp/world.tar.gz) -gt 1000 ]; then
        echo "[WORLD] Extracting world..."
        cd server-run
        tar xzf /tmp/world.tar.gz
        cd ..
        echo "[WORLD] World loaded successfully!"
    else
        echo "[WORLD] Download failed or file too small, starting fresh."
    fi
else
    echo "[WORLD] No world backup found. Starting with fresh world."
fi
