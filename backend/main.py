from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
from . import downloader
import os
import sqlite3
import json

# Load environment variables
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class DownloadRequest(BaseModel):
    youtube_url: str

@app.post("/download")
async def download_podcast(request: DownloadRequest):
    try:
        print(f"Processing URL: {request.youtube_url}")
        result = downloader.download_audio_from_youtube(request.youtube_url)
        video_id = result.get("video_id", "unknown")
        if "error" in result:
            raise HTTPException(status_code=500, detail=f"Error processing request: {result['error']}")
        summary_path = f"downloads/{video_id}_summary.txt"
        with open(summary_path, "r", encoding="utf-8") as f:
            summary_data = json.load(f)
        return {"message": result["message"], "video_id": video_id, "summary": summary_data}
    except Exception as e:
        print(f"Error in /download: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/history")
async def get_history():
    conn = sqlite3.connect('podcast_history.db')
    c = conn.cursor()
    c.execute("SELECT video_id, timestamp FROM summaries")
    history = [{"video_id": row[0], "timestamp": row[1]} for row in c.fetchall()]
    conn.close()
    return {"history": history}

@app.get("/")
async def redirect_root():
    return {"message": "Podcast Pulse API - Use /download with POST"}

@app.get("/api")
async def api_root():
    return {"message": "Podcast Pulse API - Use /download with POST"}