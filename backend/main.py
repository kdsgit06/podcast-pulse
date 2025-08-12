from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from dotenv import load_dotenv
import downloader
import os
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
import json
import sqlite3

# Load environment variables
load_dotenv()
api_key = os.getenv("GEMINI_API_KEY")  # Optional

app = FastAPI()

# Enable CORS with deployed frontend URL and local development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://podcast-pulse.vercel.app", "http://localhost:3000", "http://192.168.1.6", "http://127.0.0.1", "*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class URLRequest(BaseModel):
    youtube_url: str

@app.post("/download")
async def download_podcast(request: URLRequest):
    try:
        print(f"Processing URL: {request.youtube_url}")  # Debug
        result = downloader.download_audio_from_youtube(request.youtube_url)
        video_id = result.get("video_id", "unknown")
        if "error" in result:
            raise HTTPException(status_code=500, detail=f"Error processing request: {result['error']}")
        # Check and read the summary file
        summary_path = f"downloads/{video_id}_summary.txt"
        if os.path.exists(summary_path):
            with open(summary_path, "r", encoding="utf-8") as f:
                summary_data = json.load(f)
        else:
            summary_data = {"error": "Summary file not found"}
        # Store in SQLite
        conn = sqlite3.connect('podcast_history.db')
        c = conn.cursor()
        c.execute("INSERT INTO summaries (video_id, timestamp) VALUES (?, CURRENT_TIMESTAMP)", (video_id,))
        conn.commit()
        conn.close()
        return {"message": result["message"], "video_id": video_id, "summary": summary_data}
    except Exception as e:
        print(f"Error in /download: {str(e)}")  # Debug
        raise HTTPException(status_code=500, detail=f"Error processing request: {str(e)}")

@app.get("/history")
async def get_history():
    conn = sqlite3.connect('podcast_history.db')
    c = conn.cursor()
    c.execute("SELECT video_id, timestamp FROM summaries")
    history = [{"video_id": row[0], "timestamp": row[1]} for row in c.fetchall()]
    conn.close()
    return {"history": history}

@app.post("/feedback")
async def submit_feedback(feedback: str):
    try:
        print(f"Received feedback: {feedback}")  # Debug
        with open("feedback.txt", "a", encoding="utf-8") as f:
            f.write(f"{feedback}\n")
        return {"message": "Feedback received successfully"}
    except Exception as e:
        print(f"Error in /feedback: {str(e)}")  # Debug
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")

# Mount the frontend folder


# Serve index.html directly for root
@app.get("/", response_class=FileResponse)
async def read_index():
    return FileResponse("frontend/index.html", media_type="text/html")

# Initialize SQLite database
def init_db():
    conn = sqlite3.connect('podcast_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS summaries
                 (video_id TEXT PRIMARY KEY, timestamp TEXT)''')
    conn.commit()
    conn.close()

init_db()

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000, reload=True)