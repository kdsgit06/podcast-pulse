# backend/main.py
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from pathlib import Path
import os, json, sqlite3

app = FastAPI()

# ---- CORS: allow only known origins (override via env if needed) ----
DEFAULT_ORIGINS = [
    "http://localhost:3000",                          # CRA dev
    os.getenv("VERCEL_FRONTEND", "").strip()          # set to https://<your>.vercel.app
]
ALLOWED = [o for o in DEFAULT_ORIGINS if o]
more = os.getenv("EXTRA_ORIGINS", "")
if more:
    ALLOWED += [x.strip() for x in more.split(",") if x.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED or ["*"],  # fallback to * if nothing provided
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---- Import downloader (works both as package and script) ----
try:
    from . import downloader  # package context
except Exception:
    import downloader          # script context

# ---- Static for simple UI (optional) ----
BASE_DIR = Path(__file__).parent.resolve()
STATIC_DIR = BASE_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")

@app.on_event("startup")
def ensure_dirs():
    (BASE_DIR / "downloads").mkdir(exist_ok=True)

class DownloadRequest(BaseModel):
    youtube_url: str

@app.get("/health")
def health():
    return {"ok": True}

@app.post("/download")
async def download_podcast(req: DownloadRequest):
    try:
        url = (req.youtube_url or "").strip()
        if not url:
            return {"error": "youtube_url is required"}

        result = downloader.download_audio_from_youtube(url)

        # If the worker returns a user-facing error, bubble it up with 200
        if isinstance(result, dict) and "error" in result:
            return {"error": result["error"]}

        video_id = result.get("video_id", "unknown")
        summary_path = BASE_DIR / "downloads" / f"{video_id}_summary.txt"
        if not summary_path.exists():
            return {"error": f"Summary not found for {video_id}"}

        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)

        return {
            "message": result.get("message", "ok"),
            "video_id": video_id,
            "summary": summary_data
        }
    except Exception as e:
        # Never leak 500 stacktraces to UI
        return {"error": f"Unexpected: {str(e)}"}

@app.get("/history")
async def get_history():
    db_path = BASE_DIR / "podcast_history.db"
    if not db_path.exists():
        return {"history": []}
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("SELECT video_id, timestamp FROM summaries")
        rows = cur.fetchall()
        return {"history": [{"video_id": v, "timestamp": t} for (v, t) in rows]}
    except Exception:
        return {"history": []}
    finally:
        try:
            conn.close()
        except Exception:
            pass

@app.get("/")
def root():
    return {"message": "Podcast Pulse API - open /static/index.html"}
