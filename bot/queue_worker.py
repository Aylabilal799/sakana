import asyncio
import json
import logging
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional

import discord

logger = logging.getLogger(__name__)
DB = os.getenv("JOB_DATABASE", "/root/sakana/jobs/queue.db")
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

STAGE_WEIGHTS = {
    "STORY_GENERATING": (5, "🧠 Writing Mia's story"),
    "OBJECT_REGISTRATION": (12, "📦 Tracking story objects"),
    "SOUND_DESIGN": (15, "🎵 Planning sound design"),
    "IDENTITY_READY": (18, " Mia identity ready"),
    "REFERENCE_GENERATING": (18, "👩 Creating Mia identity"),
    "TTS_GENERATING": (25, "🎙 Generating narration"),
    "SCENE_KEYFRAME_GENERATING": (30, "🎬 Generating scenes"),
    "SCENE_VIDEO_GENERATING": (55, "🎥 Animating scenes"),
    "AUDIO_MIXING": (72, "🔊 Mixing audio"),
    "CAPTION_GENERATING": (78, "💬 Creating captions"),
    "VIDEO_ASSEMBLY": (85, "✂️ Assembling video"),
    "FINAL_QA": (90, "🔍 Final quality check"),
    "SEO_GENERATING": (94, "📝 Creating SEO metadata"),
    "YOUTUBE_UPLOADING": (97, "📺 Uploading to YouTube"),
    "TIKTOK_UPLOADING": (98, "📱 Uploading to TikTok"),
    "COMPLETED": (100, "✅ Complete"),
    "FAILED": (0, "❌ Failed"),
}

def _make_bar(progress: int, length: int = 16) -> str:
    filled = max(0, min(length, int(round(progress / 100 * length))))
    return "█" * filled + "░" * (length - filled)

def _stage_info(step: str, progress: int, message: str = "") -> Dict:
    weight, label = STAGE_WEIGHTS.get(step, (progress, step))
    display_progress = progress if 0 < progress <= 100 else weight
    bar = _make_bar(display_progress)
    return {
        "progress": display_progress,
        "bar": bar,
        "label": label,
        "message": message,
    }

