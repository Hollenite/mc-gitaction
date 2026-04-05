#!/bin/bash
# monitor.sh - Monitor player count and auto-shutdown after 10 min empty

source scripts/notify.sh

LOG_FILE="server-run/logs/latest.log"
EMPTY_SINCE=""
EMPTY_TIMEOUT=600  # 10 minutes in seconds
WARNED=false
MAX_RUNTIME=19800  # 5.5 hours in seconds
START_TIME=$(date +%s)
LAST_PLAYER_COUNT=0
SAVE_INTERVAL=1800  # Auto-save every 30 minutes
LAST_SAVE=$(date +%s)

# Track known players
declare -A ONLINE_PLAYERS

echo "[MONITOR] Starting player monitor..."
echo "[MONITOR] Auto-shutdown after ${EMPTY_TIMEOUT}s with 0 players"
echo "[MONITOR] Max runtime: ${MAX_RUNTIME}s"

while true; do
    sleep 15

    # Check if MC server is still running
    if [ -f /tmp/mc.pid ] && ! kill -0 $(cat /tmp/mc.pid) 2>/dev/null; then
        echo "[MONITOR] Server process died!"
        send_embed "💥 Server Crashed" "The server process has stopped unexpectedly." 16711680
        break
    fi

    NOW=$(date +%s)
    ELAPSED=$((NOW - START_TIME))

    # Check for max runtime (5.5 hours) - save and exit
    if [ $ELAPSED -ge $MAX_RUNTIME ]; then
        echo "[MONITOR] Max runtime reached. Saving and stopping..."
        send_embed "⏰ Runtime Limit" "Server has been running for 5.5 hours. Saving world and shutting down.\nUse **/start** to restart." 16776960
        break
    fi

    # Auto-save every 30 minutes
    if [ $((NOW - LAST_SAVE)) -ge $SAVE_INTERVAL ]; then
        echo "[MONITOR] Auto-saving world..."
        bash scripts/world-save.sh
        LAST_SAVE=$NOW
    fi

    # Parse log for player events (new lines only)
    if [ -f "$LOG_FILE" ]; then
        # Check for joins
        while IFS= read -r line; do
            PLAYER=$(echo "$line" | grep -oP '\w+ joined the game' | grep -oP '^\w+')
            if [ -n "$PLAYER" ] && [ -z "${ONLINE_PLAYERS[$PLAYER]}" ]; then
                ONLINE_PLAYERS[$PLAYER]=1
                COUNT=${#ONLINE_PLAYERS[@]}
                echo "[MONITOR] $PLAYER joined ($COUNT online)"
                send_embed "👋 $PLAYER joined" "Players online: **$COUNT**/10" 65280
                EMPTY_SINCE=""
                WARNED=false
            fi
        done < <(tail -20 "$LOG_FILE" | grep "joined the game")

        # Check for leaves
        while IFS= read -r line; do
            PLAYER=$(echo "$line" | grep -oP '\w+ left the game' | grep -oP '^\w+')
            if [ -n "$PLAYER" ] && [ -n "${ONLINE_PLAYERS[$PLAYER]}" ]; then
                unset ONLINE_PLAYERS[$PLAYER]
                COUNT=${#ONLINE_PLAYERS[@]}
                echo "[MONITOR] $PLAYER left ($COUNT online)"
                send_embed "🚪 $PLAYER left" "Players online: **$COUNT**/10" 16744192
            fi
        done < <(tail -20 "$LOG_FILE" | grep "left the game")

        # Check for deaths
        while IFS= read -r line; do
            if echo "$line" | grep -qP "(was slain|was shot|drowned|blew up|was killed|fell|burned|hit the ground|went up in flames|was frozen|was pricked|tried to swim|starved|suffocated|was impaled|was squashed|was pummeled|walked into)"; then
                DEATH_MSG=$(echo "$line" | grep -oP '\]: \K.*')
                if [ -n "$DEATH_MSG" ]; then
                    send_message "💀 $DEATH_MSG"
                fi
            fi
        done < <(tail -5 "$LOG_FILE" | grep -P "(was slain|was shot|drowned|blew up|was killed|fell|burned|hit the ground|went up in flames)")

        # Check for advancements
        while IFS= read -r line; do
            ADV_MSG=$(echo "$line" | grep -oP '\]: \K.*(?=has made the advancement|has completed the challenge)')
            if [ -n "$ADV_MSG" ]; then
                FULL_MSG=$(echo "$line" | grep -oP '\]: \K.*')
                send_message "🏆 $FULL_MSG"
            fi
        done < <(tail -5 "$LOG_FILE" | grep -P "(has made the advancement|has completed the challenge)")
    fi

    # Count online players
    PLAYER_COUNT=${#ONLINE_PLAYERS[@]}

    # Auto-shutdown logic
    if [ $PLAYER_COUNT -eq 0 ]; then
        if [ -z "$EMPTY_SINCE" ]; then
            EMPTY_SINCE=$NOW
            echo "[MONITOR] Server is empty. Starting shutdown timer..."
        fi

        EMPTY_DURATION=$((NOW - EMPTY_SINCE))

        # Warn at 5 minutes
        if [ $EMPTY_DURATION -ge 300 ] && [ "$WARNED" = false ]; then
            WARNED=true
            send_embed "⚠️ Server Empty" "No players for 5 minutes. Shutting down in **5 minutes**...\nJoin the server to cancel!" 16776960
        fi

        # Shutdown at 10 minutes
        if [ $EMPTY_DURATION -ge $EMPTY_TIMEOUT ]; then
            echo "[MONITOR] Empty for 10 minutes. Shutting down..."
            send_embed "⏹️ Auto-Shutdown" "Server has been empty for 10 minutes. Saving world..." 16744192
            break
        fi
    else
        if [ -n "$EMPTY_SINCE" ]; then
            echo "[MONITOR] Players detected, cancelling shutdown."
            EMPTY_SINCE=""
            WARNED=false
        fi
    fi
done

echo "[MONITOR] Monitor loop ended."
