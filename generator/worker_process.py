#!/usr/bin/env python3
"""Standalone worker process for video generation + YouTube upload + TikTok upload."""
import argparse
import json
import logging
import logging.handlers
import os
import random
import sqlite3
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv
env_path = PROJECT_ROOT / "config" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

import requests
from generator.pipeline import VideoPipeline
from generator.youtube_uploader import YouTubeUploader

log_path = "/root/sakana/logs/worker.log"
Path(log_path).parent.mkdir(parents=True, exist_ok=True)
handler = logging.handlers.RotatingFileHandler(log_path, maxBytes=5*1024*1024, backupCount=3, encoding="utf-8")
handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"))
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[handler, logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("worker_process")

DB = os.getenv("JOB_DATABASE", "/root/sakana/jobs/queue.db")
MAX_TIMEOUT_RETRIES = 3
TIMEOUT_RETRY_DELAY = 60
QUEUE_RETRY_MIN = 180
QUEUE_RETRY_MAX = 300
TIKTOK_UPLOAD_TIMEOUT = 300
TIKTOK_UPLOAD_RETRIES = 3
TIKTOK_UPLOAD_RETRY_DELAY = 60


def update_progress(job_id: str, stage: str, progress: int, message: str) -> None:
    try:
        with sqlite3.connect(DB, timeout=30) as conn:
            conn.execute(
                """UPDATE jobs SET status='RUNNING', stage=?, current_step=?, progress=?, status_message=?
                   WHERE job_id=?""",
                (stage, stage, int(progress), message, job_id)
            )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to update progress for %s: %s", job_id, exc)


def mark_completed(job_id: str, metadata: dict, yt_video_id: str = None) -> None:
    try:
        with sqlite3.connect(DB, timeout=30) as conn:
            conn.execute(
                """UPDATE jobs SET status='COMPLETED', stage='COMPLETED', progress=100,
                   current_step='COMPLETED', status_message='Mia video completed', completed_at=CURRENT_TIMESTAMP,
                   output_path=?, output_url=?, seo_url=?, metadata_json=?, youtube_video_id=?, youtube_uploaded=?
                   WHERE job_id=?""",
                (
                    metadata.get("video", {}).get("path"),
                    metadata.get("video", {}).get("url"),
                    metadata.get("seo_file", {}).get("url"),
                    json.dumps(metadata),
                    yt_video_id,
                    1 if yt_video_id else 0,
                    job_id,
                )
            )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to mark completed for %s: %s", job_id, exc)


def mark_failed(job_id: str, error: str) -> None:
    try:
        with sqlite3.connect(DB, timeout=30) as conn:
            conn.execute(
                """UPDATE jobs SET status='FAILED', progress=COALESCE(progress, 0),
                   completed_at=CURRENT_TIMESTAMP, error_message=?
                   WHERE job_id=?""",
                (error, job_id)
            )
            conn.commit()
    except Exception as exc:
        logger.error("Failed to mark failed for %s: %s", job_id, exc)


def _is_queue_full_error(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "video_queue_full" in msg
        or "queue is full" in msg
        or ("503" in msg and "busy" in msg)
    )


def _kill_orphan_browsers():
    """Kill any stuck chromium or playwright processes left by a timed-out upload."""
    try:
        subprocess.run(["pkill", "-f", "chromium"], capture_output=True, timeout=5)
        subprocess.run(["pkill", "-f", "playwright"], capture_output=True, timeout=5)
        logger.info("Cleaned up orphan browser processes")
    except Exception:
        pass


def _upload_tiktok_with_timeout(
    video_path: str,
    title: str,
    account: str,
    hashtags: list,
    schedule: str = None,
    day: int = None,
    job_id: str = ""
) -> tuple:
    """
    Run TikTok upload in a subprocess with a hard timeout.
    Returns (success: bool, result: dict).
    """
    cmd = [
        sys.executable,
        str(PROJECT_ROOT / "generator" / "upload_tiktok_only.py"),
        "--video-path", video_path,
        "--title", title,
        "--account", account,
        "--hashtags", json.dumps(hashtags),
    ]
    if schedule:
        cmd.extend(["--schedule", schedule])
    if day:
        cmd.extend(["--day", str(day)])

    logger.info("Starting TikTok upload subprocess for %s (timeout=%ds)", job_id, TIKTOK_UPLOAD_TIMEOUT)

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TIKTOK_UPLOAD_TIMEOUT,
        )
        last_line = result.stdout.strip().split("\n")[-1]
        output = json.loads(last_line)

        if result.returncode == 0 and output.get("success"):
            logger.info("TikTok upload subprocess succeeded for %s", job_id)
            return True, output
        else:
            logger.warning("TikTok upload subprocess failed for %s: %s", job_id, output.get("error", "Unknown"))
            return False, output

    except subprocess.TimeoutExpired:
        logger.error("TikTok upload subprocess TIMED OUT after %ds for %s", TIKTOK_UPLOAD_TIMEOUT, job_id)
        _kill_orphan_browsers()
        return False, {"error": f"TikTok upload timed out after {TIKTOK_UPLOAD_TIMEOUT}s"}

    except Exception as e:
        logger.exception("TikTok upload subprocess crashed for %s", job_id)
        _kill_orphan_browsers()
        return False, {"error": str(e)}


