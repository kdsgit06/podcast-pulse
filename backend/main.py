from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import os, json, sqlite3

# ---- App ----
app = FastAPI()

# Open CORS during bring-up (tighten later to your domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],   # includes OPTIONS
    allow_headers=["*"],
)

# ---- Imports (works both locally and on Railway) ----
try:
    from . import downloader  # when package context exists
except Exception:
    import downloader          # fallback

# ---- Paths & Static ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)  # ensure exists

# Serve your simple UI at /static/index.html
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

# Ensure downloads dir exists on boot
@app.on_event("startup")
def ensure_dirs():
    (BASE_DIR / "downloads").mkdir(exist_ok=True)

# ---- Schemas ----
class DownloadRequest(BaseModel):
    youtube_url: str

# ---- Routes ----
@app.post("/download")
async def download_podcast(req: DownloadRequest):
    try:
        result = downloader.download_audio_from_youtube(req.youtube_url)

        # ---- demo-friendly: never 500 for known errors ----
        if isinstance(result, dict) and "error" in result:
            return {"error": result["error"]}   # 200 with message

        video_id = result.get("video_id", "unknown")
        summary_path = BASE_DIR / "downloads" / f"{video_id}_summary.txt"
        if not summary_path.exists():
            return {"error": f"Summary not found for {video_id}"}

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)

        return {"message": result.get("message", "ok"), "video_id": video_id, "summary": summary_data}
    except Exception as e:
        # final safety net; should rarely hit during demo
        return {"error": f"Unexpected: {str(e)}"}


@app.get("/history")
async def get_history():
    conn = sqlite3.connect(str(BASE_DIR / "podcast_history.db"))
    try:
        cur = conn.cursor()
        cur.execute("SELECT video_id, timestamp FROM summaries")
        rows = cur.fetchall()
        return {"history": [{"video_id": v, "timestamp": t} for (v, t) in rows]}
    finally:
        conn.close()

@app.get("/")
def root():
    return {"message": "Podcast Pulse API - open /static/index.html"}
