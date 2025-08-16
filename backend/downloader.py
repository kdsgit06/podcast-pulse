import yt_dlp
import sys
import assemblyai as aai
import nltk
import sqlite3
import google.generativeai as genai
from dotenv import load_dotenv
import os
import json

# Set NLTK data path
nltk.data.path.append(r"C:\Users\DELL\nltk_data")

# Load environment variables
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("Error: GOOGLE_API_KEY not found in .env file")
    sys.exit(1)
genai.configure(api_key=api_key)

aai.settings.api_key = "6da0232e68c1446cb3b4228212bd0e95"

def transcribe_audio(file_path):
    try:
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(file_path)
        while transcript.status not in [aai.TranscriptStatus.completed, aai.TranscriptStatus.error]:
            transcript = transcriber.get_transcript(transcript.id)
        if transcript.status == aai.TranscriptStatus.completed:
            return transcript.text
        raise Exception(f"Transcription failed: {transcript.status}")
    except Exception as e:
        raise Exception(f"Transcription error: {str(e)}")

def summarize_with_gemini(transcript_text, title):
    try:
        print(f"Debug: Summarizing transcript of length {len(transcript_text)} characters")
        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content(
            f"You are a podcast analysis expert. Given the podcast titled '{title}', analyze the transcript and extract timeless wisdom by following these steps exactly: "
            f"- Identify 5-7 core topics discussed that offer lasting insights. "
            f"- For each topic, pull out exactly 2-3 key quotes or actionable pieces of advice that embody timeless wisdom. "
            f"- List any books, tools, or people mentioned as resources for further learning. "
            f"- Generate exactly 3-5 key questions the host was exploring to uncover deeper understanding. "
            f"Format the output as JSON with keys 'title', 'topics' (list of dicts with 'name' and 'quotes_advice' containing 2-3 items), 'resources' (list), and 'key_questions' (list of 3-5 items): {transcript_text}",
            generation_config={"max_output_tokens": 1500, "response_mime_type": "application/json"}
        )
        print(f"Debug: Gemini response received: {response.text[:100]}...")
        return response.text
    except Exception as e:
        print(f"Debug: Gemini API error: {str(e)}")
        return None

def save_to_history(video_id, summary):
    try:
        conn = sqlite3.connect('podcast_history.db')
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS summaries
                     (id INTEGER PRIMARY KEY, video_id TEXT, summary TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
        c.execute("INSERT INTO summaries (video_id, summary) VALUES (?, ?)", (video_id, json.dumps(summary)))
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"Error saving to history: {str(e)}")

def download_audio_from_youtube(youtube_url):
    try:
        ydl_opts = {
            'format': 'bestaudio/best',
            'outtmpl': 'downloads/%(title)s_%(id)s.%(ext)s',  # Unique filename with video_id
            'postprocessors': [{
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': '64',
            }],
            'quiet': True,  # Reduce output noise
        }
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            title = info.get('title', youtube_url.split('=')[-1].split('&')[0])
            video_id = info.get('id')
            summary_path = f"downloads/{video_id}_summary.txt"
            # Check cache with validation and format adjustment
            if os.path.exists(summary_path):
                print(f"Using cached summary for {video_id}")
                try:
                    with open(summary_path, "r", encoding="utf-8") as f:
                        cached_data = json.loads(f.read())
                        if not isinstance(cached_data, dict) or "message" not in cached_data:
                            cached_data = {"message": "Cached summary", "video_id": video_id}
                        return cached_data
                except (json.JSONDecodeError, Exception) as e:
                    print(f"Cached file {summary_path} is corrupt or invalid, reprocessing: {str(e)}")
            # Download and process
            ydl.download([youtube_url])
            file_path = [f for f in os.listdir("downloads") if f.endswith(".mp3") and video_id in f]
            if not file_path:
                raise Exception("Audio file not created after download")
            file_path = os.path.join("downloads", file_path[0])
            transcript_text = transcribe_audio(file_path)
            print(f"Transcription: {transcript_text[:100]}...")
            with open(f"downloads/{video_id}_transcript.txt", "w", encoding="utf-8") as f:
                f.write(transcript_text)
            summary = summarize_with_gemini(transcript_text, title)
            if summary:
                summary_data = json.loads(summary)
                with open(summary_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps({"message": f"Processed {youtube_url}", "video_id": video_id, **summary_data}, indent=2))
                print(f"Summarized to {summary_path}")
                save_to_history(video_id, summary_data)
                return {"message": f"Processed {youtube_url}", "video_id": video_id}
            else:
                raise Exception("Failed to generate summary")
    except Exception as e:
        print(f"Download error: {str(e)}")
        return {"message": f"Failed to process {youtube_url}", "error": str(e)}uvicorn backend.main:app --reload --host 0.0.0.0 --port 8000