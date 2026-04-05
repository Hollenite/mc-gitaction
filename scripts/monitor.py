#!/usr/bin/env python3
"""
MC Server Monitor - RCON player tracking, Discord command execution,
chat/event forwarding, auto-shutdown.
"""

import os
import sys
import time
import json
import re
import struct
import socket
import subprocess
import traceback
from datetime import datetime, timezone
from urllib.request import Request, urlopen
from urllib.parse import quote as urlquote
from urllib.error import URLError, HTTPError

# ─── Config ────────────────────────────────────────────────
RCON_HOST = "localhost"
RCON_PORT = 25575
RCON_PASSWORD = "eae4ed6e919c326b79705204"
LOG_FILE = "server-run/logs/latest.log"
DISCORD_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
DISCORD_CHANNEL = os.environ.get("DISCORD_CHANNEL_ID", "")
EMPTY_TIMEOUT = 600
WARN_TIMEOUT  = 300
MAX_RUNTIME   = 19800
SAVE_INTERVAL = 1800
CHECK_INTERVAL = 10
CMD_PREFIX = "RCON::"


# ─── RCON Client ───────────────────────────────────────────

class RCON:
    def __init__(self, host, port, password):
        self.host = host
        self.port = port
        self.password = password
        self.sock = None
        self.req_id = 0

    def connect(self):
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(5)
            self.sock.connect((self.host, self.port))
        except Exception as e:
            print(f"[RCON] Connection failed: {e}")
            self.sock = None
            return False
        resp = self._send(3, self.password)
        if resp is None:
            print("[RCON] Authentication failed!")
            self.sock = None
            return False
        print("[RCON] ✅ Connected and authenticated!")
        return True

    def command(self, cmd):
        if not self.sock:
            if not self.connect():
                return None
        try:
            return self._send(2, cmd)
        except Exception as e:
            print(f"[RCON] Command error ({cmd}): {e}")
            self.sock = None
            return None

    def _send(self, ptype, payload):
        self.req_id += 1
        body = struct.pack("<ii", self.req_id, ptype) + payload.encode("utf-8") + b"\x00\x00"
        packet = struct.pack("<i", len(body)) + body
        self.sock.sendall(packet)
        return self._recv()

    def _recv(self):
        raw = self._recv_bytes(4)
        if not raw:
            return None
        length = struct.unpack("<i", raw)[0]
        data = self._recv_bytes(length)
        if not data or len(data) < 10:
            return None
        return data[8:-2].decode("utf-8", errors="replace")

    def _recv_bytes(self, n):
        buf = b""
        while len(buf) < n:
            try:
                chunk = self.sock.recv(n - len(buf))
            except socket.timeout:
                return None
            if not chunk:
                return None
            buf += chunk
        return buf

    def close(self):
        if self.sock:
            try:
                self.sock.close()
            except:
                pass
            self.sock = None


# ─── Discord API ───────────────────────────────────────────

def discord_request(method, endpoint, body=None):
    """Make a Discord API request."""
    url = f"https://discord.com/api/v10{endpoint}"
    headers = {"Authorization": f"Bot {DISCORD_TOKEN}"}

    data = None
    if body is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(body).encode("utf-8")

    req = Request(url, data=data, headers=headers, method=method)
    try:
        with urlopen(req) as resp:
            body_bytes = resp.read()
            if body_bytes:
                return json.loads(body_bytes)
            return True
    except HTTPError as e:
        err_body = e.read().decode() if e.fp else ""
        print(f"[DISCORD] HTTP {e.code} on {method} {endpoint}: {err_body[:200]}")
        return None
    except Exception as e:
        print(f"[DISCORD] Error on {method} {endpoint}: {e}")
        return None


def send_message(content):
    return discord_request("POST", f"/channels/{DISCORD_CHANNEL}/messages", {"content": content})


