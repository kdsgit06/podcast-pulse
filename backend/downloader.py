import yt_dlp
import sys
import assemblyai as aai
import nltk
import sqlite3
nltk.data.path.append(r"C:\Users\DELL\nltk_data")
import google.generativeai as genai
from dotenv import load_dotenv
import os
import json

print("Using Python:", sys.executable)

# Explicitly load .env from the backend directory
load_dotenv(dotenv_path=os.path.join(os.path.dirname(__file__), '.env'))
api_key = os.getenv("GOOGLE_API_KEY")
if not api_key:
    print("Error: GOOGLE_API_KEY not found in .env file")
    sys.exit(1)
genai.configure(api_key=api_key)

# Set your AssemblyAI API key
aai.settings.api_key = "6da0232e68c1446cb3b4228212bd0e95"

def summarize_with_gemini(transcript_text):
    try:
        print(f"Debug: Summarizing transcript of length {len(transcript_text)} characters")
        model = genai.GenerativeModel('gemini-1.5-pro')
        response = model.generate_content(
            f"You are a podcast analysis expert. Extract 5-7 core topics, 2-3 actionable advice points, and 2-3 key quotes from this transcript. Format the output as JSON with keys 'topics', 'advice', and 'quotes': {transcript_text}",
            generation_config={"max_output_tokens": 500, "response_mime_type": "application/json"}
        )
        print(f"Debug: Gemini response received: {response.text[:100]}...")
        return response.text
    except Exception as e:
        print(f"Debug: Gemini API error: {str(e)}")
        return None

def save_to_history(video_id, summary):
    conn = sqlite3.connect('podcast_history.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS summaries
                 (id INTEGER PRIMARY KEY, video_id TEXT, summary TEXT, timestamp DATETIME DEFAULT CURRENT_TIMESTAMP)''')
    c.execute("INSERT INTO summaries (video_id, summary) VALUES (?, ?)", (video_id, json.dumps(summary)))
    conn.commit()
    conn.close()

def download_audio_from_youtube(youtube_url):
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': 'downloads/%(title)s.%(ext)s',
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([youtube_url])
    print(f"Downloaded audio from {youtube_url}")

    # Transcribe the MP3
    file_path = ydl.prepare_filename(ydl.extract_info(youtube_url, download=False)).replace('.webm', '.mp3')
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(file_path)
    if transcript.status == aai.TranscriptStatus.completed:
        print(f"Transcription: {transcript.text[:100]}...")  # Show first 100 chars
        with open(f"downloads/{youtube_url.split('=')[-1]}_transcript.txt", "w", encoding="utf-8") as f:
            f.write(transcript.text)

        # Summarize with Gemini
        summary = summarize_with_gemini(transcript.text)
        if summary:
            summary_data = json.loads(summary)
            with open(f"downloads/{youtube_url.split('=')[-1]}_summary.txt", "w", encoding="utf-8") as f:
                f.write(json.dumps(summary_data, indent=2))  # Pretty-print JSON
            print(f"Summarized to downloads/{youtube_url.split('=')[-1]}_summary.txt")
            save_to_history(youtube_url.split('=')[-1], summary_data)
        else:
            print("Failed to generate summary")
    else:
        print(f"Transcription failed: {transcript.status}")

if __name__ == "__main__":
    test_url = "https://www.youtube.com/watch?v=4qykb6jKXdo"
    download_audio_from_youtube(test_url)