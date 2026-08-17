# Mia YouTube Autopilot — Deployment Guide

## What This Adds

On top of your existing V4 + caption-fix pipeline, this adds:

1. **Auto-script generation** — No `/mia` prompt needed. System picks a unique theme and generates a fresh script automatically.
2. **SQLite deduplication**  Tracks every generated script by hash. Never repeats a story.
3. **3× daily scheduled runs** (PKT):
   - 9:00 PM PKT
   - 2:00 AM PKT
   - 5:00 AM PKT
4. **YouTube auto-upload** — Videos upload as **private** with scheduled publish time.
5. **Discord notifications** — You get notified with hosted video link + YouTube link.
6. **API rest period** — Minimum 45-minute gap between runs to avoid rate limits.

## New Files

```
generator/story_generator.py      # Auto-generates unique scripts with dedup
generator/youtube_uploader.py       # YouTube Data API v3 OAuth upload
generator/autopilot_scheduler.py  # Background scheduler (3× daily)
bot/commands.py                    # /mia + /autopilot commands
bot/main.py                        # Bot entrypoint with autopilot init
config/ENV_REQUIRED.txt            # New env vars
```

## Prerequisites

### 1. YouTube OAuth Credentials

You need a **YouTube Data API v3** project in Google Cloud Console:

1. Go to https://console.cloud.google.com/
2. Create a project → Enable **YouTube Data API v3**
3. Go to **Credentials** → **Create OAuth 2.0 Client ID** (Desktop app)
4. Download the JSON → save as:
   ```
   /root/deepseekyt/youtube_client_secret.json
   ```
   (Or copy to `/root/sakana/config/youtube_client_secret.json`)

### 2. First-Time Auth

On first run, the bot will print an OAuth URL. You must:
1. Open the URL in your browser
2. Log in with your YouTube channel Google account
3. Grant permission
4. The token will be saved to `/root/deepseekyt/youtube_token.json`

## Deployment

### Step 1: Backup your working V4 + caption fix

```bash
cd /root/sakana
cp -a bot bot.pre-autopilot
cp -a generator generator.pre-autopilot
```

### Step 2: Add new files

```bash
cd /root/sakana

# Extract the autopilot files
tar -xzf /path/to/mia_autopilot.tar.gz

# Verify new files exist
ls generator/story_generator.py
ls generator/youtube_uploader.py
ls generator/autopilot_scheduler.py
ls bot/commands.py
ls bot/main.py
```

### Step 3: Install dependencies

```bash
/root/sakana/venv/bin/pip install \
    google-api-python-client google-auth-httplib2 google-auth-oauthlib
```

### Step 4: Add environment variables

Edit your `.env` or systemd service file and add:

```bash
# YouTube Autopilot
YOUTUBE_AUTO_POST=false                    # set to true to enable
YOUTUBE_CLIENT_SECRETS_FILE=/root/deepseekyt/youtube_client_secret.json
YOUTUBE_TOKEN_FILE=/root/deepseekyt/youtube_token.json
YOUTUBE_DEFAULT_PRIVACY=private
YOUTUBE_CATEGORY_ID=22
YOUTUBE_MAX_UPLOAD_ATTEMPTS=5
YOUTUBE_OAUTH_PORT=9219
AUTOPILOT_NOTIFICATION_CHANNEL_ID=your_discord_channel_id
```

### Step 5: Test /mia still works

```bash
sudo systemctl restart agnes-pipeline
# In Discord:
/mia Mia discovers a hidden room inside her new apartment containing photographs of herself
```

Verify: progress bar, captions (no commas), video, hosting all work.

### Step 6: Test autopilot manually

```bash
# In Discord (owner only):
/autopilot status
/autopilot test
```

This forces one autopilot run immediately. Check:
- Script is auto-generated and unique
- Video generates successfully
- YouTube upload succeeds
- Discord notification arrives with both links

### Step 7: Enable autopilot

```bash
# Edit your .env:
YOUTUBE_AUTO_POST=true

# Restart:
sudo systemctl restart agnes-pipeline
```

Or use the Discord command:
```
/autopilot start
```

## Discord Commands

| Command | Description |
|---------|-------------|
| `/mia generate <prompt>` | Generate a video (existing, unchanged) |
| `/mia status <job_id>` | Check job status (existing, unchanged) |
| `/autopilot status` | Show next run time, stats, schedule |
| `/autopilot start` | Start the scheduler |
| `/autopilot stop` | Stop the scheduler |
| `/autopilot test` | Force one run now (owner only) |

## How Deduplication Works

Every generated script is hashed (SHA-256) and stored in SQLite:
- `autopilot.db` → `generated_stories` table
- If a hash collision occurs, the system auto-regenerates with a different theme
- Theme usage is also tracked so least-used themes are prioritized

## Schedule

PKT (UTC+5) | UTC
---|---
9:00 PM | 4:00 PM
2:00 AM | 9:00 PM
5:00 AM | 12:00 AM

The scheduler waits at least 45 minutes between runs. If a run is missed (e.g., bot was down), it picks the next available slot.

## Troubleshooting

### "YouTube auth failed"
- Check `YOUTUBE_CLIENT_SECRETS_FILE` path exists
- Run `/autopilot test` and watch logs for OAuth URL
- Complete OAuth in browser

### "Duplicate script detected"
- This is normal — the system auto-regenerates
- Check `autopilot.db` with sqlite3 to see generated stories

### "Autopilot not running"
- Check `YOUTUBE_AUTO_POST=true` in env
- Check logs: `tail -f /root/sakana/logs/bot.log | grep -i autopilot`

## Safety Features

1. **YOUTUBE_AUTO_POST=false by default** — Must explicitly enable
2. **Private uploads** — Videos upload as private; you manually publish
3. **45-min gap** — Prevents API rate limit issues
4. **Owner-only commands** — `/autopilot start/stop/test` restricted to bot owner
5. **No regression** — `/mia` works exactly as before
