import discord
import os, sqlite3, asyncio, logging
from pathlib import Path
from typing import Optional, Dict, List
from generator.pipeline import VideoPipeline

logger = logging.getLogger(__name__)
DB = "/root/sakana/jobs/queue.db"

class JobQueue:
    def __init__(self, bot):
        self.bot = bot
        self._init_db()

    def _init_db(self):
        Path(DB).parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(DB) as conn:
            conn.execute("""CREATE TABLE IF NOT EXISTS jobs (
                job_id TEXT PRIMARY KEY, discord_user_id TEXT, discord_channel_id TEXT,
                script TEXT, genre TEXT, status TEXT DEFAULT 'PENDING', progress INTEGER DEFAULT 0,
                current_step TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                started_at TIMESTAMP, completed_at TIMESTAMP, error_message TEXT,
                output_url TEXT, metadata_json TEXT)""")
            conn.commit()

    async def add_job(self, user_id, channel_id, script, genre="story") -> str:
        import uuid
        jid = uuid.uuid4().hex[:8]
        with sqlite3.connect(DB) as conn:
            conn.execute("INSERT INTO jobs (job_id,discord_user_id,discord_channel_id,script,genre,status) VALUES (?,?,?,?,?,'PENDING')",
                        (jid, str(user_id), str(channel_id), script, genre))
            conn.commit()
        return jid

    async def get_status(self, job_id) -> Optional[Dict]:
        with sqlite3.connect(DB) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM jobs WHERE job_id=?", (job_id,)).fetchone()
            return dict(row) if row else None

    async def get_position(self, job_id) -> int:
        with sqlite3.connect(DB) as conn:
            row = conn.execute("SELECT COUNT(*) FROM jobs WHERE status='PENDING' AND created_at < (SELECT created_at FROM jobs WHERE job_id=?)", (job_id,)).fetchone()
            return row[0] + 1 if row else 0

    async def list_pending(self) -> List[Dict]:
        with sqlite3.connect(DB) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute("SELECT * FROM jobs WHERE status NOT IN ('COMPLETED','FAILED','CANCELLED') ORDER BY created_at").fetchall()
            return [dict(r) for r in rows]

    async def process_next(self):
        with sqlite3.connect(DB) as conn:
            running = conn.execute("SELECT COUNT(*) FROM jobs WHERE status NOT IN ('PENDING','COMPLETED','FAILED','CANCELLED')").fetchone()[0]
            if running > 0: return
            row = conn.execute("SELECT * FROM jobs WHERE status='PENDING' ORDER BY created_at LIMIT 1").fetchone()
            if not row: return
            job_id, channel_id, script, genre = row[0], int(row[2]), row[3], row[4] or "story"
        await self._run_job(job_id, channel_id, script, genre)

    async def _run_job(self, job_id, channel_id, script, genre):
        self._update(job_id, "SCRIPT_PROCESSING", 5)
        try:
            loop = asyncio.get_event_loop()
            def cb(step, prog, msg):
                self._update(job_id, step, prog, msg)
                asyncio.run_coroutine_threadsafe(self._notify(channel_id, job_id, step, prog, msg), loop)
            pipeline = VideoPipeline(job_id, status_callback=cb)
            meta = await loop.run_in_executor(None, pipeline.run, script, genre)
            hostname = os.getenv("PUBLIC_HOSTNAME", "localhost")
            url = f"http://{hostname}:8080/videos/{job_id}/video.mp4"
            self._update(job_id, "COMPLETED", 100, output_url=url)
            await self._send_done(channel_id, job_id, meta, url)
        except Exception as e:
            logger.exception(f"Job {job_id} failed")
            self._update(job_id, "FAILED", error=str(e))
            await self._notify_error(channel_id, job_id, str(e))

    def _update(self, job_id, status=None, progress=None, step_name=None, output_url=None, error=None):
        with sqlite3.connect(DB) as conn:
            sets, vals = [], []
            if status: sets.append("status=?"); vals.append(status)
            if status=="COMPLETED": sets.append("completed_at=CURRENT_TIMESTAMP")
            elif status and status not in ["PENDING","COMPLETED","FAILED","CANCELLED"]: sets.append("started_at=COALESCE(started_at,CURRENT_TIMESTAMP)")
            if progress is not None: sets.append("progress=?"); vals.append(progress)
            if step_name: sets.append("current_step=?"); vals.append(step_name)
            if output_url: sets.append("output_url=?"); vals.append(output_url)
            if error: sets.append("error_message=?"); vals.append(error)
            if sets:
                vals.append(job_id)
                conn.execute(f"UPDATE jobs SET {','.join(sets)} WHERE job_id=?", vals)
                conn.commit()

    async def _notify(self, channel_id, job_id, step, progress, message):
        try:
            ch = self.bot.get_channel(channel_id)
            if ch and progress in [20, 50, 80, 95]:
                await ch.send(f"⏳ Job `{job_id[:8]}` — {message} ({progress}%)")
        except Exception as e:
            logger.error(f"Notify failed: {e}")

    async def _send_done(self, channel_id, job_id, meta, url):
        try:
            ch = self.bot.get_channel(channel_id)
            if not ch: return
            yt = meta.get("youtube", {})
            embed = discord.Embed(title="✅ Video Complete!", description=f"Job: `{job_id}`", color=discord.Color.green())
            embed.add_field(name="🎥 URL", value=url, inline=False)
            embed.add_field(name="📌 Title", value=yt.get("title","N/A")[:256], inline=False)
            embed.add_field(name="🏷️ Tags", value=", ".join(yt.get("tags",[])[:10]), inline=False)
            embed.add_field(name="#️⃣ Hashtags", value=" ".join(yt.get("hashtags",[])), inline=False)
            await ch.send(embed=embed)
            vp = meta.get("video", {}).get("path")
            if vp and Path(vp).exists():
                file_size = Path(vp).stat().st_size
                max_discord_size = 9 * 1024 * 1024

                if file_size <= max_discord_size:
                    try:
                        await ch.send(file=discord.File(vp))
                    except discord.HTTPException as e:
                        logger.warning(
                            f"Discord attachment failed for {job_id}: {e}. "
                            f"Public URL was already sent: {url}"
                        )
                else:
                    logger.info(
                        f"Skipping Discord attachment for {job_id}: "
                        f"{file_size / 1024 / 1024:.1f} MiB exceeds safe limit. "
                        f"Public URL sent: {url}"
                    )
        except Exception as e:
            logger.error(f"Send done failed: {e}")

    async def _notify_error(self, channel_id, job_id, error):
        try:
            ch = self.bot.get_channel(channel_id)
            if ch:
                await ch.send(embed=discord.Embed(title=f"❌ Job `{job_id}` Failed",
                              description=f"```{error[:1000]}```", color=discord.Color.red()))
        except Exception as e:
            logger.error(f"Error notify failed: {e}")
