import asyncio
import os
import sys
import uuid
import sqlite3
from datetime import datetime
from pathlib import Path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
from dotenv import load_dotenv
env_path = PROJECT_ROOT / "config" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)
DB = os.getenv("JOB_DATABASE", "/root/sakana/jobs/queue.db")
async def submit_autopilot_job(prompt: str, genre: str = "auto",
                                scheduled_time: datetime = None,
                                notification_channel_id: str = None) -> str:
    job_id = uuid.uuid4().hex[:8]
    scheduled_iso = scheduled_time.isoformat() if scheduled_time else None
    channel_id_str = str(notification_channel_id or "")
    with sqlite3.connect(DB, timeout=30) as conn:
        conn.execute("""INSERT INTO jobs
            (job_id, discord_user_id, discord_username, discord_channel_id,
             prompt, script, genre, status, stage, started_at, youtube_scheduled_time)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'RUNNING', 'STARTING', CURRENT_TIMESTAMP, ?)""",
            (job_id, "autopilot", "autopilot", channel_id_str,
             prompt, prompt, genre, scheduled_iso))
        conn.commit()
    cmd = [
        sys.executable, "-m", "generator.worker_process",
        "--job-id", job_id,
        "--prompt", prompt,
        "--genre", genre,
    ]
    if scheduled_iso:
        cmd.extend(["--scheduled-time", scheduled_iso])
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    async def _monitor():
        stdout, stderr = await proc.communicate()
        if proc.returncode != 0:
            err = stderr.decode()[-800:] if stderr else f"exit {proc.returncode}"
            print(f"[autopilot] Job {job_id} failed: {err}")
        else:
            print(f"[autopilot] Job {job_id} completed successfully")
    asyncio.create_task(_monitor())
    return job_id
