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

# Optional libs (present in requirements.txt)
import assemblyai as aai
from yt_dlp import YoutubeDL

# ---------------- Helpers ----------------

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

def extract_video_id(url: str) -> str:
    """
    Supports:
      https://www.youtube.com/watch?v=ID
      https://youtu.be/ID?si=...
      https://www.youtube.com/shorts/ID?feature=share
    """
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

    # fallback: last path segment if it looks like an ID
    last = u.path.strip("/").split("/")[-1]
    if _YT_ID_RE.match(last):
        return last
    return ""

def _join(items):
    return " ".join([i["text"] for i in items if i["text"].strip()])

def summarize_text_to_json(transcript_text: str) -> dict:
    """
    TODO: plug Gemini/OpenAI. Stub keeps demo stable.
    """
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
      1) Try YouTube transcripts (multi-language + translate).
      2) Fallback: yt-dlp (no download) -> get audio URL -> AssemblyAI transcribe.
         Uses cookies if provided via env var YTDLP_COOKIES.
    Saves summary JSON to downloads/{video_id}_summary.txt
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # ----- Stage 1: YouTube transcripts (prefer CC) -----
try:
    transcripts = YouTubeTranscriptApi.list_transcripts(video_id)

    # Try direct English first
    try:
        t = transcripts.find_transcript(["en", "en-US", "en-GB"])
        items = t.fetch()
    except Exception:
        # Fallback: take first transcript and translate to English if possible
        t_any = next(iter(transcripts))
        try:
            items = t_any.translate("en").fetch()
        except Exception:
            items = t_any.fetch()

    text = _join(items)
    if text.strip():
        summary = summarize_text_to_json(text)
        _write_summary(video_id, summary)
        return {"message": "Processed via transcript", "video_id": video_id}
    else:
        langs = []
        for t in transcripts:
            try: langs.append(getattr(t, "language_code", "?"))
            except Exception: pass
        return {"error": f"No usable transcript text. Available languages: {', '.join(langs) or 'unknown'}"}
except (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled) as e:
    return {"error": f"Transcript not accessible for this video ({type(e).__name__}). Try a different link with CC."}
except Exception:
    pass  # fall through to Stage-2 if enabled



    # ----- Stage 2: yt-dlp (no download) + AssemblyAI (correct SDK) -----
        # ----- Stage 2: Best-effort (yt-dlp metadata -> AssemblyAI) -----
    # Feature flag: disable by default for a stable demo
    if os.getenv("ENABLE_AAI_FALLBACK", "false").lower() != "true":
        return {"error": "This video has no captions. Please use a link with CC (captions)."}

    aai_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not aai_key:
        return {"error": "Transcript failed and ASSEMBLYAI_API_KEY is not set on server."}

    cookies = _cookies_file_from_env()
    ydl_opts = {
        "quiet": True,
        "skip_download": True,
        "noplaylist": True,
        # do NOT force a specific format; we'll scan formats and pick one
    }
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        # 1) Get metadata WITHOUT downloading
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=False)

        # 1b) Pick a viable audio URL from the available formats
        def pick_audio_url(info: dict):
            formats = info.get("formats") or []
            candidates = []

            for f in formats:
                url = f.get("url")
                acodec = f.get("acodec")
                if url and acodec and acodec != "none":
                    # prefer higher bitrate audio
                    candidates.append({
                        "url": url,
                        "abr": f.get("abr") or 0,
                        "proto": (f.get("protocol") or "").lower()
                    })

            # if nothing found yet, accept HLS/m3u8 streams (AAI can fetch)
            if not candidates:
                for f in formats:
                    url = f.get("url")
                    proto = (f.get("protocol") or "").lower()
                    if url and ("m3u8" in proto or "http" in proto):
                        candidates.append({"url": url, "abr": f.get("abr") or 0, "proto": proto})

            if candidates:
                candidates.sort(key=lambda x: x["abr"], reverse=True)
                return candidates[0]["url"]

            # last chance: some extractors put a direct url at top-level
            return info.get("url")

        audio_url = pick_audio_url(info)
        if not audio_url:
            return {"error": "Could not obtain an audio URL from YouTube (blocked or images-only). Try another video or refresh cookies."}

        # 2) Ask AssemblyAI to fetch & transcribe that remote audio URL
        aai.settings.api_key = aai_key
        transcriber = aai.Transcriber()
        transcript = transcriber.transcribe(audio_url=audio_url)

        if transcript.status != "completed" or not getattr(transcript, "text", ""):
            return {"error": f"AssemblyAI failed: {getattr(transcript, 'error', 'no text')}"}

        summary = summarize_text_to_json(transcript.text)
        _write_summary(video_id, summary)
        return {"message": "Processed via AssemblyAI (audio URL)", "video_id": video_id}

    except Exception as e:
        return {"error": f"Fallback failed: {str(e)}"}