def send_embed(title, desc, color=3447003, fields=None):
    embed = {
        "title": title,
        "description": desc,
        "color": color,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if fields:
        embed["fields"] = [{"name": n, "value": v, "inline": il} for n, v, il in fields]
    return discord_request("POST", f"/channels/{DISCORD_CHANNEL}/messages", {"embeds": [embed]})


def get_recent_messages(limit=15):
    result = discord_request("GET", f"/channels/{DISCORD_CHANNEL}/messages?limit={limit}")
    return result if isinstance(result, list) else []


def add_reaction(message_id, emoji):
    encoded = urlquote(emoji, safe="")
    discord_request("PUT", f"/channels/{DISCORD_CHANNEL}/messages/{message_id}/reactions/{encoded}/@me")


def reply_to(message_id, content):
    discord_request("POST", f"/channels/{DISCORD_CHANNEL}/messages", {
        "content": content,
        "message_reference": {"message_id": str(message_id)}
    })


# ─── Log Watcher ──────────────────────────────────────────

class LogWatcher:
    CHAT_RE  = re.compile(r"\[.*INFO\].*: <(\w+)> (.+)")
    JOIN_RE  = re.compile(r"\[.*INFO\].*: (\w+) joined the game")
    LEAVE_RE = re.compile(r"\[.*INFO\].*: (\w+) left the game")
    DEATH_RE = re.compile(r"\[.*INFO\].*: (\w+ (?:was slain|was shot|drowned|blew up|was killed|fell|burned|hit the ground|went up in flames|was frozen|was pricked|tried to swim|starved|suffocated|was impaled|was squashed|was pummeled|walked into|was fireballed|was stung|was squished|withered away|experienced kinetic|didn't want|was obliterated|was blown up|died).*)")
    ADV_RE   = re.compile(r"\[.*INFO\].*: (\w+ has (?:made the advancement|completed the challenge|reached the goal) \[.+\])")
    DONE_RE  = re.compile(r"Done \(")

    def __init__(self, path):
        self.path = path
        self.position = 0
        self.server_ready = False

    def read_new(self):
        if not os.path.exists(self.path):
            return []
        try:
            with open(self.path, "r", errors="replace") as f:
                f.seek(self.position)
                lines = f.readlines()
                self.position = f.tell()
            return [l.strip() for l in lines if l.strip()]
        except:
            return []

    def parse(self, lines):
        events = []
        for line in lines:
            if not self.server_ready:
                if self.DONE_RE.search(line):
                    self.server_ready = True
                    events.append(("ready", None, None))
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
                events.append(("adv", m.group(1), None))
                continue
        return events


# ─── Monitor ──────────────────────────────────────────────

class Monitor:
    def __init__(self):
        self.rcon = RCON(RCON_HOST, RCON_PORT, RCON_PASSWORD)
        self.log = LogWatcher(LOG_FILE)
        self.players = set()
        self.start_time = time.time()
        self.last_save = time.time()
        self.empty_since = None
        self.warned = False
        self.processed = set()
        self.rcon_ok = False
        self.server_ready = False

    def try_rcon(self):
        if self.rcon_ok:
            return True
        print("[MONITOR] Trying RCON connection...")
        if self.rcon.connect():
            self.rcon_ok = True
            resp = self.rcon.command("op Hollenite")
            print(f"[MONITOR] op Hollenite: {resp}")
            return True
        return False

    def rcon_player_count(self):
        """Get reliable player count via RCON."""
        if not self.rcon_ok:
            return len(self.players), 10
        resp = self.rcon.command("list")
        if resp:
            m = re.search(r"There are (\d+) of a max of (\d+)", resp)
            if m:
                count = int(m.group(1))
                maxp = int(m.group(2))
                if ":" in resp:
                    names = resp.split(":", 1)[1].strip()
                    if names:
                        self.players = {n.strip() for n in names.split(",") if n.strip()}
                    else:
                        self.players = set()
                return count, maxp
        return len(self.players), 10

    def get_tps(self):
        if not self.rcon_ok:
            return None
        resp = self.rcon.command("tps")
        if resp:
            clean = re.sub(r"§.", "", resp)
            nums = re.findall(r"[\d.*]+", clean)
            # Filter to actual TPS values (should be around 0-20)
            tps = []
            for n in nums:
                if '*' in n:
                    tps.append(n)
                else:
                    try:
                        v = float(n)
                        if 0 <= v <= 20.5:
                            tps.append(f"{v:.1f}")
                    except:
                        pass
            return tps[:3] if len(tps) >= 3 else None
        return None

    def get_memory(self):
        try:
            with open("/proc/meminfo") as f:
                info = {}
                for line in f:
                    parts = line.split()
                    info[parts[0].rstrip(":")] = int(parts[1])
            total = info.get("MemTotal", 0) // 1024
            avail = info.get("MemAvailable", 0) // 1024
            return total - avail, total
        except:
            return None, None

    def uptime_str(self):
        s = int(time.time() - self.start_time)
        h, r = divmod(s, 3600)
        m, s = divmod(r, 60)
        return f"{h}h {m}m {s}s"

    def process_events(self):
        lines = self.log.read_new()
        events = self.log.parse(lines)

        for etype, d1, d2 in events:
            if etype == "ready":
                self.server_ready = True
                print("[MONITOR] Server ready! Connecting RCON...")
                # Give RCON a moment
                time.sleep(3)
                self.try_rcon()

                count, maxp = self.rcon_player_count()
                tps = self.get_tps()
                mem_used, mem_total = self.get_memory()

                fields = [
                    ("🌐 IP", "`wiring-funding.gl.joinmc.link`", False),
                    ("👥 Players", f"{count}/{maxp}", True),
                    ("⛏️ Version", "Paper 1.21.1", True),
                    ("🎮 Gamemode", "Survival", True),
                ]
                if tps:
                    fields.append(("📊 TPS", ", ".join(tps), True))
                if mem_used and mem_total:
                    fields.append(("💾 RAM", f"{mem_used}/{mem_total} MB", True))
                fields.append(("⏱️ Max Runtime", "5.5 hours", True))
                fields.append(("🔌 Auto-Shutdown", "10 min if empty", True))

                send_embed(
                    "✅ Server is ONLINE!",
                    "Server loaded! Connect now!",
                    color=0x2ecc71,
                    fields=fields,
                )

            elif etype == "chat":
                send_message(f"💬 **{d1}**: {d2}")

            elif etype == "join":
                self.players.add(d1)
                c = len(self.players)
                plist = ", ".join(sorted(self.players)) or "None"
                send_embed(
                    f"👋 {d1} joined the game",
                    f"**Players online:** {c}/10\n**Online:** {plist}",
                    color=0x2ecc71,
                )
                self.empty_since = None
                self.warned = False

            elif etype == "leave":
                self.players.discard(d1)
                c = len(self.players)
                plist = ", ".join(sorted(self.players)) or "None"
                send_embed(
                    f"🚪 {d1} left the game",
                    f"**Players online:** {c}/10\n**Online:** {plist}",
                    color=0xf39c12,
                )

            elif etype == "death":
                send_message(f"💀 {d1}")

            elif etype == "adv":
                send_message(f"🏆 {d1}")

    def check_commands(self):
        """Poll Discord channel for RCON:: commands and execute them."""
        if not self.rcon_ok:
            return

        try:
            messages = get_recent_messages(10)
        except Exception as e:
            print(f"[CMD] Failed to fetch messages: {e}")
            return

        if not messages:
            return

        for msg in messages:
            msg_id = msg.get("id", "")
            content = msg.get("content", "")

            if not content.startswith(CMD_PREFIX):
                continue
            if msg_id in self.processed:
                continue

            cmd = content[len(CMD_PREFIX):].strip()
            if not cmd:
                continue

            self.processed.add(msg_id)
            print(f"[CMD] Found command: '{cmd}' (msg {msg_id})")

            # Execute via RCON
            try:
                result = self.rcon.command(cmd)
                if result is not None:
                    result = re.sub(r"§.", "", result)  # strip color codes
                else:
                    result = "(no response)"
            except Exception as e:
                result = f"Error: {e}"

            print(f"[CMD] Result: {result}")

            # Reply in Discord
            try:
                reply_to(msg_id, f"```\n> {cmd}\n{result}\n```")
            except Exception as e:
                print(f"[CMD] Failed to reply: {e}")

            # Add ✅ reaction
            try:
                add_reaction(msg_id, "✅")
            except Exception as e:
                print(f"[CMD] Failed to react: {e}")

    def shutdown_check(self):
        """Check auto-shutdown conditions."""
        now = time.time()

        # Use RCON for accurate count
        count, _ = self.rcon_player_count()

        if count == 0:
            if self.empty_since is None:
                self.empty_since = now
                print("[MONITOR] Server empty. Timer started.")

            dur = int(now - self.empty_since)

            if dur >= WARN_TIMEOUT and not self.warned:
                self.warned = True
                left = (EMPTY_TIMEOUT - dur) // 60
                send_embed(
                    "⚠️ Server Empty",
                    f"No players for {WARN_TIMEOUT // 60} min.\n"
                    f"Shutting down in **{left} minutes**...\n"
                    "Join to cancel!",
                    color=0xf1c40f,
                )

            if dur >= EMPTY_TIMEOUT:
                send_embed("⏹️ Auto-Shutdown",
                    "Empty for 10 min. Saving world...", color=0xe67e22)
                return True
        else:
            if self.empty_since:
                print(f"[MONITOR] {count} player(s) online. Timer cancelled.")
                if self.warned:
                    send_message("✅ Shutdown cancelled — player(s) online!")
                self.empty_since = None
                self.warned = False

        return False

    def runtime_check(self):
        if time.time() - self.start_time >= MAX_RUNTIME:
            send_embed("⏰ Runtime Limit",
                f"Ran for {self.uptime_str()}. Saving & stopping.\nUse **/start** to restart.",
                color=0xf1c40f)
            return True
        return False

    def save_check(self):
        now = time.time()
        if now - self.last_save >= SAVE_INTERVAL:
            print("[MONITOR] Auto-saving...")
            if self.rcon_ok:
                self.rcon.command("save-all")
                time.sleep(5)
            subprocess.run(["bash", "scripts/world-save.sh"], timeout=600)
            self.last_save = now
            send_message("💾 World auto-saved to Google Drive.")

    def mc_alive(self):
        pid_file = "/tmp/mc.pid"
        if not os.path.exists(pid_file):
            return True
        try:
            pid = int(open(pid_file).read().strip())
            os.kill(pid, 0)
            return True
        except (ProcessLookupError, ValueError):
            return False

    def run(self):
        print("=" * 50)
        print("[MONITOR] Starting MC Server Monitor")
        print(f"[MONITOR] RCON: {RCON_HOST}:{RCON_PORT}")
        print(f"[MONITOR] Log:  {LOG_FILE}")
        print(f"[MONITOR] Auto-shutdown: {EMPTY_TIMEOUT}s empty")
        print(f"[MONITOR] Max runtime: {MAX_RUNTIME}s")
        print("=" * 50)

        # Wait for server to start
        print("[MONITOR] Waiting for server to start...")
        while True:
            self.process_events()
            if self.server_ready:
                break
            if not self.mc_alive():
                print("[MONITOR] Server process died during startup!")
                send_embed("💥 Server Failed to Start",
                    "Process died during startup.", color=0xe74c3c)
                return
            time.sleep(2)

        print("[MONITOR] Server is ready! Starting main loop.")

        # Main loop
        while True:
            try:
                self.process_events()
                self.check_commands()

                if self.shutdown_check():
                    break
                if self.runtime_check():
                    break

                self.save_check()

                if not self.mc_alive():
                    send_embed("💥 Server Crashed",
                        "Server process died unexpectedly.", color=0xe74c3c)
                    break

            except Exception as e:
                print(f"[MONITOR] Loop error: {e}")
                traceback.print_exc()

            time.sleep(CHECK_INTERVAL)

        print("[MONITOR] Monitor exiting.")
        self.rcon.close()


if __name__ == "__main__":
    Monitor().run()
