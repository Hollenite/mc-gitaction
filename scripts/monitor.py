#!/usr/bin/env python3
"""
MC Server Monitor - Reports events to Discord, handles RCON commands,
tracks players, auto-shutdown on empty.
"""

import os
import sys
import time
import json
import re
import struct
import socket
import subprocess
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.error import URLError, HTTPError

# ─── Config ────────────────────────────────────────────────
RCON_HOST = "localhost"
RCON_PORT = 25575
RCON_PASSWORD = "eae4ed6e919c326b79705204"
LOG_FILE = "server-run/logs/latest.log"
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL_ID", "")
EMPTY_TIMEOUT = 600       # 10 minutes
WARN_TIMEOUT  = 300       # 5 minutes
MAX_RUNTIME   = 19800     # 5.5 hours
SAVE_INTERVAL = 1800      # 30 min auto-save
CHECK_INTERVAL = 10       # seconds between checks
CMD_PREFIX = "RCON::"     # prefix for commands in Discord


# ─── RCON Client ───────────────────────────────────────────

class RCON:
    """Minimal Minecraft RCON client."""

    def __init__(self, host, port, password):
        self.host = host
        self.port = port
        self.password = password
        self.sock = None
        self.req_id = 0

    def connect(self):
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.settimeout(5)
        try:
            self.sock.connect((self.host, self.port))
        except Exception as e:
            print(f"[RCON] Connection failed: {e}")
            self.sock = None
            return False
        # Authenticate
        resp = self._send(3, self.password)
        if resp is None:
            print("[RCON] Auth failed")
            self.sock = None
            return False
        print("[RCON] Connected and authenticated")
        return True

    def command(self, cmd):
        """Send a command, return the response string."""
        if not self.sock:
            if not self.connect():
                return None
        try:
            return self._send(2, cmd)
        except Exception as e:
            print(f"[RCON] Command error: {e}")
            self.sock = None
            return None

    def _send(self, ptype, payload):
        self.req_id += 1
        data = struct.pack("<ii", self.req_id, ptype) + payload.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<i", len(data)) + data
        self.sock.sendall(packet)
        return self._recv()

    def _recv(self):
        raw = b""
        while len(raw) < 4:
            chunk = self.sock.recv(4 - len(raw))
            if not chunk:
                return None
            raw += chunk
        length = struct.unpack("<i", raw)[0]
        data = b""
        while len(data) < length:
            chunk = self.sock.recv(length - len(data))
            if not chunk:
                break
            data += chunk
        if len(data) < 10:
            return None
        response = data[8:-2].decode("utf-8", errors="replace")
        return response

    def close(self):
        if self.sock:
            self.sock.close()
            self.sock = None


# ─── Discord API ───────────────────────────────────────────

