# Minecraft Server on GitHub Actions

Paper 1.21.1 server running on GitHub Actions, controlled via Discord bot.

## Setup

### 1. GitHub Secrets
Go to repo Settings → Secrets → Actions and add:

| Secret | Value |
|--------|-------|
| `DISCORD_BOT_TOKEN` | Your Discord bot token |
| `DISCORD_CHANNEL_ID` | Channel ID for live notifications |
| `GH_PAT` | GitHub Personal Access Token (actions:write) |
| `PLAYIT_SECRET` | playit.gg agent secret key |

### 2. Discord Bot (on Oracle VM)
```bash
pip3 install -r bot/requirements.txt

export DISCORD_BOT_TOKEN="your_token"
export GH_PAT="your_github_pat"
export GITHUB_REPO="Hollenite/mc-gitaction"
export DISCORD_GUILD_ID="your_guild_id"
export DISCORD_CHANNEL_ID="your_channel_id"
export PLAYIT_ADDRESS="your.ply.gg:port"

python3 bot/bot.py
```

### 3. Initial World Upload
Upload your world as a GitHub Release asset tagged `world-backup`.

## How It Works
1. User types `/start` in Discord
2. Bot triggers GitHub Actions workflow
3. Runner downloads Paper + world, starts server + playit tunnel
4. Discord gets live notifications (joins, leaves, deaths)
5. After 10 min with no players → auto-saves world and shuts down
