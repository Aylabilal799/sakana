#!/usr/bin/env python3
"""One-time TikTok login script. Run this ONCE on your local machine with a screen."""
from tiktokautouploader import upload_tiktok

upload_tiktok(
    video="/root/sakana/dummy_video.mp4",
    description="Login test",
    accountname="miasmoments_i",  # <-- CHANGE THIS to your actual username
    headless=False,  # Browser window pops up — log in manually
)
print("Login complete! Session cookies saved.")
