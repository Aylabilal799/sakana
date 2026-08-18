"""youtube_auth.py — OAuth credential loading & channel verification for YouTube Data API.

This module:
  1. Loads/refreshes the cached OAuth token.
  2. Provides get_credentials() for uploaders.
  3. Provides get_channel_info() to verify WHICH channel the token belongs to
     (so you can confirm it's "Mia Moments" before going live).
"""

import os
import json
import logging

from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

logger = logging.getLogger(__name__)

# BOTH scopes are required:
#   youtube.upload  → upload videos
#   youtube         → set publishAt (scheduled publishing)
YOUTUBE_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

CLIENT_SECRETS_FILE = os.getenv(
    "YOUTUBE_CLIENT_SECRETS_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_client_secret.json"),
)
TOKEN_FILE = os.getenv(
    "YOUTUBE_TOKEN_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "youtube_token.json"),
)


def get_credentials() -> Credentials:
    """Loads the cached user token and refreshes it if expired.

    Raises:
        RuntimeError: If no token file exists or the token is invalid/unrefreshable.
    """
    if not os.path.exists(TOKEN_FILE):
        raise RuntimeError(
            f"No YouTube OAuth token found at:\n  {TOKEN_FILE}\n\n"
            "Run the manual setup script to authorize Mia Moments:\n"
            "  cd /root/sakana && source venv/bin/activate && python generator/youtube_auth_setup.py"
        )

    creds = Credentials.from_authorized_user_file(TOKEN_FILE, YOUTUBE_SCOPES)

    if creds and creds.expired and creds.refresh_token:
        logger.info("[YouTube Auth] Access token expired, refreshing...")
        creds.refresh(Request())
        # Persist refreshed token
        with open(TOKEN_FILE, "w") as f:
            f.write(creds.to_json())
        logger.info("[YouTube Auth] Token refreshed and saved")

    if not creds or not creds.valid:
        raise RuntimeError(
            "YouTube OAuth token is invalid and could not be refreshed.\n"
            "Re-run the setup script:\n"
            "  cd /root/sakana && source venv/bin/activate && python generator/youtube_auth_setup.py"
        )

    logger.info("[YouTube Auth] Credentials loaded successfully from %s", TOKEN_FILE)
    return creds


def get_channel_info(credentials: Credentials = None) -> dict:
    """Fetches the authorized user's YouTube channel info.

    Returns:
        dict with keys: id, title, url, subscriber_count, video_count
    """
    creds = credentials or get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    # "mine=True" returns the channel belonging to the authorized user
    response = youtube.channels().list(part="snippet,statistics,contentDetails", mine=True).execute()

    items = response.get("items", [])
    if not items:
        raise RuntimeError("No YouTube channel found for this Google account.")

    ch = items[0]
    snippet = ch.get("snippet", {})
    stats = ch.get("statistics", {})

    info = {
        "id": ch.get("id"),
        "title": snippet.get("title", "Unknown"),
        "url": f"https://youtube.com/channel/{ch.get('id')}",
        "custom_url": snippet.get("customUrl"),  # e.g. @miamoments
        "subscriber_count": stats.get("subscriberCount", "hidden"),
        "video_count": stats.get("videoCount", 0),
        "description": snippet.get("description", "")[:200],
    }

    # Prefer custom URL if available
    if info["custom_url"]:
        info["url"] = f"https://youtube.com/{info['custom_url']}"

    return info


def verify_mia_channel(expected_name_substring: str = "mia") -> dict:
    """Loads credentials and prints the connected channel for human verification.

    Args:
        expected_name_substring: Case-insensitive substring to check in channel title.
                               Default is "mia" to match "Mia Moments".

    Returns:
        Channel info dict if verification passes.

    Raises:
        RuntimeError: If the channel name doesn't contain the expected substring.
    """
    print("=" * 60)
    print("  Mia Moments — YouTube Channel Verification")
    print("=" * 60)

    creds = get_credentials()
    info = get_channel_info(creds)

    print(f"\n✅ Authenticated successfully!")
    print(f"   Channel Name: {info['title']}")
    print(f"   Channel URL:  {info['url']}")
    print(f"   Videos:       {info['video_count']}")
    print(f"   Subscribers:  {info['subscriber_count']}")

    if expected_name_substring.lower() not in info['title'].lower():
        print(f"\n⚠️  WARNING: Channel name '{info['title']}' does NOT contain '{expected_name_substring}'.")
        print("   This token may be for the WRONG channel!")
        raise RuntimeError(
            f"Expected channel name to contain '{expected_name_substring}', "
            f"but got '{info['title']}'. "
            "Delete the token and re-authenticate with the correct Google account."
        )

    print(f"\n✅ Channel name contains '{expected_name_substring}' — looks correct!")
    print("=" * 60)
    return info


if __name__ == "__main__":
    # When run directly, just verify the channel
    logging.basicConfig(level=logging.INFO)
    verify_mia_channel("mia")
