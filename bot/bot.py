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

# ─── Bot Setup ─────────────────────────────────────────────
intents = discord.Intents.default()
intents.message_content = True


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


bot = MCBot()


# ─── Helper Functions ──────────────────────────────────────

async def get_workflow_status():
    """Check if any minecraft workflow is currently running"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs?status=in_progress"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with bot.session.get(url, headers=headers) as resp:
        if resp.status == 200:
            data = await resp.json()
            runs = data.get("workflow_runs", [])
            # Filter for our minecraft workflow
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
    """Trigger the minecraft server workflow"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/workflows/minecraft.yml/dispatches"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    payload = {"ref": "main", "inputs": {"action": "start"}}
    async with bot.session.post(url, headers=headers, json=payload) as resp:
        return resp.status == 204


async def cancel_workflow(run_id):
    """Cancel a running workflow"""
    url = f"https://api.github.com/repos/{GITHUB_REPO}/actions/runs/{run_id}/cancel"
    headers = {
        "Authorization": f"token {GITHUB_TOKEN}",
        "Accept": "application/vnd.github.v3+json"
    }
    async with bot.session.post(url, headers=headers) as resp:
        return resp.status == 202


def make_embed(title, description, color=0x3498db, fields=None):
    embed = discord.Embed(
        title=title,
        description=description,
        color=color,
        timestamp=datetime.now(timezone.utc)
    )
    embed.set_footer(text="MC Server Bot")
    if fields:
        for name, value, inline in fields:
            embed.add_field(name=name, value=value, inline=inline)
    return embed


# ─── Slash Commands ────────────────────────────────────────

@bot.tree.command(name="start", description="🟢 Start the Minecraft server")
async def start_server(interaction: discord.Interaction):
    await interaction.response.defer()

    # Check if already running
    status = await get_workflow_status()
    if status["running"]:
        started = status.get("started_at", "unknown")
        embed = make_embed(
            "⚠️ Server Already Running",
            f"The server is already online!\n\n🌐 **IP:** `{PLAYIT_ADDRESS}`\n⏱️ Started: {started}",
            color=0xf39c12
        )
        await interaction.followup.send(embed=embed)
        return

    # Trigger the workflow
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
                ("Version", "Paper 1.21.1", True),
                ("Max Players", "10", True),
                ("Auto-Shutdown", "10 min empty", True),
            ]
        )
        await interaction.followup.send(embed=embed)
    else:
        embed = make_embed(
            "❌ Failed to Start",
            "Could not trigger the server. Check GitHub Actions permissions.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="stop", description="🔴 Stop the Minecraft server")
async def stop_server(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()
    if not status["running"]:
        embed = make_embed(
            "ℹ️ Server Not Running",
            "The server is already offline.",
            color=0x95a5a6
        )
        await interaction.followup.send(embed=embed)
        return

    success = await cancel_workflow(status["run_id"])
    if success:
        embed = make_embed(
            "🛑 Server Stopping",
            "Saving world and shutting down...\n"
            "The world will be preserved for next time.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)
    else:
        embed = make_embed(
            "❌ Failed to Stop",
            "Could not cancel the workflow. Try again or check GitHub.",
            color=0xe74c3c
        )
        await interaction.followup.send(embed=embed)


@bot.tree.command(name="status", description="📊 Check server status")
async def server_status(interaction: discord.Interaction):
    await interaction.response.defer()

    status = await get_workflow_status()

    if status["running"]:
        started_at = status.get("started_at", "")
        uptime_str = "Unknown"
        if started_at:
            try:
                start_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
                delta = datetime.now(timezone.utc) - start_dt
                hours, remainder = divmod(int(delta.total_seconds()), 3600)
                minutes, seconds = divmod(remainder, 60)
                uptime_str = f"{hours}h {minutes}m {seconds}s"
            except Exception:
                pass

        embed = make_embed(
            "🟢 Server is ONLINE",
            f"The Minecraft server is running!",
            color=0x2ecc71,
            fields=[
                ("IP", f"`{PLAYIT_ADDRESS}`", False),
                ("Version", "Paper 1.21.1", True),
                ("Uptime", uptime_str, True),
                ("Max Runtime", "5.5 hours", True),
                ("Auto-Shutdown", "10 min if empty", True),
                ("Actions Run", f"[View Logs]({status.get('url', '#')})", True),
            ]
        )
    else:
        embed = make_embed(
            "🔴 Server is OFFLINE",
            "Use `/start` to boot up the server!\n"
            f"🌐 **IP (when online):** `{PLAYIT_ADDRESS}`",
            color=0xe74c3c
        )

    await interaction.followup.send(embed=embed)


@bot.tree.command(name="ip", description="🌐 Get the server IP address")
async def server_ip(interaction: discord.Interaction):
    embed = make_embed(
        "🌐 Server Address",
        f"```\n{PLAYIT_ADDRESS}\n```\n"
        "Add this in Minecraft → Multiplayer → Add Server\n\n"
        "**Note:** The server must be running (`/start`) to connect.",
        color=0x3498db
    )
    await interaction.response.send_message(embed=embed)


@bot.tree.command(name="help", description="❓ Show all commands")
async def help_cmd(interaction: discord.Interaction):
    embed = make_embed(
        "⛏️ Minecraft Server Bot",
        "Control the Paper 1.21.1 server from Discord!",
        color=0x9b59b6,
        fields=[
            ("/start", "🟢 Start the server (~2 min boot)", False),
            ("/stop", "🔴 Stop the server (saves world)", False),
            ("/status", "📊 Check if server is online", False),
            ("/ip", "🌐 Get the server IP address", False),
            ("/help", "❓ Show this help message", False),
        ]
    )
    embed.add_field(
        name="ℹ️ Auto-Shutdown",
        value="Server shuts down after **10 minutes** with no players.\n"
              "Max runtime per session: **5.5 hours**.",
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
