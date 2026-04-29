import discord
from discord import app_commands
import aiohttp
import asyncio
import os
import json
from datetime import datetime, timezone

# ─── Configuration ─────────────────────────────────────────
BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
GITHUB_TOKEN = os.environ.get("GH_PAT", "")
GITHUB_REPO = os.environ.get("GITHUB_REPO", "Hollenite/mc-gitaction")
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0"))
CHANNEL_ID = int(os.environ.get("DISCORD_CHANNEL_ID", "0"))
PLAYIT_ADDRESS = os.environ.get("PLAYIT_ADDRESS", "wiring-funding.gl.joinmc.link")
CMD_PREFIX = "RCON::"

# ─── Bot Setup ─────────────────────────────────────────────
intents = discord.Intents.default()


class MCBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.session: aiohttp.ClientSession = None

    async def setup_hook(self):
        self.session = aiohttp.ClientSession()
        guild = discord.Object(id=GUILD_ID)
        self.tree.copy_global_to(guild=guild)
        await self.tree.sync(guild=guild)
        print(f"[BOT] Synced commands to guild {GUILD_ID}")

    async def on_ready(self):
        print(f"[BOT] Logged in as {self.user} (ID: {self.user.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="Minecraft Server"
            )
        )

    async def close(self):
        if self.session:
            await self.session.close()
        await super().close()


bot = MCBot()


# ─── Helper Functions ──────────────────────────────────────

async def get_workflow_status():
    """Check if any minecraft workflow is currently running."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?status=in_progress"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with bot.session.get(url, headers=headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            runs = data.get("workflow_runs", [])
            mc_runs = [r for r in runs if "minecraft" in r.get("name", "").lower()]
            if mc_runs:
                run = mc_runs[0]
                return {
                    "running": True,
                    "run_id": run["id"],
                    "started_at": run.get("run_started_at", ""),
                    "url": run["html_url"]
                }
    return {"running": False}


async def trigger_workflow():
    """Trigger the minecraft server workflow."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/minecraft.yml/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": "main", "inputs": {"action": "start"}}
    async with bot.session.post(url, headers=headers, json=payload) as resp:
        return resp.status == 204


async def cancel_workflow(run_id):
    """Cancel a running workflow."""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/cancel"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with bot.session.post(url, headers=headers) as resp:
        return resp.status == 202


async def is_shutting_down():
    """Check recent Discord messages for shutdown indicators."""
    channel = bot.get_channel(CHANNEL_ID)
    if not channel:
        return False
    try:
        shutdown_keywords = ["Auto-Shutdown", "Server Stopping", "Runtime Limit",
                            "Server Crashed", "Server Stopped", "Saving world"]
        async for msg in channel.history(limit=8):
            if msg.author.id != bot.user.id:
                continue
            # Check embeds
            for emb in msg.embeds:
                if emb.title and any(kw in emb.title for kw in shutdown_keywords):
                    return True
            # Check plain messages
            if any(kw.lower() in msg.content.lower() for kw in shutdown_keywords):
                return True
    except Exception:
        pass
    return False


def make_embed(title, description, color=0x3498db, fields=None, footer=None):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text=footer or "MC Server Bot")
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    return embed


# ─── Slash Commands ────────────────────────────────────────

