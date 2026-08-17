#!/usr/bin/env bash
set -euo pipefail
PROJECT="${PROJECT_DIRECTORY:-/root/sakana}"
HOST_ROOT="${OUTPUT_DIRECTORY:-/var/www/agnes-videos}"
PUBLIC_BASE="${VIDEO_HOST_URL:-http://127.0.0.1:6464/videos}"

echo "=== Python syntax ==="
PYTHONPYCACHEPREFIX=/tmp/mia-pycache "$PROJECT/venv/bin/python" -m py_compile \
  "$PROJECT"/generator/*.py "$PROJECT"/bot/*.py "$PROJECT"/web/*.py
echo "OK"

echo "=== FFmpeg ==="
ffmpeg -version | head -1
ffmpeg -hide_banner -filters 2>/dev/null | grep -E ' ass | xfade | tpad ' || true

echo "=== Nginx ==="
nginx -t
systemctl is-active nginx
ss -tlnp | grep ':6464'
curl -fsSI http://127.0.0.1:6464/ | head -5

echo "=== Bot service ==="
systemctl is-active agnes-pipeline
systemctl status agnes-pipeline --no-pager | head -15

echo "=== Directories ==="
namei -l "$HOST_ROOT"
ls -ld "$PROJECT/characters/mia" "$HOST_ROOT"

echo "=== Environment names only ==="
for name in DISCORD_BOT_TOKEN AGNES_API_KEY OUTPUT_DIRECTORY VIDEO_HOST_URL PUBLIC_HOSTNAME KOKORO_MODEL_PATH KOKORO_VOICES_PATH KOKORO_VOICE; do
  if grep -q "^${name}=" "$PROJECT/config/.env" 2>/dev/null; then echo "SET $name"; else echo "MISSING $name"; fi
done

echo "Verification completed. Run /mia in Discord for the paid end-to-end generation test."
