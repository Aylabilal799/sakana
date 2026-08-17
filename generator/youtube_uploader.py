import json
import logging
import os
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import quote

import httplib2
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

logger = logging.getLogger(__name__)

# YouTube Data API v3 scopes
YOUTUBE_UPLOAD_SCOPE = "https://www.googleapis.com/auth/youtube.upload"
YOUTUBE_READWRITE_SCOPE = "https://www.googleapis.com/auth/youtube"
API_SERVICE_NAME = "youtube"
API_VERSION = "v3"

# Default paths — can be overridden by env
DEFAULT_CLIENT_SECRETS = "/root/deepseekyt/youtube_client_secret.json"
DEFAULT_TOKEN_FILE = "/root/deepseekyt/youtube_token.json"


class YouTubeUploader:
    """Upload videos to YouTube with OAuth2, supporting scheduled publish."""

    def __init__(
        self,
        client_secrets_file: Optional[str] = None,
        token_file: Optional[str] = None,
        max_retries: int = 5,
    ):
        self.client_secrets_file = client_secrets_file or os.getenv(
            "YOUTUBE_CLIENT_SECRETS_FILE", DEFAULT_CLIENT_SECRETS
        )
        self.token_file = token_file or os.getenv(
            "YOUTUBE_TOKEN_FILE", DEFAULT_TOKEN_FILE
        )
        self.max_retries = int(os.getenv("YOUTUBE_MAX_UPLOAD_ATTEMPTS", max_retries))
        self.oauth_port = int(os.getenv("YOUTUBE_OAUTH_PORT", "9219"))
        self._credentials = None
        self._youtube = None

    def _get_credentials(self) -> Credentials:
        """Load or refresh OAuth2 credentials."""
        creds = None

        if Path(self.token_file).exists():
            try:
                creds = Credentials.from_authorized_user_file(
                    self.token_file,
                    scopes=[YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READWRITE_SCOPE]
                )
                logger.info("Loaded YouTube credentials from %s", self.token_file)
            except Exception as exc:
                logger.warning("Failed to load token file: %s", exc)

        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(Request())
                logger.info("Refreshed YouTube OAuth token")
            except Exception as exc:
                logger.error("Failed to refresh token: %s", exc)
                creds = None

        if not creds or not creds.valid:
            if not Path(self.client_secrets_file).exists():
                raise FileNotFoundError(
                    f"YouTube client secrets not found at {self.client_secrets_file}. "
                    f"Download from Google Cloud Console and place there."
                )
            flow = InstalledAppFlow.from_client_secrets_file(
                self.client_secrets_file,
                scopes=[YOUTUBE_UPLOAD_SCOPE, YOUTUBE_READWRITE_SCOPE],
            )
            creds = flow.run_local_server(port=self.oauth_port, open_browser=False)
            # Save token for future runs
            Path(self.token_file).parent.mkdir(parents=True, exist_ok=True)
            with open(self.token_file, "w") as f:
                f.write(creds.to_json())
            logger.info("Saved new YouTube token to %s", self.token_file)

        self._credentials = creds
        return creds

    def _get_service(self):
        """Lazy-load the YouTube API service."""
        if self._youtube is None:
            creds = self._get_credentials()
            self._youtube = build(
                API_SERVICE_NAME, API_VERSION,
                credentials=creds,
                cache_discovery=False,
                static_discovery=False,
            )
        return self._youtube

    def upload_video(
        self,
        video_path: str,
        title: str,
        description: str,
        tags: list,
        category_id: str = "22",
        privacy_status: str = "private",
        scheduled_time: Optional[datetime] = None,
        thumbnail_path: Optional[str] = None,
    ) -> Dict:
        """Upload a video to YouTube.

        Args:
            video_path: Path to the MP4 file
            title: Video title
            description: Video description
            tags: List of tags
            category_id: YouTube category ID (22 = People & Blogs)
            privacy_status: "private", "unlisted", or "public"
            scheduled_time: If set and privacy_status="private", schedules publish at this time (UTC)
            thumbnail_path: Optional thumbnail image path
        """
        youtube = self._get_service()

        # Build snippet
        snippet = {
            "title": title[:100],  # YouTube max title length
            "description": description[:5000],
            "tags": tags[:500],
            "categoryId": category_id,
        }

        status = {
            "privacyStatus": privacy_status,
            "selfDeclaredMadeForKids": False,
        }

        # Schedule publish if provided (requires privacyStatus=private)
        if scheduled_time and privacy_status == "private":
            status["publishAt"] = scheduled_time.strftime("%Y-%m-%dT%H:%M:%SZ")
            logger.info("Scheduling video for: %s", status["publishAt"])

        body = {
            "snippet": snippet,
            "status": status,
        }

        media = MediaFileUpload(
            video_path,
            mimetype="video/mp4",
            resumable=True,
        )

        # Execute upload with retry
        request = youtube.videos().insert(
            part=",".join(body.keys()),
            body=body,
            media_body=media,
        )

        response = self._execute_with_retry(request)
        video_id = response.get("id")

        # Upload thumbnail if provided
        if thumbnail_path and Path(thumbnail_path).exists() and video_id:
            try:
                youtube.thumbnails().set(
                    videoId=video_id,
                    media_body=MediaFileUpload(thumbnail_path, mimetype="image/png"),
                ).execute()
                logger.info("Thumbnail uploaded for video %s", video_id)
            except Exception as exc:
                logger.warning("Thumbnail upload failed: %s", exc)

        return {
            "video_id": video_id,
            "title": title,
            "privacy_status": privacy_status,
            "scheduled_time": scheduled_time.isoformat() if scheduled_time else None,
            "youtube_url": f"https://www.youtube.com/watch?v={video_id}" if video_id else None,
            "embed_url": f"https://www.youtube.com/embed/{video_id}" if video_id else None,
        }

    def _execute_with_retry(self, request):
        """Execute a YouTube API request with exponential backoff."""
        retry = 0
        while retry < self.max_retries:
            try:
                response = request.execute()
                return response
            except HttpError as exc:
                if exc.resp.status in (500, 502, 503, 504):
                    retry += 1
                    wait = 2 ** retry
                    logger.warning("YouTube API error %s, retrying in %ds (%d/%d)...",
                                   exc.resp.status, wait, retry, self.max_retries)
                    time.sleep(wait)
                else:
                    raise
            except Exception as exc:
                retry += 1
                wait = 2 ** retry
                logger.warning("YouTube upload error: %s, retrying in %ds (%d/%d)...",
                               exc, wait, retry, self.max_retries)
                time.sleep(wait)
        raise RuntimeError(f"YouTube upload failed after {self.max_retries} retries")

    def get_upload_status(self, video_id: str) -> Dict:
        """Check the status of an uploaded video."""
        youtube = self._get_service()
        response = youtube.videos().list(
            part="status,snippet",
            id=video_id,
        ).execute()
        items = response.get("items", [])
        if not items:
            return {"found": False}
        item = items[0]
        return {
            "found": True,
            "title": item["snippet"]["title"],
            "privacy_status": item["status"]["privacyStatus"],
            "upload_status": item["status"].get("uploadStatus"),
            "publish_at": item["status"].get("publishAt"),
        }

    def test_auth(self) -> bool:
        """Test if YouTube authentication is working."""
        try:
            youtube = self._get_service()
            response = youtube.channels().list(part="snippet", mine=True).execute()
            channels = response.get("items", [])
            if channels:
                logger.info("YouTube auth OK. Channel: %s",
                           channels[0]["snippet"]["title"])
                return True
            return False
        except Exception as exc:
            logger.error("YouTube auth test failed: %s", exc)
            return False
