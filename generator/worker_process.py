#!/usr/bin/env python3
"""Standalone worker process for video generation + YouTube upload."""
import argparse
import json
import logging
import logging.handlers
import os
import sqlite3
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

# Log to file so we can see retries and API issues after the fact
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
MAX_RETRIES = 3
RETRY_DELAY = 60  # seconds


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


def run_job(job_id: str, prompt: str, genre: str, scheduled_time_iso: str = None) -> dict:
    def callback(stage, progress, message):
        update_progress(job_id, stage, progress, message)
        print(json.dumps({"type": "progress", "stage": stage, "progress": progress, "message": message}), flush=True)

    pipeline = VideoPipeline(job_id, status_callback=callback)
    metadata = pipeline.run(prompt, genre)

    # Phase 2: YouTube upload (ALWAYS — private by default, scheduled if time given)
    yt_video_id = None
    try:
        update_progress(job_id, "YOUTUBE_UPLOADING", 97, "📺 Uploading to YouTube...")
        print(json.dumps({"type": "progress", "stage": "YOUTUBE_UPLOADING", "progress": 97, "message": "📺 Uploading to YouTube..."}), flush=True)

        yt_uploader = YouTubeUploader()
        scheduled_dt = datetime.fromisoformat(scheduled_time_iso) if scheduled_time_iso else None

        yt_result = yt_uploader.upload_video(
            video_path=metadata.get("video", {}).get("path"),
            title=metadata.get("youtube", {}).get("title", "Mia's Daily Vlog"),
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
    for attempt in range(1, MAX_RETRIES + 1):
        logger.info("Worker starting job %s (attempt %d/%d)", args.job_id, attempt, MAX_RETRIES)
        try:
            run_job(args.job_id, args.prompt, args.genre, args.scheduled_time)
            print(json.dumps({"type": "completed"}), flush=True)
            logger.info("Worker completed job %s on attempt %d", args.job_id, attempt)
            return  # Success — exit cleanly
        except (requests.exceptions.ReadTimeout, requests.exceptions.ConnectTimeout) as e:
            last_error = e
            logger.warning("Agnes AI API timeout on attempt %d/%d: %s", attempt, MAX_RETRIES, e)
            if attempt < MAX_RETRIES:
                logger.info("Sleeping %ds before retry...", RETRY_DELAY)
                time.sleep(RETRY_DELAY)
            else:
                logger.error("All %d attempts exhausted due to API timeout", MAX_RETRIES)
        except Exception as exc:
            # Non-timeout error — fail immediately, no point retrying code bugs
            logger.exception("Worker failed for job %s (non-retryable error)", args.job_id)
            mark_failed(args.job_id, str(exc))
            print(json.dumps({"type": "failed", "error": str(exc)}), flush=True)
            sys.exit(1)

    # If we get here, all retries were timeouts
    mark_failed(args.job_id, f"Agnes AI API timeout after {MAX_RETRIES} attempts: {last_error}")
    print(json.dumps({"type": "failed", "error": f"API timeout after {MAX_RETRIES} retries: {last_error}"}), flush=True)
    sys.exit(1)


if __name__ == "__main__":
    main()
