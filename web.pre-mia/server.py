import logging
import mimetypes
import os
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse

logger = logging.getLogger(__name__)
app = FastAPI(title="Mia Hosted Assets", version="2.0.0")
OUTPUT = Path(os.getenv("OUTPUT_DIRECTORY", "/var/www/agnes-videos")).resolve()
SAFE_JOB = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
SAFE_FILE = re.compile(r"^[A-Za-z0-9_. -]{1,180}$")


@app.get("/videos/{job_id}/{filename}")
async def get_asset(job_id: str, filename: str):
    if not SAFE_JOB.fullmatch(job_id) or not SAFE_FILE.fullmatch(filename):
        raise HTTPException(status_code=404, detail="File not found")
    candidate = (OUTPUT / job_id / filename).resolve()
    try:
        candidate.relative_to(OUTPUT)
    except ValueError:
        logger.warning("Blocked path traversal attempt: %s/%s", job_id, filename)
        raise HTTPException(status_code=404, detail="File not found")
    if not candidate.is_file():
        logger.info("Hosted file not found: %s", candidate)
        raise HTTPException(status_code=404, detail="File not found")
    media_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
    return FileResponse(candidate, media_type=media_type, filename=candidate.name, content_disposition_type="inline")


@app.get("/", response_class=PlainTextResponse)
async def root():
    return "Mia video hosting is online\n"
