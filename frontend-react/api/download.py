# C:\Users\DELL\Desktop\projects\personal projects\podcast-pulse\frontend-react\api\download.py
import json
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from . import downloader  # Use a relative import  # Adjust import to reach the downloader module

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://podcast-pulse-xi.vercel.app", "http://localhost:3000"],
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
        # Vercel doesn’t persist files; use a temporary summary for now
        summary = {"title": "Test Summary", "topics": [{"name": "Test", "quotes_advice": ["Test advice"]}]}
        return {"message": result["message"], "video_id": video_id, "summary": summary}
    except Exception as e:
        print(f"Error in /download: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")