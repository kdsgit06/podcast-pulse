from fastapi import FastAPI
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from .downloader import download_audio_from_youtube
import json
import sqlite3

app = FastAPI()
app.mount("/static", StaticFiles(directory="frontend"), name="static")

@app.get("/")
async def read_root():
    return RedirectResponse(url="/static/index.html")

@app.get("/favicon.ico")
async def favicon():
    return {"message": "No favicon"}, 204

@app.post("/download")
async def download_podcast(youtube_url: str):
    try:
        video_id = youtube_url.split('=')[-1]
        print(f"Debug: Looking for file in downloads/{video_id}_summary.txt")
        download_audio_from_youtube(youtube_url)
        with open(f"downloads/{video_id}_summary.txt", "r", encoding="utf-8") as f:
            summary = f.read()
        return {"summary": json.loads(summary)}
    except FileNotFoundError:
        return {"error": f"Summary file for {video_id} not found. Check if transcription completed."}
    except json.JSONDecodeError:
        return {"error": f"Invalid JSON in summary file for {video_id}."}
    except Exception as e:
        return {"error": str(e)}

@app.get("/history")
async def get_history():
    conn = sqlite3.connect('podcast_history.db')
    c = conn.cursor()
    c.execute("SELECT video_id, summary, timestamp FROM summaries ORDER BY timestamp DESC LIMIT 5")
    history = [{"video_id": row[0], "summary": json.loads(row[1]), "timestamp": row[2]} for row in c.fetchall()]
    conn.close()
    return {"history": history}