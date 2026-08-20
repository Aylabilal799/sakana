from tiktokautouploader import upload_tiktok

upload_tiktok(
    video="/path/to/any/video.mp4",  # any video file you have locally
    description="test",
    accountname="your_tiktok_username",
    headless=False  # browser window pops up — log in manually here
)
