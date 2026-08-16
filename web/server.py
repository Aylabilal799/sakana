import os
from fastapi import FastAPI
from fastapi.responses import FileResponse

app = FastAPI()
OUTPUT = "/root/sakana/output"

@app.get("/videos/{job_id}/video.mp4")
async def get_video(job_id: str):
    path = os.path.join(OUTPUT, job_id, "video.mp4")
    if os.path.exists(path):
        return FileResponse(path, media_type="video/mp4")
    return {"error": "Video not found"}

@app.get("/")
async def root():
    return {"status": "Agnes Pipeline", "version": "1.0.0"}