@bot.tree.command(name="start", description="🟢 Start the Minecraft server")
async def start_server(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()
    if status["running"]:
        # Check if the server is actually shutting down
        shutting_down = await is_shutting_down()

        if shutting_down:
            embed = make_embed(
                "⏳ Server is Closing",
                "The server is currently shutting down and saving the world.\n\n"
                "Please wait a moment and try `/start` again once it's fully stopped.",
                color=0xe67e22,
                fields=[
                    ("💾 Status", "Saving world to Google Drive...", True),
                    ("⏱️ Wait", "~2-3 minutes", True),
                    ("🔗 Logs", f"[View Progress]({status.get('url', '#')})", True),
                ]
            )
            await interaction.followup.send(embed=embed)
            return

        started = status.get("started_at", "unknown")
        try:
            start_dt = datetime.fromisoformat(started.replace("Z", "+00:00"))
            delta = datetime.now(timezone.utc) - start_dt
            h, r = divmod(int(delta.total_seconds()), 3600)
            m, s = divmod(r, 60)
            uptime = f"{h}h {m}m {s}s"
        except Exception:
            uptime = "Unknown"

        embed = make_embed(
            "⚠️ Server Already Running",
            f"The server is already online!",
            color=0xf39c12,
            fields=[
                ("🌐 IP", f"`{PLAYIT_ADDRESS}`", False),
                ("⏱️ Uptime", uptime, True),
                ("🔗 Actions", f"[View Logs]({status.get('url', '#')})", True),
            ]
        )
        await interaction.followup.send(embed=embed)
        return

    success = await trigger_workflow()
    if success:
        embed = make_embed(
            "🚀 Server Starting!",
            "The Minecraft server is booting up...\n\n"
            "⏳ **Estimated time:** ~2-3 minutes\n"
            f"🌐 **IP:** `{PLAYIT_ADDRESS}`\n\n"
            "You'll receive a notification when it's ready!",
            color=0x2ecc71,
            fields=[
                ("⛏️ Version", "Paper 1.21.11", True),
                ("👥 Max Players", "10", True),
                ("🔌 Auto-Shutdown", "10 min if empty", True),
                ("🎮 Gamemode", "Survival", True),
                ("⏱️ Max Runtime", "5.5 hours", True),
                ("💾 World", "Auto-saved to Drive", True),
            ]
        )
        await interaction.followup.send(embed=embed)
    else:
        embed = make_embed(
            "❌ Failed to Start",
            "Could not trigger the server workflow.\n"
            "Check GitHub Actions permissions or try again.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="stop", description="🔴 Stop the Minecraft server (saves world)")
async def stop_server(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()
    if not status["running"]:
        embed = make_embed(
            "ℹ️ Server Not Running",
            "The server is already offline. Use `/start` to boot it up.",
            color=0x95a5a6
        )
        await interaction.followup.send(embed=embed)
        return

    success = await cancel_workflow(status["run_id"])
    if success:
        embed = make_embed(
            "🛑 Server Stopping",
            "Saving world to Google Drive and shutting down...\n"
            "The world will be preserved for next time.",
            color=0xe74c3c,
            fields=[
                ("💾 World Save", "In progress...", True),
                ("🔄 Restart", "Use `/start` when you want to play", True),
            ]
        )
        await interaction.followup.send(embed=embed)
    else:
        embed = make_embed(
            "❌ Failed to Stop",
            "Could not cancel the workflow. Try again.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="status", description="📊 Detailed server status")
async def server_status(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()

    if status["running"]:
        started_at = status.get("started_at", "")
        uptime_str = "Unknown"
        time_left = "Unknown"
        if started_at:
            try:
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - start_dt
                elapsed = int(delta.total_seconds())
                h, r = divmod(elapsed, 3600)
                m, s = divmod(r, 60)
                uptime_str = f"{h}h {m}m {s}s"
                remaining = max(0, 19800 - elapsed)
                rh, rr = divmod(remaining, 3600)
                rm, rs = divmod(rr, 60)
                time_left = f"{rh}h {rm}m"
            except Exception:
                pass

        # Try to find player info from recent monitor messages
        player_info = "Use `/players` for live count"
        channel = bot.get_channel(CHANNEL_ID)
        if channel:
            try:
                async for msg in channel.history(limit=15):
                    if msg.author.id == bot.user.id and msg.embeds:
                        for emb in msg.embeds:
                            if emb.title and ("joined" in emb.title or "left" in emb.title):
                                if emb.description:
                                    player_info = emb.description
                                break
            except Exception:
                pass

        embed = make_embed(
            "🟢 Server is ONLINE",
            f"The Minecraft server is running!",
            color=0x2ecc71,
            fields=[
                ("🌐 IP", f"`{PLAYIT_ADDRESS}`", False),
                ("👥 Players", player_info, False),
                ("⛏️ Version", "Paper 1.21.11", True),
                ("⏱️ Uptime", uptime_str, True),
                ("⏰ Time Left", time_left, True),
                ("🎮 Gamemode", "Survival", True),
                ("🔌 Auto-Shutdown", "10 min if empty", True),
                ("💾 World Backup", "Google Drive", True),
                ("🔗 Logs", f"[Actions]({status.get('url', '#')})", True),
            ],
            footer=f"Server ID: {status.get('run_id', 'N/A')}"
        )
    else:
        embed = make_embed(
            "🔴 Server is OFFLINE",
            f"Use `/start` to boot up the server!\n\n"
            f"🌐 **IP (when online):** `{PLAYIT_ADDRESS}`\n"
            f"⛏️ **Version:** Paper 1.21.11\n"
            f"🎮 **Gamemode:** Survival\n"
            f"💾 **World:** Saved on Google Drive",
            color=0xe74c3c,
            fields=[
                ("How to Play", "1. Type `/start`\n2. Wait ~2 min\n3. Connect to the IP above", False),
            ]
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="cmd", description="🔧 Execute a server console command")
@app_commands.describe(command="The Minecraft command to execute (e.g., 'give Steve diamond 64')")
async def run_command(interaction: discord.Interaction, command: str):
    await interaction.response.defer()

    # Check if server is running
    status = await get_workflow_status()
    if not status["running"]:
        embed = make_embed(
            "❌ Server Offline",
            "Cannot run commands — the server is not running.\nUse `/start` first.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)
        return

    # Strip leading slash if user added one
    command = command.lstrip("/")

    # Send the command to the channel for the monitor to pick up
    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        cmd_msg = await channel.send(f"{CMD_PREFIX}{command}")
        embed = make_embed(
            "🔧 Command Queued",
            f"```\n{command}\n```\n"
            "Waiting for server to execute...\n"
            "Response will appear as a reply below.",
            color=0x9b59b6,
            fields=[
                ("⏳ Wait Time", "~10 seconds", True),
                ("📋 Command ID", cmd_msg.id, True),
            ]
        )
        await interaction.followup.send(embed=embed)
    else:
        embed = make_embed(
            "❌ Error",
            "Could not find the server channel.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="ip", description="🌐 Get the server IP address")
async def server_ip(interaction: discord.Interaction):
    embed = make_embed(
        "🌐 Server Address",
        f"```\n{PLAYIT_ADDRESS}\n```\n"
        "**How to connect:**\n"
        "1. Open Minecraft 1.21.11\n"
        "2. Go to Multiplayer → Add Server\n"
        "3. Paste the address above\n\n"
        "⚠️ Server must be running (`/start`) to connect.",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="players", description="👥 Show online players")
async def show_players(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()
    if not status["running"]:
        embed = make_embed(
            "🔴 Server Offline",
            "No players — server is not running.\nUse `/start` to boot it up.",
            color=0x95a5a6
        )
        await interaction.followup.send(embed=embed)
        return

    # Find latest player info from monitor messages
    channel = bot.get_channel(CHANNEL_ID)
    player_list = None
    player_count = "Unknown"

    if channel:
        try:
            async for msg in channel.history(limit=30):
                if msg.author.id == bot.user.id and msg.embeds:
                    for emb in msg.embeds:
                        if emb.title and ("joined" in emb.title or "left" in emb.title or "ONLINE" in emb.title):
                            if emb.description and "Players online" in emb.description:
                                player_list = emb.description
                                break
                            for field in (emb.fields or []):
                                if "Players" in field.name:
                                    player_count = field.value
                                    break
                if player_list:
                    break
        except Exception:
            pass

    if player_list:
        embed = make_embed(
            "👥 Online Players",
            player_list,
            color=0x2ecc71,
            fields=[
                ("🌐 IP", f"`{PLAYIT_ADDRESS}`", False),
            ]
        )
    else:
        embed = make_embed(
            "👥 Players",
            f"Players: {player_count}\n\n"
            "Tip: Use `/cmd list` for real-time player info.",
            color=0x3498db
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="say", description="📢 Broadcast a message to all players in-game")
@app_commands.describe(message="Message to broadcast")
async def say_ingame(interaction: discord.Interaction, message: str):
    await interaction.response.defer()

    status = await get_workflow_status()
    if not status["running"]:
        embed = make_embed("❌ Server Offline", "Server is not running.", color=0xe74c3c)
        await interaction.followup.send(embed=embed)
        return

    channel = bot.get_channel(CHANNEL_ID)
    if channel:
        await channel.send(f'{CMD_PREFIX}say [Discord] {interaction.user.display_name}: {message}')
        embed = make_embed(
            "📢 Message Sent",
            f"**{interaction.user.display_name}**: {message}",
            color=0x2ecc71
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="help", description="❓ Show all commands")
async def help_cmd(interaction: discord.Interaction):
    embed = make_embed(
        "⛏️ Minecraft Server Bot",
        "Control the Paper 1.21.11 server from Discord!",
        color=0x9b59b6,
        fields=[
            ("🟢 /start", "Boot up the server (~2 min)", False),
            ("🔴 /stop", "Save world and shut down", False),
            ("📊 /status", "Detailed server status", False),
            ("👥 /players", "Show online players", False),
            ("🌐 /ip", "Get the server IP address", False),
            ("🔧 /cmd", "Run a console command (e.g., `/cmd give Steve diamond 64`)", False),
            ("📢 /say", "Broadcast a message to in-game players", False),
            ("❓ /help", "Show this help message", False),
        ]
    )
    embed.add_field(
        name="━━━ ℹ️ Server Info ━━━",
        value=f"🌐 IP: `{PLAYIT_ADDRESS}`\n"
              "⛏️ Version: Paper 1.21.11\n"
              "🔌 Auto-shutdown: 10 min with no players\n"
              "⏱️ Max runtime: 5.5 hours per session\n"
              "💾 World: Auto-saved to Google Drive",
        inline=False
    )
    await interaction.response.send_message(embed=embed)


# ─── Run ───────────────────────────────────────────────────

if __name__ == "__main__":
    if not BOT_TOKEN:
        print("ERROR: DISCORD_BOT_TOKEN not set!")
        exit(1)
    if not GITHUB_TOKEN:
        print("ERROR: GH_PAT not set!")
        exit(1)
    print("[BOT] Starting...")
    bot.run(BOT_TOKEN)
