from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
import os, json, sqlite3

# IMPORTANT: if downloader.py is in the same folder as main.py, this works:
import downloader
# If your imports fail on Railway, switch to: from . import downloader

app = FastAPI()

# keep wide-open during bring-up; we’ll tighten later
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],   # includes OPTIONS
    allow_headers=["*"],
)

@app.on_event("startup")
def ensure_dirs():
    os.makedirs("downloads", exist_ok=True)

class DownloadRequest(BaseModel):
    youtube_url: str

@app.post("/download")
async def download_podcast(req: DownloadRequest):
    try:
        result = downloader.download_audio_from_youtube(req.youtube_url)
        if "error" in result:
            raise HTTPException(status_code=500, detail=result["error"])

        video_id = result.get("video_id", "unknown")
        summary_path = f"downloads/{video_id}_summary.txt"
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)

        return {
            "message": result.get("message", "ok"),
            "video_id": video_id,
            "summary": summary_data
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/history")
async def get_history():
    conn = sqlite3.connect("podcast_history.db")
    c = conn.cursor()
    c.execute("SELECT video_id, timestamp FROM summaries")
    history = [{"video_id": row[0], "timestamp": row[1]} for row in c.fetchall()]
    conn.close()
    return {"history": history}

# Serve a simple page at /static/index.html
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def root():
    return {"message": "Open /static/index.html"}
