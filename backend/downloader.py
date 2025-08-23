from urllib.parse import urlparse, parse_qs
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript,
)
from pathlib import Path
import os, json, re, tempfile

# Optional libs (installed)
import assemblyai as aai
from yt_dlp import YoutubeDL

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

def extract_video_id(url: str) -> str:
    u = urlparse(url.strip()); host = u.netloc.lower()
    if host.endswith("youtu.be"):
        return u.path.strip("/").split("/")[0]
    if "youtube.com" in host and "/shorts/" in u.path:
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0] == "shorts":
            return parts[1]
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and q["v"]:
            return q["v"][0]
    last = u.path.strip("/").split("/")[-1]
    return last if _YT_ID_RE.match(last) else ""

def _join(items): 
    return " ".join([i["text"] for i in items if i["text"].strip()])

def summarize_text_to_json(text: str) -> dict:
    snippet = text.replace("\n", " ")[:1200]
    return {
        "title": "Podcast Pulse — Transcript Summary",
        "topics": [{"name": "Key Ideas", "details": snippet}],
        "quotes": [],
        "advice": [],
    }

def _write_summary(video_id: str, data: dict) -> str:
    base = Path(__file__).parent.resolve()
    (base / "downloads").mkdir(exist_ok=True)
    out = base / "downloads" / f"{video_id}_summary.txt"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(out)

def _cookies_file_from_env():
    data = os.getenv("YTDLP_COOKIES")
    if not data:
        return None
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    fp.write(data.encode("utf-8")); fp.flush(); fp.close()
    return fp.name

def _pick_audio_url(info: dict):
    fmts = info.get("formats") or []
    candidates = []
    for f in fmts:
        url = f.get("url"); ac = f.get("acodec")
        if url and ac and ac != "none":
            candidates.append({"url": url, "abr": f.get("abr") or 0})
    if not candidates:
        for f in fmts:
            url = f.get("url"); proto = (f.get("protocol") or "").lower()
            if url and ("m3u8" in proto or "http" in proto):
                candidates.append({"url": url, "abr": f.get("abr") or 0})
    if candidates:
        candidates.sort(key=lambda x: x["abr"], reverse=True)
        return candidates[0]["url"]
    return info.get("url")

def download_audio_from_youtube(youtube_url: str) -> dict:
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # ----- Stage 1: robust transcript fetch -----
       # ----- Stage 1: YouTube transcripts (prefer CC) -----
    try:
        transcripts = YouTubeTranscriptApi.list_transcripts(video_id)

        # Try English first (manual or auto)
        try:
            t = transcripts.find_transcript(["en", "en-US", "en-GB"])
            items = t.fetch()
        except Exception:
            # If no English, take first and translate to English if possible
            t_any = next(iter(transcripts))
            try:
                items = t_any.translate("en").fetch()
            except Exception:
                items = t_any.fetch()

        text = _join(items)
        if text.strip():
            _write_summary(video_id, summarize_text_to_json(text))
            return {"message": "Processed via transcript", "video_id": video_id}
        else:
            langs = []
            for t in transcripts:
                try:
                    langs.append(getattr(t, "language_code", "?"))
                except Exception:
                    pass
            return {"error": f"No usable transcript text. Available languages: {', '.join(langs) or 'unknown'}"}

    except (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled) as e:
        # If fallback disabled, tell the truth clearly and STOP here
        if os.getenv("ENABLE_AAI_FALLBACK", "false").lower() != "true":
            return {"error": f"Transcript not accessible for this video ({type(e).__name__}). Use a link with CC."}
        # else fall through to Stage‑2
    except Exception as e:
        # Unknown parsing issue; if fallback disabled, report it and STOP
        if os.getenv("ENABLE_AAI_FALLBACK", "false").lower() != "true":
            return {"error": f"Transcript step failed unexpectedly: {str(e)}"}
        # else fall through to Stage‑2


    # ----- Stage 2: feature-flagged fallback (yt-dlp -> AAI) -----
    if os.getenv("ENABLE_AAI_FALLBACK", "false").lower() != "true":
        return {"error": "This video has no captions. Please use a link with CC (captions)."}

    aai_key = os.getenv("ASSEMBLYAI_API_KEY")
    if not aai_key:
        return {"error": "AAI fallback disabled: ASSEMBLYAI_API_KEY not set."}

    cookies = _cookies_file_from_env()
    ydl_opts = {"quiet": True, "skip_download": True, "noplaylist": True}
    if cookies:
        ydl_opts["cookiefile"] = cookies

    try:
        audio_url = None
        for client in (None, "web", "android", "ios"):
            opts = dict(ydl_opts)
            if client:
                opts["extractor_args"] = {"youtube": {"player_client": [client]}}
            with YoutubeDL(opts) as ydl:
                info = ydl.extract_info(youtube_url, download=False)
            audio_url = _pick_audio_url(info)
            if audio_url:
                break

        if not audio_url:
            return {"error": "Could not obtain an audio stream from YouTube (blocked). Use a video with CC."}

        aai.settings.api_key = aai_key
        transcript = aai.Transcriber().transcribe(audio_url=audio_url)
        if transcript.status != "completed" or not getattr(transcript, "text", ""):
            return {"error": f"AssemblyAI failed: {getattr(transcript, 'error', 'no text')}"}

        _write_summary(video_id, summarize_text_to_json(transcript.text))
        return {"message": "Processed via AssemblyAI (audio URL)", "video_id": video_id}

    except Exception:
        return {"error": "YouTube blocked audio on this link. Use a video with CC; audio fallback is best-effort."}
