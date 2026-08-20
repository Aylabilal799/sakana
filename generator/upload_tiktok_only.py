#!/usr/bin/env python3
"""Standalone TikTok upload script — called via subprocess with hard timeout."""
import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_ROOT))

from tiktokautouploader import upload_tiktok


def main():
    parser = argparse.ArgumentParser(description="Upload a video to TikTok")
    parser.add_argument("--video-path", required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--account", required=True)
    parser.add_argument("--hashtags", default="[]")
    parser.add_argument("--schedule", default=None)
    parser.add_argument("--day", type=int, default=None)
    args = parser.parse_args()

    hashtags = json.loads(args.hashtags) if args.hashtags else []
    schedule_kwargs = {}
    if args.schedule:
        schedule_kwargs["schedule"] = args.schedule
    if args.day:
        schedule_kwargs["day"] = args.day

    try:
        upload_tiktok(
            video=args.video_path,
            description=args.title,
            accountname=args.account,
            hashtags=hashtags,
            headless=True,
            stealth=True,
            suppressprint=True,
            **schedule_kwargs
        )
        result = {"success": True, "url": f"https://www.tiktok.com/@{args.account}"}
        print(json.dumps(result))
        sys.exit(0)
    except Exception as e:
        result = {"success": False, "error": str(e)}
        print(json.dumps(result))
        sys.exit(1)


if __name__ == "__main__":
    main()
