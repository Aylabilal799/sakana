import asyncio
import json
import logging
import os
import sqlite3
import uuid
from pathlib import Path
from typing import Dict, List, Optional

import discord

from generator.pipeline import VideoPipeline

logger = logging.getLogger(__name__)
DB = os.getenv("JOB_DATABASE", "/root/sakana/jobs/queue.db")
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED"}

# Progress stage labels and weights for the Discord bar
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
    "COMPLETED": (100, "✅ Complete"),
    "FAILED": (0, "❌ Failed"),
}


def _make_bar(progress: int, length: int = 16) -> str:
    filled = max(0, min(length, int(round(progress / 100 * length))))
    return "█" * filled + "░" * (length - filled)


def _stage_info(step: str, progress: int, message: str = "") -> Dict:
    weight, label = STAGE_WEIGHTS.get(step, (progress, step))
    # Use actual progress if available and reasonable, else fall back to stage weight
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
                metadata_json TEXT
            )""")
            existing = {row[1] for row in conn.execute("PRAGMA table_info(jobs)")}
            additions = {
                "discord_username": "TEXT", "prompt": "TEXT", "stage": "TEXT",
                "status_message": "TEXT", "output_path": "TEXT", "seo_url": "TEXT",
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

    async def _run_job(self, job: Dict):
        job_id = job["job_id"]
        channel_id = int(job["discord_channel_id"])
        prompt = job.get("prompt") or job.get("script") or ""
        loop = asyncio.get_running_loop()

        # Create the single progress message
        await self._create_progress_message(channel_id, job_id, prompt)

        try:
            def callback(stage, progress, message):
                self._update_progress(job_id, stage, progress, message)
                asyncio.run_coroutine_threadsafe(
                    self._update_progress_message(job_id, stage, progress, message), loop
                )

            pipeline = VideoPipeline(job_id, status_callback=callback)
            metadata = await loop.run_in_executor(None, pipeline.run, prompt, job.get("genre") or "auto")
            video = metadata.get("video", {})
            seo = metadata.get("seo_file", {})
            with self._connect() as conn:
                conn.execute("""UPDATE jobs SET status='COMPLETED', stage='COMPLETED', progress=100,
                    current_step='COMPLETED', status_message='Mia video completed', completed_at=CURRENT_TIMESTAMP,
                    output_path=?, output_url=?, seo_url=?, metadata_json=? WHERE job_id=?""",
                    (video.get("path"), video.get("url"), seo.get("url"), json.dumps(metadata), job_id))
                conn.commit()
            await self._send_done(job_id, metadata)
        except Exception as exc:
            logger.exception("Mia job %s failed", job_id)
            status = await self.get_status(job_id) or {}
            stage = status.get("stage") or "UNKNOWN"
            with self._connect() as conn:
                conn.execute("""UPDATE jobs SET status='FAILED', progress=COALESCE(progress,0),
                    completed_at=CURRENT_TIMESTAMP, error_message=? WHERE job_id=?""", (str(exc), job_id))
                conn.commit()
            await self._notify_error(job_id, stage, str(exc))

    def _update_progress(self, job_id: str, stage: str, progress: int, message: str) -> None:
        with self._connect() as conn:
            conn.execute("""UPDATE jobs SET status='RUNNING', stage=?, current_step=?, progress=?, status_message=?
                WHERE job_id=?""", (stage, stage, int(progress), message, job_id))
            conn.commit()

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
            # Re-add prompt from the message content if possible, or keep it minimal
            embed.add_field(name="Progress", value=f"`{info['bar']}` {info['progress']}%", inline=False)
            embed.add_field(name="Stage", value=info['label'], inline=True)
            embed.add_field(name="Update", value=message[:500] or info['message'], inline=True)
            await msg.edit(embed=embed)
        except Exception as exc:
            logger.error("Failed to update progress message for %s: %s", job_id, exc)

    async def _send_done(self, job_id, metadata):
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

            if msg:
                await msg.edit(embed=embed)
            else:
                channel_id = int(metadata.get("discord_channel_id", 0))
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
                if channel:
                    msg = await channel.send(embed=embed)

            # Send files as follow-up messages
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
