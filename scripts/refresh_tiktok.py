#!/usr/bin/env python3
"""
Daily TikTok session refresh — visits TikTok with existing cookies
to keep the session warm. Uses Playwright directly (no upload).
Run via cron with xvfb-run on headless servers.
"""
import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
env_path = PROJECT_ROOT / "config" / ".env"
if env_path.exists():
    load_dotenv(dotenv_path=env_path)

ACCOUNT = os.getenv("TIKTOK_ACCOUNT_NAME", "")
if not ACCOUNT:
    print("ERROR: TIKTOK_ACCOUNT_NAME not set in .env")
    sys.exit(1)

COOKIES_FILE = PROJECT_ROOT / f"TK_cookies_{ACCOUNT}.json"
TIKTOK_URL = "https://www.tiktok.com/upload"


def load_cookies():
    if not COOKIES_FILE.exists():
        return None
    with open(COOKIES_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def save_cookies(cookies):
    with open(COOKIES_FILE, "w", encoding="utf-8") as f:
        json.dump(cookies, f, indent=2)
    print(f"Cookies saved to {COOKIES_FILE}")


def refresh_session():
    """Visit TikTok upload page with existing cookies to refresh session."""
    cookies = load_cookies()
    if cookies is None:
        print(f"No cookies file found at {COOKIES_FILE}")
        print("You need to log in manually first.")
        return False

    age_hours = (time.time() - COOKIES_FILE.stat().st_mtime) / 3600
    print(f"Cookie age: {age_hours:.1f} hours")

    try:
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-accelerated-2d-canvas",
                "--disable-gpu",
            ])
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
            )

            # Load existing cookies
            context.add_cookies(cookies)
            print(f"Loaded {len(cookies)} cookies")

            page = context.new_page()
            print(f"Navigating to {TIKTOK_URL}...")

            # Visit TikTok upload page — this refreshes the session
            page.goto(TIKTOK_URL, timeout=60000, wait_until="networkidle")

            # Wait a moment for any session refresh
            time.sleep(5)

            # Check if we're still logged in (look for upload form or profile indicator)
            page_content = page.content()
            if "login" in page_content.lower() and "phone" in page_content.lower():
                print("SESSION EXPIRED — redirected to login page")
                browser.close()
                return False

            # Save refreshed cookies
            refreshed_cookies = context.cookies()
            save_cookies(refreshed_cookies)

            browser.close()
            print("Session refresh successful — cookies updated")
            return True

    except ImportError:
        print("ERROR: playwright not installed. Run: pip install playwright && playwright install chromium")
        return False
    except Exception as e:
        err_msg = str(e).lower()
        if any(x in err_msg for x in ["login", "unauthorized", "session"]):
            print(f"SESSION EXPIRED: {e}")
            return False
        print(f"Refresh error (session may still be valid): {e}")
        return False


if __name__ == "__main__":
    success = refresh_session()
    sys.exit(0 if success else 1)