def run_job(job_id: str, prompt: str, genre: str, scheduled_time_iso: str = None) -> dict:
    def callback(stage, progress, message):
        update_progress(job_id, stage, progress, message)
        print(json.dumps({"type": "progress", "stage": stage, "progress": progress, "message": message}), flush=True)

    pipeline = VideoPipeline(job_id, status_callback=callback)
    metadata = pipeline.run(prompt, genre)

    video_path = metadata.get("video", {}).get("path")
    title = metadata.get("youtube", {}).get("title", "Mia\'s Daily Vlog")

    # Phase 2: YouTube upload
    yt_video_id = None
    try:
        update_progress(job_id, "YOUTUBE_UPLOADING", 97, "📺 Uploading to YouTube...")
        print(json.dumps({"type": "progress", "stage": "YOUTUBE_UPLOADING", "progress": 97, "message": "📺 Uploading to YouTube..."}), flush=True)

        yt_uploader = YouTubeUploader()
        scheduled_dt = datetime.fromisoformat(scheduled_time_iso) if scheduled_time_iso else None

        yt_result = yt_uploader.upload_video(
            video_path=video_path,
            title=title,
            description=metadata.get("youtube", {}).get("description", ""),
            tags=metadata.get("youtube", {}).get("tags", []),
            category_id=os.getenv("YOUTUBE_CATEGORY_ID", "22"),
            privacy_status="private",
            scheduled_time=scheduled_dt,
        )
        yt_video_id = yt_result.get("video_id")
        logger.info("YouTube upload successful: video_id=%s", yt_video_id)
        print(json.dumps({"type": "youtube", "video_id": yt_video_id}), flush=True)
    except Exception as yt_exc:
        logger.exception("YouTube upload failed for %s", job_id)
        print(json.dumps({"type": "youtube_error", "error": str(yt_exc)}), flush=True)

    # Phase 3: TikTok upload with subprocess timeout + retry loop
    tiktok_url = None
    tiktok_account = os.getenv("TIKTOK_ACCOUNT_NAME", "")

    if not tiktok_account:
        logger.warning("TIKTOK_ACCOUNT_NAME not set in .env — skipping TikTok upload")
        metadata["tiktok"] = {"error": "TIKTOK_ACCOUNT_NAME not configured in .env"}
    else:
        tags = metadata.get("youtube", {}).get("tags", [])
        hashtags = [f"#{t.replace(' ', '')}" for t in tags[:5] if t] or ["#MiaVlog", "#DailyVlog", "#Storytime"]

        schedule = None
        day = None
        if scheduled_time_iso:
            dt = datetime.fromisoformat(scheduled_time_iso)
            schedule = dt.strftime("%H:%M")
            day = dt.day

        for tt_attempt in range(1, TIKTOK_UPLOAD_RETRIES + 1):
            update_progress(
                job_id,
                "TIKTOK_UPLOADING",
                98,
                f"📱 Uploading to TikTok... (attempt {tt_attempt}/{TIKTOK_UPLOAD_RETRIES})"
            )
            print(json.dumps({
                "type": "progress",
                "stage": "TIKTOK_UPLOADING",
                "progress": 98,
                "message": f"📱 Uploading to TikTok... (attempt {tt_attempt}/{TIKTOK_UPLOAD_RETRIES})"
            }), flush=True)

            success, result = _upload_tiktok_with_timeout(
                video_path=video_path,
                title=title,
                account=tiktok_account,
                hashtags=hashtags,
                schedule=schedule,
                day=day,
                job_id=job_id,
            )

            if success:
                tiktok_url = result.get("url", f"https://www.tiktok.com/@{tiktok_account}")
                logger.info("TikTok upload successful for %s on attempt %d", job_id, tt_attempt)
                print(json.dumps({"type": "tiktok", "url": tiktok_url}), flush=True)
                break

            logger.warning(
                "TikTok upload attempt %d/%d failed for %s: %s",
                tt_attempt, TIKTOK_UPLOAD_RETRIES, job_id, result.get("error", "Unknown")
            )

            if tt_attempt < TIKTOK_UPLOAD_RETRIES:
                logger.info("Waiting %ds before TikTok retry...", TIKTOK_UPLOAD_RETRY_DELAY)
                update_progress(
                    job_id,
                    "TIKTOK_UPLOADING",
                    98,
                    f"⏳ TikTok failed, retrying in {TIKTOK_UPLOAD_RETRY_DELAY}s (attempt {tt_attempt}/{TIKTOK_UPLOAD_RETRIES})"
                )
                time.sleep(TIKTOK_UPLOAD_RETRY_DELAY)
            else:
                logger.error("All %d TikTok upload attempts failed for %s", TIKTOK_UPLOAD_RETRIES, job_id)
                metadata["tiktok"] = {"error": f"All {TIKTOK_UPLOAD_RETRIES} attempts failed. Last: {result.get('error', 'Unknown')}"}

        if tiktok_url:
            metadata["tiktok"] = {"url": tiktok_url}

    mark_completed(job_id, metadata, yt_video_id)
    return metadata