def discord_api(method, endpoint, body=None):
    """Call the Discord REST API."""
    url = f"https://discord.com/api/v10{endpoint}"
    headers = {
        "Authorization": f"Bot {DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }
    data = json.dumps(body).encode("utf-8") if body else None
    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            if resp.status in (200, 201):
                return json.loads(resp.read())
            return None
    except (URLError, HTTPError) as e:
        return None


def send_message(content):
    """Send a plain text message."""
    discord_api("POST", f"/channels/{DISCORD_CHANNEL}/messages", {"content": content})


def send_embed(title, desc, color=3447003, fields=None):
    """Send an embed message."""
    embed = {
        "title": title,
        "description": desc,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = [{"name": n, "value": v, "inline": il} for n, v, il in fields]
    discord_api("POST", f"/channels/{DISCORD_CHANNEL}/messages", {"embeds": [embed]})


def get_recent_messages(limit=15):
    """Get recent messages from the Discord channel."""
    return discord_api("GET", f"/channels/{DISCORD_CHANNEL}/messages?limit={limit}") or []


def add_reaction(message_id, emoji):
    """Add a reaction to a message."""
    discord_api("PUT", f"/channels/{DISCORD_CHANNEL}/messages/{message_id}/reactions/{emoji}/@me")


def reply_to(message_id, content):
    """Reply to a specific message."""
    discord_api("POST", f"/channels/{DISCORD_CHANNEL}/messages", {
        "content": content,
        "message_reference": {"message_id": message_id}
    })


# ─── Log Watcher ──────────────────────────────────────────

class LogWatcher:
    """Watch MC server log file for events."""

    # Patterns to detect
    CHAT_RE     = re.compile(r"\[.*INFO\].*: <(\w+)> (.+)")
    JOIN_RE     = re.compile(r"\[.*INFO\].*: (\w+) joined the game")
    LEAVE_RE    = re.compile(r"\[.*INFO\].*: (\w+) left the game")
    DEATH_RE    = re.compile(r"\[.*INFO\].*: (\w+ (?:was slain|was shot|drowned|blew up|was killed|fell|burned|hit the ground|went up in flames|was frozen|was pricked|tried to swim|starved|suffocated|was impaled|was squashed|was pummeled|walked into|was fireballed|was stung|was squished|withered away|experienced kinetic|didn't want to live|was obliterated|was blown up|died).*)")
    ADV_RE      = re.compile(r"\[.*INFO\].*: (\w+ has (?:made the advancement|completed the challenge|reached the goal) \[.+\])")
    DONE_RE     = re.compile(r"\[.*INFO\].*: Done \(")

    def __init__(self, path):
        self.path = path
        self.position = 0
        self.seen_done = False

    def get_new_lines(self):
        """Read new lines from log file."""
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", errors="replace") as f:
                f.seek(self.position)
                lines = f.readlines()
                self.position = f.tell()
            return lines
        except Exception:
            return []

    def parse_events(self, lines):
        """Parse log lines into events."""
        events = []
        for line in lines:
            line = line.strip()
            if not line:
                continue

            m = self.CHAT_RE.search(line)
            if m:
                events.append(("chat", m.group(1), m.group(2)))
                continue

            m = self.JOIN_RE.search(line)
            if m:
                events.append(("join", m.group(1), None))
                continue

            m = self.LEAVE_RE.search(line)
            if m:
                events.append(("leave", m.group(1), None))
                continue

            m = self.DEATH_RE.search(line)
            if m:
                events.append(("death", m.group(1), None))
                continue

            m = self.ADV_RE.search(line)
            if m:
                events.append(("advancement", m.group(1), None))
                continue

            if self.DONE_RE.search(line) and not self.seen_done:
                self.seen_done = True
                events.append(("server_ready", None, None))

        return events


# ─── Monitor ──────────────────────────────────────────────

class Monitor:
    def __init__(self):
        self.rcon = RCON(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        self.log = LogWatcher(LOG_FILE)
        self.online_players = set()
        self.start_time = time.time()
        self.last_save = time.time()
        self.empty_since = None
        self.warned = False
        self.processed_cmds = set()
        self.rcon_connected = False

    def connect_rcon(self):
        """Try to connect to RCON."""
        if self.rcon_connected:
            return True
        if self.rcon.connect():
            self.rcon_connected = True
            # Op the server owner
            self.rcon.command("op Hollenite")
            print("[MONITOR] RCON connected, opped Hollenite")
            return True
        return False

    def get_player_count_rcon(self):
        """Get player list via RCON 'list' command."""
        if not self.rcon_connected:
            self.connect_rcon()
        resp = self.rcon.command("list")
        if resp:
            # Response: "There are X of a max of Y players online: player1, player2"
            m = re.search(r"There are (\d+) of a max of (\d+)", resp)
            if m:
                count = int(m.group(1))
                max_p = int(m.group(2))
                # Extract player names
                if ":" in resp:
                    names_str = resp.split(":", 1)[1].strip()
                    if names_str:
                        names = [n.strip() for n in names_str.split(",") if n.strip()]
                        self.online_players = set(names)
                    else:
                        self.online_players = set()
                return count, max_p
        return len(self.online_players), 10

    def get_tps(self):
        """Get server TPS via RCON."""
        resp = self.rcon.command("tps") if self.rcon_connected else None
        if resp:
            # Paper TPS format: "§6TPS from last 1m, 5m, 15m: §a20.0, §a20.0, §a20.0"
            # Strip color codes
            clean = re.sub(r"§.", "", resp)
            numbers = re.findall(r"[\d.]+", clean)
            if len(numbers) >= 3:
                return numbers[:3]
        return None

    def get_memory(self):
        """Get rough memory usage from /proc."""
        try:
            with open("/proc/meminfo") as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                parts = line.split()
                info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 0) // 1024
            free = (info.get("MemAvailable", 0)) // 1024
            used = total - free
            return used, total
        except Exception:
            return None, None

    def format_uptime(self):
        elapsed = int(time.time() - self.start_time)
        h, r = divmod(elapsed, 3600)
        m, s = divmod(r, 60)
        return f"{h}h {m}m {s}s"

    def process_log_events(self):
        """Read log, parse events, forward to Discord."""
        lines = self.log.get_new_lines()
        events = self.log.parse_events(lines)

        for etype, data, extra in events:
            if etype == "chat":
                send_message(f"💬 **{data}**: {extra}")

            elif etype == "join":
                self.online_players.add(data)
                count = len(self.online_players)
                send_embed(
                    f"👋 {data} joined",
                    f"Players online: **{count}**/10\n"
                    f"Online: {', '.join(sorted(self.online_players)) or 'None'}",
                    color=0x2ecc71,
                )
                self.empty_since = None
                self.warned = False

            elif etype == "leave":
                self.online_players.discard(data)
                count = len(self.online_players)
                send_embed(
                    f"🚪 {data} left",
                    f"Players online: **{count}**/10\n"
                    f"Online: {', '.join(sorted(self.online_players)) or 'None'}",
                    color=0xf39c12,
                )

            elif etype == "death":
                send_message(f"💀 {data}")

            elif etype == "advancement":
                send_message(f"🏆 {data}")

            elif etype == "server_ready":
                count, max_p = self.get_player_count_rcon()
                tps = self.get_tps()
                mem_used, mem_total = self.get_memory()

                fields = [
                    ("🌐 IP", "`wiring-funding.gl.joinmc.link`", False),
                    ("👥 Players", f"{count}/{max_p}", True),
                    ("⛏️ Version", "Paper 1.21.1", True),
                    ("🎮 Gamemode", "Survival", True),
                ]
                if tps:
                    fields.append(("📊 TPS", f"{tps[0]}, {tps[1]}, {tps[2]}", True))
                if mem_used and mem_total:
                    fields.append(("💾 RAM", f"{mem_used}/{mem_total} MB", True))
                fields.append(("⏱️ Max Runtime", "5.5 hours", True))
                fields.append(("🔌 Auto-Shutdown", "10 min if empty", True))

                send_embed(
                    "✅ Server is ONLINE!",
                    "Server loaded successfully. Connect now!",
                    color=0x2ecc71,
                    fields=fields,
                )

    def check_discord_commands(self):
        """Poll Discord for RCON commands."""
        if not self.rcon_connected:
            return

        messages = get_recent_messages(10)
        if not messages:
            return

        for msg in messages:
            msg_id = msg.get("id", "")
            content = msg.get("content", "")

            if not content.startswith(CMD_PREFIX):
                continue
            if msg_id in self.processed_cmds:
                continue

            # Extract command
            cmd = content[len(CMD_PREFIX):].strip()
            if not cmd:
                continue

            self.processed_cmds.add(msg_id)
            print(f"[CMD] Executing: {cmd}")

            # Execute via RCON
            result = self.rcon.command(cmd)

            # Clean color codes
            if result:
                result = re.sub(r"§.", "", result)
            else:
                result = "(no response)"

            # Reply with result
            reply_to(msg_id, f"```\n> {cmd}\n{result}\n```")
            add_reaction(msg_id, "✅")

    def auto_shutdown_check(self):
        """Check if server should auto-shutdown."""
        now = time.time()

        # Get accurate player count via RCON
        count, _ = self.get_player_count_rcon()

        if count == 0:
            if self.empty_since is None:
                self.empty_since = now
                print("[MONITOR] Server is empty. Starting shutdown timer...")

            empty_duration = int(now - self.empty_since)

            if empty_duration >= WARN_TIMEOUT and not self.warned:
                self.warned = True
                remaining = (EMPTY_TIMEOUT - empty_duration) // 60
                send_embed(
                    "⚠️ Server Empty",
                    f"No players for {WARN_TIMEOUT // 60} minutes.\n"
                    f"Shutting down in **{remaining} minutes**...\n"
                    f"Join the server to cancel!",
                    color=0xf1c40f,
                )

            if empty_duration >= EMPTY_TIMEOUT:
                send_embed(
                    "⏹️ Auto-Shutdown",
                    "No players for 10 minutes. Saving world and shutting down...",
                    color=0xe67e22,
                )
                return True
        else:
            if self.empty_since is not None:
                print(f"[MONITOR] Players online ({count}), cancelling shutdown.")
                if self.warned:
                    send_message("✅ Shutdown cancelled — player online!")
                self.empty_since = None
                self.warned = False

        return False

    def max_runtime_check(self):
        """Check if max runtime exceeded."""
        elapsed = time.time() - self.start_time
        if elapsed >= MAX_RUNTIME:
            send_embed(
                "⏰ Runtime Limit",
                f"Server has run for {self.format_uptime()}.\n"
                "Saving world and shutting down.\n"
                "Use **/start** to restart.",
                color=0xf1c40f,
            )
            return True
        return False

    def auto_save_check(self):
        """Periodic world save."""
        now = time.time()
        if now - self.last_save >= SAVE_INTERVAL:
            print("[MONITOR] Auto-saving world...")
            if self.rcon_connected:
                self.rcon.command("save-all")
            subprocess.run(["bash", "scripts/world-save.sh"], timeout=300)
            self.last_save = now
            send_message("💾 World auto-saved to Google Drive.")

    def run(self):
        """Main monitoring loop."""
        print("[MONITOR] Starting monitor...")
        print(f"[MONITOR] Empty timeout: {EMPTY_TIMEOUT}s")
        print(f"[MONITOR] Max runtime: {MAX_RUNTIME}s")

        # Wait for RCON to be available
        for i in range(30):
            if self.connect_rcon():
                break
            time.sleep(2)

        while True:
            try:
                # Process log events (chat, joins, leaves, deaths)
                self.process_log_events()

                # Check for Discord commands
                self.check_discord_commands()

                # Check auto-shutdown
                if self.auto_shutdown_check():
                    break

                # Check max runtime
                if self.max_runtime_check():
                    break

                # Auto-save
                self.auto_save_check()

                # Check server process alive
                mc_pid_file = "/tmp/mc.pid"
                if os.path.exists(mc_pid_file):
                    pid = int(open(mc_pid_file).read().strip())
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        send_embed("💥 Server Crashed", "The server process died unexpectedly.", color=0xe74c3c)
                        break

            except Exception as e:
                print(f"[MONITOR] Error: {e}")

            time.sleep(CHECK_INTERVAL)

        print("[MONITOR] Monitor stopped.")
        self.rcon.close()


if __name__ == "__main__":
    Monitor().run()
