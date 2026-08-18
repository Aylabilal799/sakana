#!/usr/bin/env python3
"""youtube_auth_setup.py — One-time manual OAuth setup for Mia Moments (headless VPS).

Run this on the VPS:

    cd /root/sakana
    source venv/bin/activate
    python generator/youtube_auth_setup.py

It will:
  1. Print an OAuth URL.
  2. You open it in YOUR browser (make sure Mia Moments account is active).
  3. After clicking Allow, Google redirects to localhost (will show an error page — that's OK).
  4. Copy the ?code=... value from the browser's address bar.
  5. Paste the code back into the terminal.
  6. It saves the token and verifies the channel is "Mia Moments."
"""

import os
import sys
import json
import logging
import urllib.parse

PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from google_auth_oauthlib.flow import InstalledAppFlow
from generator.youtube_auth import (
    YOUTUBE_SCOPES,
    CLIENT_SECRETS_FILE,
    TOKEN_FILE,
    verify_mia_channel,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(message)s",
)
logger = logging.getLogger("youtube_setup")


def run_oauth_flow():
    print("\n" + "=" * 60)
    print("  Mia Moments — YouTube OAuth Setup")
    print("=" * 60)

    if not os.path.exists(CLIENT_SECRETS_FILE):
        print(f"\n❌ Client secrets file NOT FOUND:\n   {CLIENT_SECRETS_FILE}")
        print("\nPlease copy your youtube_client_secret.json to that path.")
        print("Download it from: https://console.cloud.google.com/apis/credentials")
        sys.exit(1)

    print(f"\n📄 Client secrets: {CLIENT_SECRETS_FILE}")
    print(f"💾 Token will be saved to: {TOKEN_FILE}")
    print(f"🔐 Scopes requested:")
    for s in YOUTUBE_SCOPES:
        print(f"   • {s}")

    # Build the flow
    flow = InstalledAppFlow.from_client_secrets_file(
        CLIENT_SECRETS_FILE,
        scopes=YOUTUBE_SCOPES,
    )
    # CRITICAL: Set redirect_uri so Google accepts the request
    flow.redirect_uri = 'http://localhost:9219/'

    # Generate authorization URL
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        include_granted_scopes="true",
    )

    print("\n" + "-" * 60)
    print("STEP 1: Open this URL in your browser (on your computer):")
    print("-" * 60)
    print(auth_url)
    print("-" * 60)
    print("⚠️  MAKE SURE you are logged into the Mia Moments Google account!")
    print("-" * 60)

    print("\nSTEP 2: Click 'Allow' on the Google consent screen.")
    print("STEP 3: Your browser will redirect to a localhost URL that fails — this is NORMAL.")
    print("        The address bar will look like:")
    print("        http://localhost:9219/?state=...&code=4/0AX4...&scope=...")
    print("\nSTEP 4: Copy ONLY the code value (the part after &code= and before &scope=)")
    print("        Example: 4/0AX4XfWgF5qGD7N17... (very long string)")

    auth_code = input("\nPaste the authorization code here: ").strip()

    if not auth_code:
        print("❌ No code provided. Exiting.")
        sys.exit(1)

    # Clean up the code if they accidentally pasted the full URL
    if "code=" in auth_code:
        parsed = urllib.parse.urlparse(auth_code)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            auth_code = params["code"][0]
            print(f"Extracted code from URL: {auth_code[:20]}...")

    # Exchange the authorization code for tokens
    print("\n⏳ Exchanging code for tokens...")
    try:
        flow.fetch_token(code=auth_code)
    except Exception as e:
        print(f"\n❌ Token exchange failed: {e}")
        print("\nCommon causes:")
        print("  • Code expired (only valid for a few minutes)")
        print("  • Wrong Google account selected")
        print("  • Redirect URI mismatch in Google Cloud Console")
        sys.exit(1)

    creds = flow.credentials

    # Save token
    token_data = json.loads(creds.to_json())
    os.makedirs(os.path.dirname(TOKEN_FILE) or ".", exist_ok=True)
    with open(TOKEN_FILE, "w") as f:
        json.dump(token_data, f, indent=2)

    print(f"\n✅ Token saved to: {TOKEN_FILE}")

    # Verify it's the right channel
    try:
        verify_mia_channel("mia")
        print("\n🎉 Setup complete! Mia Moments is ready for /miayt uploads.")
    except RuntimeError as e:
        print(f"\n❌ {e}")
        print("\nThe token file has been saved anyway, but it's for the WRONG channel.")
        print("To fix:")
        print(f"  rm {TOKEN_FILE}")
        print("  Then re-run this script while logged into the correct account.")
        sys.exit(1)


if __name__ == "__main__":
    run_oauth_flow()
