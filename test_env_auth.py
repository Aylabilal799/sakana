#!/usr/bin/env python3
"""
Mia /miayt Environment & Auth Test Script
Tests: .env loading, YouTube auth, date parsing, DB schema
"""
import os
import sys
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

PROJECT_ROOT = Path("/root/sakana")
DB_PATH = os.getenv("JOB_DATABASE", "/root/sakana/jobs/queue.db")

print("=" * 65)
print("  Mia /miayt — Environment & Auth Test")
print("=" * 65)

# ── Test 1: Load .env manually ─────────────────────────────
print("\n[1] Loading .env file...")
env_file = PROJECT_ROOT / "config" / ".env"
loaded = 0
if env_file.exists():
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, val = line.split("=", 1)
            os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
            loaded += 1
    print(f"  OK | Loaded {loaded} env vars from {env_file}")
else:
    print(f"  FAIL | .env file not found at {env_file}")

# ── Test 2: Check required env vars ────────────────────────
print("\n[2] Checking required environment variables...")
required = {
    "YOUTUBE_CLIENT_SECRETS_FILE": "YouTube OAuth client secrets",
    "YOUTUBE_TOKEN_FILE": "YouTube OAuth token",
    "YOUTUBE_AUTO_POST": "Autopilot toggle",
    "JOB_DATABASE": "SQLite DB path",
    "DISCORD_BOT_TOKEN": "Discord bot token",
    "DISCORD_GUILD_ID": "Discord guild ID",
}
all_ok = True
for key, desc in required.items():
    val = os.getenv(key, "")
    exists = "OK" if val else "MISSING"
    if not val:
        all_ok = False
    print(f"  {exists} | {key} => {desc}")
    if val and "TOKEN" not in key.upper() and "SECRET" not in key.upper():
        print(f"       Value: {val}")

# ── Test 3: Check file existence ─────────────────────────────
print("\n[3] Checking file paths...")
secrets = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "")
token = os.getenv("YOUTUBE_TOKEN_FILE", "")
db = os.getenv("JOB_DATABASE", "")

for label, path in [("Secrets", secrets), ("Token", token), ("DB", db)]:
    exists = Path(path).exists() if path else False
    status = "OK" if exists else "MISSING"
    print(f"  {status} | {label}: {path}")

# ── Test 4: Date/Time Parsing ────────────────────────────────
print("\n[4] Testing date/time parsing...")
def parse_scheduled_time(date_str, time_str):
    date_str = date_str.strip()
    time_str = time_str.strip()
    dt = None
    for fmt in ("%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y", "%Y/%m/%d", "%m/%d/%Y"):
        try:
            dt = datetime.strptime(date_str, fmt)
            break
        except ValueError:
            continue
    if dt is None:
        return None
    time_parsed = None
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p"):
        try:
            time_parsed = datetime.strptime(time_str.upper().replace(".", ""), fmt)
            break
        except ValueError:
            continue
    if time_parsed is None:
        return None
    return datetime(dt.year, dt.month, dt.day, time_parsed.hour, time_parsed.minute, tzinfo=timezone.utc)

tests = [
    ("2026-08-20", "14:30"),
    ("08-20-2026", "2:30 PM"),
    ("2026/08/20", "02:30"),
]
for d, t in tests:
    r = parse_scheduled_time(d, t)
    print(f"  {'OK' if r else 'FAIL'} | '{d}' + '{t}' => {r}")

# ── Test 5: Future time check ───────────────────────────────
print("\n[5] Testing future time validation...")
now = datetime.now(timezone.utc)
test = parse_scheduled_time("2026-12-25", "10:00")
if test and test > now:
    print(f"  OK | {test} is in the future")
else:
    print(f"  FAIL | Time validation failed")

# ── Test 6: DB Schema Check ─────────────────────────────────
print("\n[6] Checking database schema...")
try:
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.execute("PRAGMA table_info(jobs)")
    columns = {row[1] for row in cursor.fetchall()}
    needed = {"youtube_scheduled_time", "youtube_video_id", "youtube_uploaded"}
    missing = needed - columns
    if missing:
        print(f"  WARN | Missing columns: {missing}")
        print(f"       | Run: ALTER TABLE jobs ADD COLUMN ...")
    else:
        print(f"  OK | All YouTube columns present")
    conn.close()
except Exception as e:
    print(f"  FAIL | DB error: {e}")

# ── Test 7: YouTube Auth (only if files exist) ──────────────
print("\n[7] Testing YouTube authentication...")
if Path(secrets).exists():
    try:
        sys.path.insert(0, str(PROJECT_ROOT))
        from generator.youtube_uploader import YouTubeUploader
        uploader = YouTubeUploader()
        ok = uploader.test_auth()
        print(f"  {'OK' if ok else 'FAIL'} | YouTube auth {'working!' if ok else 'failed'}")
    except Exception as e:
        print(f"  FAIL | {e}")
else:
    print("  SKIP | Secrets file not found")

# ── Summary ─────────────────────────────────────────────────
print("\n" + "=" * 65)
if all_ok:
    print("  All env vars loaded. Ready for production test!")
else:
    print("  Some env vars are missing. Check your .env file.")
print("=" * 65)
