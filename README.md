# Agnes Video Pipeline

Discord-controlled AI video generation using Agnes AI API + Kokoro TTS on a Debian VPS.

## Quick Start

```bash
cd /root/sakana
bash scripts/install.sh
```

Edit `/root/sakana/config/.env` with your credentials, then:

```bash
systemctl start agnes-pipeline
tail -f /root/sakana/logs/bot.log
```

## Discord Commands

- `/generate script:Your story here genre:horror` — Start video generation
- `/status <job_id>` — Check job status
- `/queue` — List pending jobs
- `/voices` — List female TTS voices

## Architecture

- **Video generation**: Agnes AI cloud API (free, no GPU needed)
- **TTS**: Kokoro (local, CPU, ~400MB RAM)
- **Assembly**: FFmpeg (local)
- **Queue**: SQLite (persistent, sequential)
- **Hosting**: Nginx on port 8080

## Requirements

- Debian Trixie+
- 8 GB RAM (CPU only, no GPU needed)
- Agnes AI API key (free)
- Discord bot token
