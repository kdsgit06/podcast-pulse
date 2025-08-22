# backend/downloader.py
from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript
)
from pathlib import Path
import os, json, re, tempfile

# Optional libs (present in your requirements)
import assemblyai as aai
from yt_dlp import YoutubeDL

# ---------------- Helpers ----------------

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

def extract_video_id(url: str) -> str:
    u = urlparse(url.strip())
    host = u.netloc.lower()

    # youtu.be short links
    if host.endswith("youtu.be"):
        seg = u.path.strip("/").split("/")[0]
        return seg

    # shorts
    if "youtube.com" in host and "/shorts/" in u.path:
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "shorts":
            return parts[1]

    # watch?v=
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and q["v"]:
            return q["v"][0]

    last = u.path.strip("/").split("/")[-1]
    if _YT_ID_RE.match(last):
        return last
    return ""

def _join(items):
    return " ".join([i["text"] for i in items if i["text"].strip()])

def summarize_text_to_json(transcript_text: str) -> dict:
    # TODO: replace with Gemini/OpenAI. Keep stub for demo stability.
    snippet = transcript_text.replace("\n", " ")[:1200]
    return {
        "title": "Podcast Pulse — Auto Summary",
        "topics": [{"name": "Key Ideas", "details": snippet}],
        "quotes": [],
        "advice": []
    }

def _write_summary(video_id: str, data: dict) -> str:
    base = Path(__file__).parent.resolve()
    downloads = base / "downloads"
    downloads.mkdir(exist_ok=True)
    out = downloads / f"{video_id}_summary.txt"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(out)

def _cookies_file_from_env():
    data = os.getenv("YTDLP_COOKIES")
    if not data:
        return None
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    fp.write(data.encode("utf-8"))
    fp.flush(); fp.close()
    return fp.name

# ---------------- Main entry ----------------

def download_audio_from_youtube(youtube_url: str) -> dict:
    """
    Robust flow:
      1) Try transcript API (handles CC videos, multiple langs & translate).
      2) If that fails, use yt-dlp (no download) to get an audio URL and
         send it to AssemblyAI via remote_url -> fetch transcript -> summarize.
         Uses cookies if provided via env var YTDLP_COOKIES.
    Saves summary JSON to downloads/{video_id}_summary.txt
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # ----- Stage 1: YouTube transcripts (prefer CC) -----
    try:
        try:
            items = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        except (NoTranscriptFound, TranscriptsDisabled):
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            # try direct English
            try:
                t = transcripts.find_transcript(["en", "en-US", "en-GB"])
                items = t.fetch()
            except Exception:
                # try translate any to English
                t_any = next(iter(transcripts))
                t_en = t_any.translate("en")
                items = t_en.fetch()
        text = _join(items)
        if text.strip():
            summary = summarize_text_to_json(text)
            _write_summary(video_id, summary)
            return {"message": "Processed via transcript", "video_id": video_id}
    except (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled):
        pass
    except Exception:
        # swallow parser glitches and fall through to Stage 2
        pass

    # ----- Stage 2: yt-dlp (no download) + AssemblyAI -----
    # Requirements: env ASSEMBLYAI_API_KEY set; cookies optional but recommended.
    aai_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not aai_key:
        return {"error": "Transcript failed and ASSEMBLYAI_API_KEY is not set on server."}

    cookies = _cookies_file_from_env()
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "format": "bestaudio/best",
        "noplaylist": True,
        # more friendly client to avoid some blocks
        "extractor_args": {"youtube": {"player_client": ["android"]}},
    }
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)
            # pick an audio format URL
            url = None
            if "url" in info:
                url = info["url"]
            else:
                for f in info.get("formats", []):
                    if f.get("acodec") and f.get("acodec") != "none" and f.get("url"):
                        url = f["url"]; break
            if not url:
                return {"error": "Could not get audio URL from YouTube. Try another video."}

        aai.settings.api_key = aai_key
        transcript = aai.Transcript.create(audio_url=url)
        transcript = aai.Transcript.get(transcript.id, polling=True)

        if transcript.status != "completed" or not transcript.text:
            return {"error": f"AssemblyAI failed: {transcript.error or 'no text'}"}

        summary = summarize_text_to_json(transcript.text)
        _write_summary(video_id, summary)
        return {"message": "Processed via AssemblyAI (audio URL)", "video_id": video_id}

    except Exception as e:
        return {"error": f"Fallback failed: {str(e)}"}
