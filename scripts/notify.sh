#!/bin/bash
# notify.sh - Send Discord messages via bot token

send_message() {
    local content="$1"
    curl -s -X POST "https://discord.com/api/v10/channels/${DISCORD_CHANNEL_ID}/messages" \
        -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{\"content\": \"$content\"}" > /dev/null 2>&1
}

send_embed() {
    local title="$1"
    local description="$2"
    local color="${3:-3447003}"

    # Escape special chars for JSON
    description=$(echo "$description" | sed 's/"/\\"/g')

    curl -s -X POST "https://discord.com/api/v10/channels/${DISCORD_CHANNEL_ID}/messages" \
        -H "Authorization: Bot ${DISCORD_BOT_TOKEN}" \
        -H "Content-Type: application/json" \
        -d "{
            \"embeds\": [{
                \"title\": \"$title\",
                \"description\": \"$description\",
                \"color\": $color,
                \"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\"
            }]
        }" > /dev/null 2>&1
}
