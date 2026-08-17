import asyncio
import logging
import os
import random
import sqlite3
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, Optional

from generator.agnes_client import AgnesClient
from generator.pipeline import VideoPipeline
from generator.seo_generator import SEOGenerator
from generator.story_generator import StoryGenerator
from generator.youtube_uploader import YouTubeUploader

logger = logging.getLogger(__name__)

# PKT is UTC+5
PKT_OFFSET = timedelta(hours=5)

# Schedule times in PKT (24h format)
SCHEDULE_TIMES_PKT = [
    (21, 0),   # 9:00 PM PKT
    (2, 0),    # 2:00 AM PKT
    (5, 0),    # 5:00 AM PKT
]

# Minimum gap between runs to avoid API burden (in minutes)
MIN_GAP_MINUTES = 45


class AutopilotScheduler:
    """Background scheduler that auto-generates and uploads Mia videos on a fixed schedule."""

    def __init__(
        self,
        bot=None,
        notification_channel_id: Optional[int] = None,
        db_path: Optional[str] = None,
    ):
        self.bot = bot
        self.notification_channel_id = notification_channel_id or int(
            os.getenv("AUTOPILOT_NOTIFICATION_CHANNEL_ID", "0")
        )
        self.db_path = db_path or "/root/sakana/data/autopilot.db"
        self.enabled = os.getenv("YOUTUBE_AUTO_POST", "false").lower() in ("true", "1", "yes")
        self.project_dir = Path(os.getenv("PROJECT_DIRECTORY", "/root/sakana"))
        self.host_root = Path(os.getenv("OUTPUT_DIRECTORY", "/var/www/agnes-videos"))
        self.public_base = os.getenv("VIDEO_HOST_URL", "http://localhost:6464/videos").rstrip("/")

        self.agnes = AgnesClient()
        self.story_generator = StoryGenerator(self.agnes, db_path=self.db_path)
        self.youtube = YouTubeUploader()
        self.seo = SEOGenerator()
        self._running = False
        self._task = None

        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self):
        with self._connect() as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS autopilot_schedule (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    scheduled_pkt_time TEXT NOT NULL,
                    scheduled_utc_time TEXT NOT NULL,
                    job_id TEXT,
                    story_hash TEXT,
                    status TEXT DEFAULT 'pending',
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    started_at TIMESTAMP,
                    completed_at TIMESTAMP,
                    video_url TEXT,
                    youtube_video_id TEXT,
                    youtube_url TEXT,
                    error_message TEXT
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS autopilot_stats (
                    id INTEGER PRIMARY KEY CHECK(id = 1),
                    total_runs INTEGER DEFAULT 0,
                    successful_uploads INTEGER DEFAULT 0,
                    failed_uploads INTEGER DEFAULT 0,
                    last_run_at TIMESTAMP,
                    last_status TEXT
                )
            """)
            conn.execute("""
                INSERT OR IGNORE INTO autopilot_stats (id) VALUES (1)
            """)
            conn.commit()

    def start(self):
        """Start the autopilot scheduler in the background."""
        if not self.enabled:
            logger.info("Autopilot is DISABLED (YOUTUBE_AUTO_POST != true). Skipping scheduler start.")
            return
        if self._running:
            logger.warning("Autopilot scheduler already running")
            return
        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        logger.info("Autopilot scheduler STARTED. Enabled times (PKT): %s", SCHEDULE_TIMES_PKT)

    def stop(self):
        """Stop the autopilot scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            self._task = None
        logger.info("Autopilot scheduler STOPPED")

    async def _scheduler_loop(self):
        """Main scheduler loop — checks every minute for scheduled runs."""
        logger.info("Autopilot scheduler loop running")
        while self._running:
            try:
                now_pkt = self._now_pkt()
                next_run = self._get_next_run_time(now_pkt)

                if next_run:
                    wait_seconds = (next_run - self._now_pkt()).total_seconds()
                    if wait_seconds > 0:
                        logger.info("Next autopilot run at %s PKT (waiting %.0f minutes)",
                                   next_run.strftime("%H:%M"), wait_seconds / 60)
                        # Sleep in chunks to allow clean shutdown
                        while wait_seconds > 60 and self._running:
                            await asyncio.sleep(60)
                            wait_seconds = (next_run - self._now_pkt()).total_seconds()
                        if wait_seconds > 0 and self._running:
                            await asyncio.sleep(wait_seconds)

                    if self._running:
                        await self._run_autopilot_job(next_run)
                else:
                    # No scheduled runs found, wait and check again
                    await asyncio.sleep(60)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.exception("Autopilot scheduler error: %s", exc)
                await asyncio.sleep(300)  # Wait 5 minutes on error

    async def _run_autopilot_job(self, scheduled_time: datetime):
        """Execute one autopilot run: generate story → video → upload → notify."""
        job_id = f"auto_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"
        logger.info("=" * 60)
        logger.info("AUTOPILOT RUN STARTING: %s | Scheduled: %s PKT",
                   job_id, scheduled_time.strftime("%H:%M"))
        logger.info("=" * 60)

        # Record in DB
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO autopilot_schedule
                (scheduled_pkt_time, scheduled_utc_time, job_id, status, started_at)
                VALUES (?, ?, ?, 'running', CURRENT_TIMESTAMP)
            """, (
                scheduled_time.strftime("%H:%M"),
                datetime.now(timezone.utc).isoformat(),
                job_id,
            ))
            conn.commit()

        discord_notifs = []  # Collect notifications to send

        def status_callback(stage, progress, message):
            logger.info("[%s] %s (%d%%) %s", job_id, stage, progress, message)

        try:
            # Step 1: Generate unique story
            logger.info("[%s] Generating unique story...", job_id)
            plan = self.story_generator.generate_unique_story()
            story_hash = self.story_generator._hash_script(plan["script"])

            # Step 2: Run full pipeline
            logger.info("[%s] Running video pipeline...", job_id)
            pipeline = VideoPipeline(job_id, status_callback=status_callback)
            loop = asyncio.get_running_loop()
            metadata = await loop.run_in_executor(
                None, pipeline.run, plan["script"], plan.get("genre", "daily_vlog")
            )

            video_path = metadata["video"]["path"]
            video_url = metadata["video"]["url"]
            seo_path = metadata["seo_file"]["path"]

            # Step 3: Generate SEO
            youtube_meta = self.seo.generate(plan)

            # Step 4: Upload to YouTube (scheduled as private, will auto-publish)
            logger.info("[%s] Uploading to YouTube...", job_id)
            # Schedule for 5 minutes from now (or at the scheduled time if in future)
            publish_time = max(
                datetime.now(timezone.utc) + timedelta(minutes=5),
                self._pkt_to_utc(scheduled_time) + timedelta(minutes=5),
            )

            upload_result = await loop.run_in_executor(
                None,
                lambda: self.youtube.upload_video(
                    video_path=video_path,
                    title=youtube_meta.get("title", "Mia's Daily Vlog"),
                    description=youtube_meta.get("description", ""),
                    tags=youtube_meta.get("tags", []),
                    category_id=os.getenv("YOUTUBE_CATEGORY_ID", "22"),
                    privacy_status="private",
                    scheduled_time=publish_time,
                    thumbnail_path=None,  # Could generate thumbnail later
                )
            )

            youtube_video_id = upload_result.get("video_id")
            youtube_url = upload_result.get("youtube_url")

            # Update story record
            self.story_generator.update_story_status(
                script_hash=story_hash,
                job_id=job_id,
                youtube_video_id=youtube_video_id,
                status="uploaded",
            )

            # Update schedule record
            with self._connect() as conn:
                conn.execute("""
                    UPDATE autopilot_schedule
                    SET status = 'completed',
                        completed_at = CURRENT_TIMESTAMP,
                        video_url = ?,
                        youtube_video_id = ?,
                        youtube_url = ?,
                        story_hash = ?
                    WHERE job_id = ?
                """, (video_url, youtube_video_id, youtube_url, story_hash, job_id))
                conn.execute("""
                    UPDATE autopilot_stats
                    SET total_runs = total_runs + 1,
                        successful_uploads = successful_uploads + 1,
                        last_run_at = CURRENT_TIMESTAMP,
                        last_status = 'success'
                    WHERE id = 1
                """)
                conn.commit()

            # Discord notification
            discord_notifs.append({
                "type": "success",
                "job_id": job_id,
                "video_url": video_url,
                "youtube_url": youtube_url,
                "title": youtube_meta.get("title", "Mia's Daily Vlog"),
                "scheduled": scheduled_time.strftime("%H:%M PKT"),
            })
            logger.info("[%s] Autopilot run COMPLETED successfully", job_id)

        except Exception as exc:
            logger.exception("[%s] Autopilot run FAILED: %s", job_id, exc)
            with self._connect() as conn:
                conn.execute("""
                    UPDATE autopilot_schedule
                    SET status = 'failed',
                        completed_at = CURRENT_TIMESTAMP,
                        error_message = ?
                    WHERE job_id = ?
                """, (str(exc)[:500], job_id))
                conn.execute("""
                    UPDATE autopilot_stats
                    SET total_runs = total_runs + 1,
                        failed_uploads = failed_uploads + 1,
                        last_run_at = CURRENT_TIMESTAMP,
                        last_status = 'failed'
                    WHERE id = 1
                """)
                conn.commit()

            discord_notifs.append({
                "type": "error",
                "job_id": job_id,
                "error": str(exc)[:500],
                "scheduled": scheduled_time.strftime("%H:%M PKT"),
            })

        # Send Discord notifications
        if self.bot and self.notification_channel_id:
            await self._send_discord_notifications(discord_notifs)

        # Rest period between runs (at least MIN_GAP_MINUTES from now)
        next_available = datetime.now(timezone.utc) + timedelta(minutes=MIN_GAP_MINUTES)
        logger.info("[%s] Next autopilot job available after %s",
                   job_id, next_available.strftime("%H:%M UTC"))

    async def _send_discord_notifications(self, notifications):
        """Send autopilot notifications to Discord."""
        import discord as discord_module
        try:
            channel = self.bot.get_channel(self.notification_channel_id)
            if not channel:
                channel = await self.bot.fetch_channel(self.notification_channel_id)
            if not channel:
                logger.warning("Autopilot notification channel %s not found", self.notification_channel_id)
                return

            for notif in notifications:
                if notif["type"] == "success":
                    embed = discord_module.Embed(
                        title="✅ Mia Autopilot — Video Scheduled",
                        description=f"Job: `{notif['job_id']}`",
                        color=discord_module.Color.green(),
                    )
                    embed.add_field(name="📺 Title", value=notif["title"][:256], inline=False)
                    embed.add_field(name="🎬 Hosted Video", value=notif["video_url"], inline=False)
                    embed.add_field(name="📺 YouTube", value=notif["youtube_url"] or "Uploading...", inline=False)
                    embed.add_field(name="⏰ Scheduled", value=notif["scheduled"], inline=True)
                    embed.add_field(name="📊 Stats", value=self._get_stats_text(), inline=False)
                    await channel.send(embed=embed)
                else:
                    embed = discord_module.Embed(
                        title="❌ Mia Autopilot — Failed",
                        description=f"Job: `{notif['job_id']}`",
                        color=discord_module.Color.red(),
                    )
                    embed.add_field(name="⏰ Scheduled", value=notif["scheduled"], inline=True)
                    embed.add_field(name="Error", value=f"```{notif['error'][:900]}```", inline=False)
                    embed.add_field(name="📊 Stats", value=self._get_stats_text(), inline=False)
                    await channel.send(embed=embed)
        except Exception as exc:
            logger.exception("Failed to send autopilot Discord notification: %s", exc)

    def _get_stats_text(self) -> str:
        """Get formatted autopilot statistics."""
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM autopilot_stats WHERE id = 1").fetchone()
            if not row:
                return "No stats available"
        return (
            f"Total runs: {row['total_runs']} | "
            f"Successful: {row['successful_uploads']} | "
            f"Failed: {row['failed_uploads']} | "
            f"Last: {row['last_status']}"
        )

    def _now_pkt(self) -> datetime:
        """Get current time in PKT (UTC+5)."""
        return datetime.now(timezone.utc) + PKT_OFFSET

    def _pkt_to_utc(self, pkt_time: datetime) -> datetime:
        """Convert PKT time to UTC."""
        return pkt_time - PKT_OFFSET

    def _get_next_run_time(self, now_pkt: datetime) -> Optional[datetime]:
        """Find the next scheduled run time from now."""
        today = now_pkt.date()
        candidates = []

        for hour, minute in SCHEDULE_TIMES_PKT:
            # Today's time
            candidate = datetime.combine(today, datetime.min.time().replace(hour=hour, minute=minute))
            candidate = candidate.replace(tzinfo=now_pkt.tzinfo)
            if candidate <= now_pkt:
                # Already passed today, schedule for tomorrow
                candidate += timedelta(days=1)
            candidates.append(candidate)

        # Also check tomorrow's times
        for hour, minute in SCHEDULE_TIMES_PKT:
            candidate = datetime.combine(today + timedelta(days=1), datetime.min.time().replace(hour=hour, minute=minute))
            candidate = candidate.replace(tzinfo=now_pkt.tzinfo)
            candidates.append(candidate)

        # Filter out runs that are too close to now (respect MIN_GAP)
        min_time = now_pkt + timedelta(minutes=MIN_GAP_MINUTES)
        valid = [c for c in candidates if c >= min_time]

        if valid:
            return min(valid)
        return None

    def get_status(self) -> Dict:
        """Get current autopilot status."""
        next_run = self._get_next_run_time(self._now_pkt())
        stats = self._get_stats_text()
        return {
            "enabled": self.enabled,
            "running": self._running,
            "next_run_pkt": next_run.strftime("%H:%M PKT") if next_run else None,
            "next_run_utc": self._pkt_to_utc(next_run).isoformat() if next_run else None,
            "schedule_times_pkt": [f"{h:02d}:{m:02d}" for h, m in SCHEDULE_TIMES_PKT],
            "stats": stats,
            "notification_channel": self.notification_channel_id,
        }
