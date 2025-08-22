# backend/downloader.py
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import YouTubeTranscriptApi, TranscriptsDisabled, NoTranscriptFound
from pathlib import Path
import json

def extract_video_id(url: str) -> str:
    u = urlparse(url.strip())
    if u.netloc.endswith("youtu.be"):
        return u.path.strip("/")
    if "youtube.com" in u.netloc:
        q = parse_qs(u.query)
        if "v" in q: return q["v"][0]
    return u.path.strip("/")

def summarize_text_to_json(transcript_text: str) -> dict:
    # TODO: call Gemini/OpenAI here later; stub is fine for demo
    return {
        "title": "Podcast Pulse (Transcript Summary)",
        "topics": [{"name": "Key Ideas", "details": transcript_text[:800]}],
        "quotes": [],
        "advice": []
    }

def download_audio_from_youtube(youtube_url: str) -> dict:
    """Transcript-first flow: no audio download; avoids YouTube anti-bot in cloud."""
    try:
        vid = extract_video_id(youtube_url)
        if not vid:
            return {"error": "Invalid YouTube URL; could not parse video id."}

        # Try English first; add more languages if you want
        items = YouTubeTranscriptApi.get_transcript(vid, languages=["en"])
        text = " ".join([i["text"] for i in items if i["text"].strip()])

        summary = summarize_text_to_json(text)

        base = Path(__file__).parent.resolve()
        (base / "downloads").mkdir(exist_ok=True)
        out = base / "downloads" / f"{vid}_summary.txt"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary, f, ensure_ascii=False, indent=2)

        return {"message": "Processed via transcript", "video_id": vid}
    except (TranscriptsDisabled, NoTranscriptFound):
        return {"error": "Transcript not available for this video. Try a link with CC (captions)."}
    except Exception as e:
        return {"error": str(e)}