def main():
    parser = argparse.ArgumentParser(description="Run Mia video generation + YouTube upload worker")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--genre", default="auto")
    parser.add_argument("--scheduled-time", default=None, help="ISO format UTC datetime for YouTube scheduling")
    args = parser.parse_args()

    last_error = None
    timeout_attempts = 0
    queue_full_attempts = 0
    attempt = 0

    while True:
        attempt += 1
        logger.info("Worker starting job %s (attempt %d)", args.job_id, attempt)
        try:
            run_job(args.job_id, args.prompt, args.genre, args.scheduled_time)
            print(json.dumps({"type": "completed"}), flush=True)
            logger.info("Worker completed job %s on attempt %d", args.job_id, attempt)
            return

        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            timeout_attempts += 1
            last_error = e
            logger.warning("Agnes AI API timeout (timeout attempt %d/%d): %s", timeout_attempts, MAX_TIMEOUT_RETRIES, e)
            if timeout_attempts < MAX_TIMEOUT_RETRIES:
                logger.info("Sleeping %ds before retry...", TIMEOUT_RETRY_DELAY)
                time.sleep(TIMEOUT_RETRY_DELAY)
            else:
                logger.error("All %d timeout attempts exhausted", MAX_TIMEOUT_RETRIES)
                mark_failed(args.job_id, f"API timeout after {MAX_TIMEOUT_RETRIES} attempts: {last_error}")
                print(json.dumps({"type": "failed", "error": f"API timeout after {MAX_TIMEOUT_RETRIES} retries: {last_error}"}), flush=True)
                sys.exit(1)

        except Exception as exc:
            err_msg = str(exc)

            if _is_queue_full_error(exc):
                queue_full_attempts += 1
                sleep_sec = random.randint(QUEUE_RETRY_MIN, QUEUE_RETRY_MAX)
                last_error = exc
                logger.warning(
                    "Agnes video queue full after internal retries (queue-full attempt %d), "
                    "sleeping %ds (~%dmin) then resuming job...",
                    queue_full_attempts, sleep_sec, sleep_sec // 60
                )
                update_progress(
                    args.job_id,
                    "SCENE_VIDEO_GENERATING",
                    55,
                    f"⏳ Agnes queue full — resuming in ~{sleep_sec // 60}min (queue attempt {queue_full_attempts})"
                )
                time.sleep(sleep_sec)
                continue

            logger.exception("Worker failed for job %s (non-retryable error)", args.job_id)
            mark_failed(args.job_id, err_msg)
            print(json.dumps({"type": "failed", "error": err_msg}), flush=True)
            sys.exit(1)


if __name__ == "__main__":
    main()