class JobQueue:
    def __init__(self, bot):
        self.bot = bot
        self._processing_lock = asyncio.Lock()
        self._progress_messages: Dict[str, discord.Message] = {}
        self._init_db()

    def _connect(self):
        connection = sqlite3.connect(DB, timeout=30)
        connection.row_factory = sqlite3.Row
        return connection

    def _init_db(self):
        Path(DB).parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY,
                discord_user_id TEXT,
                discord_username TEXT,
                discord_channel_id TEXT,
                prompt TEXT,
                script TEXT,
                genre TEXT DEFAULT 'auto',
                status TEXT DEFAULT 'PENDING',
                progress INTEGER DEFAULT 0,
                stage TEXT,
                current_step TEXT,
                status_message TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP,
                completed_at TIMESTAMP,
                error_message TEXT,
                output_path TEXT,
                output_url TEXT,
                seo_url TEXT,
                metadata_json TEXT,
                youtube_scheduled_time TEXT,
                youtube_video_id TEXT,
                youtube_uploaded INTEGER DEFAULT 0
            )""")
            existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            additions = {
                "discord_username": "TEXT", "prompt": "TEXT", "stage": "TEXT",
                "status_message": "TEXT", "output_path": "TEXT", "seo_url": "TEXT",
                "youtube_scheduled_time": "TEXT", "youtube_video_id": "TEXT",
                "youtube_uploaded": "INTEGER DEFAULT 0",
            }
            for column, sql_type in additions.items():
                if column not in existing:
                    conn.execute(f"ALTER TABLE jobs ADD COLUMN {column} {sql_type}")
            conn.execute("""UPDATE jobs SET status='FAILED', error_message=COALESCE(error_message,
                'Interrupted by bot restart; submit /mia again.'), completed_at=CURRENT_TIMESTAMP
                WHERE status NOT IN ('PENDING','COMPLETED','FAILED','CANCELLED')""")
            conn.commit()

    async def add_job(self, user_id, username, channel_id, prompt, genre="auto") -> str:
        job_id = uuid.uuid4().hex[:8]
        with self._connect() as conn:
            conn.execute("""INSERT INTO jobs
                (job_id, discord_user_id, discord_username, discord_channel_id, prompt, script, genre, status, stage)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 'QUEUED')""",
                (job_id, str(user_id), str(username), str(channel_id), prompt, prompt, genre))
            conn.commit()
        return job_id

    async def add_yt_job(self, user_id, username, channel_id, prompt, genre="auto", scheduled_time=None) -> str:
        job_id = uuid.uuid4().hex[:8]
        scheduled_iso = scheduled_time.isoformat() if scheduled_time else None
        with self._connect() as conn:
            conn.execute("""INSERT INTO jobs
                (job_id, discord_user_id, discord_username, discord_channel_id, prompt, script, genre, status, stage,
                 youtube_scheduled_time)
                VALUES (?, ?, ?, ?, ?, ?, ?, 'PENDING', 'QUEUED', ?)""",
                (job_id, str(user_id), str(username), str(channel_id), prompt, prompt, genre, scheduled_iso))
            conn.commit()
        return job_id

    @staticmethod
    def parse_scheduled_time(date_str: str, time_str: str) -> Optional[datetime]:
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

    async def get_status(self, job_id: str) -> Optional[Dict]:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    async def get_position(self, job_id: str) -> int:
        with self._connect() as conn:
            row = conn.execute("""SELECT COUNT(*) FROM jobs
                WHERE status='PENDING' AND created_at <=
                (SELECT created_at FROM jobs WHERE job_id=?)""", (job_id,)).fetchone()
            return int(row[0]) if row else 0

    async def list_pending(self) -> List[Dict]:
        with self._connect() as conn:
            rows = conn.execute("""SELECT * FROM jobs
                WHERE status IN ('PENDING','RUNNING') ORDER BY created_at""").fetchall()
            return [dict(row) for row in rows]

    async def process_next(self):
        if self._processing_lock.locked():
            return
        async with self._processing_lock:
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                row = conn.execute("SELECT * FROM jobs WHERE status='PENDING' ORDER BY created_at LIMIT 1").fetchone()
                if not row:
                    conn.commit()
                    return
                conn.execute("""UPDATE jobs SET status='RUNNING', stage='STARTING', progress=1,
                    started_at=CURRENT_TIMESTAMP, error_message=NULL WHERE job_id=?""", (row["job_id"],))
                conn.commit()
            await self._run_job(dict(row))

    async def _poll_progress(self, job_id: str):
        while True:
            try:
                await asyncio.sleep(5)
                status = await self.get_status(job_id)
                if status and status.get("stage"):
                    await self._update_progress_message(
                        job_id,
                        status["stage"],
                        status["progress"],
                        status.get("status_message") or ""
                    )
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("Progress poll error for %s: %s", job_id, exc)

    async def _run_job(self, job: Dict):
        job_id = job["job_id"]
        channel_id = int(job["discord_channel_id"])
        prompt = job.get("prompt") or job.get("script") or ""
        scheduled_time = job.get("youtube_scheduled_time")

        await self._create_progress_message(channel_id, job_id, prompt)

        cmd = [
            sys.executable, "-m", "generator.worker_process",
            "--job-id", job_id,
            "--prompt", prompt,
            "--genre", job.get("genre") or "auto",
        ]
        if scheduled_time:
            cmd.extend(["--scheduled-time", scheduled_time])

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )

        poll_task = asyncio.create_task(self._poll_progress(job_id))
        stdout, stderr = await proc.communicate()
        # Save worker output for debugging
        try:
            with open("/root/sakana/logs/worker.log", "a", encoding="utf-8") as wf:
                wf.write(f"\n=== Worker {job_id} stdout ===\n")
                wf.write(stdout.decode("utf-8", errors="replace")[-4000:] + "\n")
                wf.write(f"=== Worker {job_id} stderr ===\n")
                wf.write(stderr.decode("utf-8", errors="replace")[-4000:] + "\n")
        except Exception:
            pass
        # Log worker output for debugging
        try:
            with open("/root/sakana/logs/worker.log", "a") as wf:
                wf.write(f"\n=== Worker {job_id} ===\n")
                wf.write(f"STDOUT:\n{stdout.decode()[-3000:]}\n")
                wf.write(f"STDERR:\n{stderr.decode()[-3000:]}\n")
        except Exception:
            pass
        poll_task.cancel()

        try:
            await poll_task
        except asyncio.CancelledError:
            pass

        if proc.returncode != 0:
            error_msg = stderr.decode()[-1500:] if stderr else f"Worker exited with code {proc.returncode}"
            logger.error("Worker failed for %s: %s", job_id, error_msg)
            status = await self.get_status(job_id) or {}
            stage = status.get("stage") or "UNKNOWN"
            with self._connect() as conn:
                conn.execute(
                    """UPDATE jobs SET status='FAILED', progress=COALESCE(progress, 0),
                       completed_at=CURRENT_TIMESTAMP, error_message=? WHERE job_id=?""",
                    (error_msg, job_id)
                )
                conn.commit()
            await self._notify_error(job_id, stage, error_msg)
            return

        status = await self.get_status(job_id) or {}
        metadata = {}
        if status.get("metadata_json"):
            try:
                metadata = json.loads(status["metadata_json"])
            except json.JSONDecodeError:
                logger.warning("Could not parse metadata_json for %s", job_id)

        yt_result = None
        if status.get("youtube_video_id"):
            yt_result = {
                "video_id": status["youtube_video_id"],
                "youtube_url": f"https://youtube.com/watch?v={status['youtube_video_id']}",
                "privacy_status": "private",
                "scheduled_time": status.get("youtube_scheduled_time"),
            }

        await self._send_done(job_id, metadata, yt_result)

    async def _create_progress_message(self, channel_id, job_id, prompt):
        try:
            channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            if not channel:
                return
            info = _stage_info("STORY_GENERATING", 0, "Starting...")
            embed = discord.Embed(
                title="🎬 Mia AI Video Generation",
                description=f"Job: `{job_id}`",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Prompt", value=prompt[:300] + "..." if len(prompt) > 300 else prompt, inline=False)
            embed.add_field(name="Progress", value=f"`{info['bar']}` {info['progress']}%", inline=False)
            embed.add_field(name="Stage", value=info['label'], inline=True)
            embed.add_field(name="Update", value=info['message'] or "Initializing...", inline=True)
            msg = await channel.send(embed=embed)
            self._progress_messages[job_id] = msg
        except Exception as exc:
            logger.error("Failed to create progress message for %s: %s", job_id, exc)

    async def _update_progress_message(self, job_id, stage, progress, message):
        msg = self._progress_messages.get(job_id)
        if not msg:
            return
        try:
            info = _stage_info(stage, progress, message)
            embed = discord.Embed(
                title="🎬 Mia AI Video Generation",
                description=f"Job: `{job_id}`",
                color=discord.Color.blurple(),
            )
            embed.add_field(name="Progress", value=f"`{info['bar']}` {info['progress']}%", inline=False)
            embed.add_field(name="Stage", value=info['label'], inline=True)
            embed.add_field(name="Update", value=message[:500] or info['message'], inline=True)
            await msg.edit(embed=embed)
        except Exception as exc:
            logger.error("Failed to update progress message for %s: %s", job_id, exc)

    async def _send_done(self, job_id, metadata, yt_result=None):
        msg = self._progress_messages.pop(job_id, None)
        video = metadata.get("video", {})
        seo = metadata.get("seo_file", {})
        youtube = metadata.get("youtube", {})

        try:
            embed = discord.Embed(
                title="✅ Mia video completed",
                description=f"Job: `{job_id}`\n`{_make_bar(100)}` 100%",
                color=discord.Color.green(),
            )
            embed.add_field(name="🎬 Video", value=video.get("url", "Unavailable"), inline=False)
            embed.add_field(name="⏱ Duration", value=f"{video.get('duration', 0):.2f} seconds", inline=True)
            embed.add_field(name="🎙 Voice", value=metadata.get("audio", {}).get("voice", "Kokoro"), inline=True)
            embed.add_field(name="📐 Format", value="1080×1920 · 9:16", inline=True)
            embed.add_field(name="🎞 Scenes", value=str(video.get("scenes", 0)), inline=True)
            embed.add_field(name="📝 SEO file", value=seo.get("url", "Unavailable"), inline=False)
            embed.add_field(name="📌 YouTube title", value=youtube.get("title", "Mia Vlog")[:256], inline=False)

            if yt_result:
                if yt_result.get("video_id"):
                    embed.add_field(
                        name="📺 YouTube",
                        value=f"[Watch on YouTube]({yt_result.get('youtube_url')})\n"
                              f"Privacy: `{yt_result.get('privacy_status')}`\n"
                              f"Scheduled: `{yt_result.get('scheduled_time')}`",
                        inline=False,
                    )
                elif yt_result.get("error"):
                    embed.add_field(name="⚠️ YouTube Upload Error", value=f"```{yt_result['error'][:500]}```", inline=False)

            # ===== TIKTOK EMBED BLOCK =====
            tiktok = metadata.get("tiktok", {})
            if tiktok.get("url"):
                embed.add_field(
                    name="📱 TikTok",
                    value=f"[View on TikTok]({tiktok['url']})",
                    inline=False,
                )
            elif tiktok.get("error"):
                embed.add_field(
                    name="⚠️ TikTok Upload Error",
                    value=f"```{tiktok['error'][:500]}```",
                    inline=False,
                )
            # ===== END TIKTOK EMBED BLOCK =====

            if msg:
                await msg.edit(embed=embed)
            else:
                channel_id = int(metadata.get("discord_channel_id", 0))
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    msg = await channel.send(embed=embed)

            if msg:
                seo_path = seo.get("path")
                if seo_path and Path(seo_path).is_file():
                    await msg.reply(file=discord.File(seo_path, filename="mia_youtube.txt"))

                video_path = video.get("path")
                if video_path and Path(video_path).is_file():
                    size = Path(video_path).stat().st_size
                    if size <= 9 * 1024 * 1024:
                        try:
                            await msg.reply(file=discord.File(video_path, filename="mia_video.mp4"))
                        except discord.HTTPException as exc:
                            logger.warning("Discord video upload skipped for %s: %s", job_id, exc)
                    else:
                        await msg.reply(f"📎 Video file ({size/1024/1024:.1f} MiB): {video.get('url', 'Unavailable')}")
        except Exception as exc:
            logger.exception("Completion notification failed for %s: %s", job_id, exc)

    async def _notify_error(self, job_id, stage, error):
        msg = self._progress_messages.pop(job_id, None)
        try:
            info = _stage_info(stage, 0, error)
            embed = discord.Embed(
                title="❌ Mia generation failed",
                description=f"Job: `{job_id}`\n`{info['bar']}` {info['progress']}%",
                color=discord.Color.red(),
            )
            embed.add_field(name="Stage", value=info['label'], inline=False)
            embed.add_field(name="Error", value=f"```{error[:900]}```", inline=False)
            if msg:
                await msg.edit(embed=embed)
            else:
                status_info = await self.get_status(job_id)
                if status_info:
                    channel_id = int(status_info.get("discord_channel_id", 0))
                    channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                    if channel:
                        await channel.send(embed=embed)
        except Exception as exc:
            logger.error("Failure notification failed for %s: %s", job_id, exc)
