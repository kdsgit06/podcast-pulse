# backend/downloader.py
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript
)
from pathlib import Path
import json, re

# ---------- Helpers ----------

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

def extract_video_id(url: str) -> str:
    """
    Robust extraction:
      https://www.youtube.com/watch?v=ID
      https://youtu.be/ID?si=...
      https://www.youtube.com/shorts/ID?feature=share
    """
    u = urlparse(url.strip())
    host = u.netloc.lower()

    # youtu.be short links
    if host.endswith("youtu.be"):
        # path like "/ID"
        vid = u.path.strip("/").split("/")[0]
        return vid

    # full youtube
    if "youtube.com" in host:
        # shorts path
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "shorts":
            return parts[1]

        # normal watch?v=
        q = parse_qs(u.query)
        if "v" in q and q["v"]:
            return q["v"][0]

    # last fallback: last segment if it looks like an ID
    last = u.path.strip("/").split("/")[-1]
    if _YT_ID_RE.match(last):
        return last

    return ""

def summarize_text_to_json(transcript_text: str) -> dict:
    """
    TODO: plug in Gemini/OpenAI. Stub keeps portfolio demo working.
    """
    # Keep it short to avoid huge payloads
    snippet = transcript_text.replace("\n", " ")[:1200]
    return {
        "title": "Podcast Pulse (Transcript Summary)",
        "topics": [{"name": "Key Ideas", "details": snippet}],
        "quotes": [],
        "advice": []
    }

def _join(items):
    return " ".join([i["text"] for i in items if i["text"].strip()])

# ---------- Main entry called by FastAPI ----------

def download_audio_from_youtube(youtube_url: str) -> dict:
    """
    Transcript-first flow:
    - Try English transcripts
    - Else translate available transcript to English
    - Else use first available language (still returns JSON)
    Saves to downloads/{video_id}_summary.txt
    """
    try:
        video_id = extract_video_id(youtube_url)
        if not video_id:
            return {"error": "Invalid YouTube URL. Could not parse a video ID."}

        # Strategy 1: direct English (manually created or auto-generated)
        try:
            items = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
            transcript_text = _join(items)
        except (NoTranscriptFound, TranscriptsDisabled):
            # Strategy 2: list transcripts and try translate to English
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                t = transcripts.find_transcript(["en", "en-US", "en-GB"])
                items = t.fetch()
                transcript_text = _join(items)
            except Exception:
                try:
                    # pick any transcript and translate to English
                    t_any = next(iter(transcripts))
                    t_en = t_any.translate("en")
                    items = t_en.fetch()
                    transcript_text = _join(items)
                except Exception:
                    # Strategy 3: use first available language as-is
                    try:
                        t_any2 = next(iter(transcripts))
                        items = t_any2.fetch()
                        transcript_text = _join(items)
                    except Exception:
                        return {"error": "Transcript not available for this video (captions disabled). Try a link with CC."}

        if not transcript_text.strip():
            return {"error": "Transcript fetched but empty. Try another video with proper captions (CC)."}

        summary_json = summarize_text_to_json(transcript_text)

        base = Path(__file__).parent.resolve()
        downloads = base / "downloads"
        downloads.mkdir(exist_ok=True)
        out = downloads / f"{video_id}_summary.txt"
        with open(out, "w", encoding="utf-8") as f:
            json.dump(summary_json, f, ensure_ascii=False, indent=2)

        return {"message": "Processed via transcript", "video_id": video_id}

    except CouldNotRetrieveTranscript:
        return {"error": "Could not retrieve transcript (network or video restricted). Try another video with CC."}
    except TranscriptsDisabled:
        return {"error": "Captions are disabled for this video. Pick a link with CC."}
    except NoTranscriptFound:
        return {"error": "No transcript found. Use a video with captions (CC)."}
    except Exception as e:
        # Make errors readable to the UI instead of raw parser traces
        return {"error": f"Unexpected error while fetching transcript: {str(e)}"}
