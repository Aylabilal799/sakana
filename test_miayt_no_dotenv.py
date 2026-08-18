#!/usr/bin/env python3
"""
Test script for /miayt command functionality.
Run this on your VPS to verify date parsing and YouTube auth before using Discord.
"""
import os
import sys
from pathlib import Path
from datetime import datetime, timezone

print("=" * 60)
print("Mia /miayt Test Script")
print("=" * 60)

# ── Test 1: Date/Time Parsing ──────────────────────────────
print("\n[1] Testing date/time parsing...")

def parse_scheduled_time(date_str: str, time_str: str):
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
    for fmt in ("%H:%M", "%I:%M %p", "%I:%M%p", "%I:%M %P", "%I:%M%P"):
        try:
            time_parsed = datetime.strptime(time_str.upper().replace(".", ""), fmt)
            break
        except ValueError:
            continue
    if time_parsed is None:
        return None
    scheduled = datetime(
        dt.year, dt.month, dt.day,
        time_parsed.hour, time_parsed.minute,
        tzinfo=timezone.utc,
    )
    return scheduled

test_cases = [
    ("2026-08-20", "14:30"),
    ("08-20-2026", "2:30 PM"),
    ("2026/08/20", "02:30"),
    ("20-08-2026", "9:00 AM"),
]

for date_str, time_str in test_cases:
    result = parse_scheduled_time(date_str, time_str)
    status = "OK" if result else "FAIL"
    print(f"  {status} | Date: '{date_str}' + Time: '{time_str}' => {result}")

# ── Test 2: Check ENV ───────────────────────────────────────
print("\n[2] Checking environment variables...")
secrets = os.getenv("YOUTUBE_CLIENT_SECRETS_FILE", "NOT SET")
token = os.getenv("YOUTUBE_TOKEN_FILE", "NOT SET")
auto_post = os.getenv("YOUTUBE_AUTO_POST", "NOT SET")

print(f"  YOUTUBE_CLIENT_SECRETS_FILE: {secrets}")
print(f"  YOUTUBE_TOKEN_FILE: {token}")
print(f"  YOUTUBE_AUTO_POST: {auto_post}")

secrets_exists = Path(secrets).exists() if secrets != "NOT SET" else False
token_exists = Path(token).exists() if token != "NOT SET" else False

print(f"  Secrets file exists: {secrets_exists}")
print(f"  Token file exists: {token_exists}")

# ── Test 3: YouTube Auth ───────────────────────────────────
print("\n[3] Testing YouTube authentication...")
if secrets_exists:
    try:
        sys.path.insert(0, "/root/sakana")
        from generator.youtube_uploader import YouTubeUploader
        uploader = YouTubeUploader()
        ok = uploader.test_auth()
        if ok:
            print("  OK | YouTube auth working!")
        else:
            print("  FAIL | YouTube auth returned False")
    except Exception as e:
        print(f"  FAIL | {e}")
else:
    print("  SKIP | Secrets file not found, cannot test auth")

# ── Test 4: Future time validation ──────────────────────────
print("\n[4] Testing future time validation...")
now = datetime.now(timezone.utc)
test_dt = parse_scheduled_time("2026-12-25", "10:00")
if test_dt:
    if test_dt > now:
        print(f"  OK | {test_dt} is in the future")
    else:
        print(f"  WARN | {test_dt} is in the past (expected for old dates)")
else:
    print("  FAIL | Could not parse")

print("\n" + "=" * 60)
print("Test complete. If all checks pass, /miayt should work!")
print("=" * 60)
