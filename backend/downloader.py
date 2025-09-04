# backend/downloader.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import os, re, json, tempfile, shutil, base64

# 3rd-party
from youtube_transcript_api import (
    YouTubeTranscriptApi,
    TranscriptsDisabled,
    NoTranscriptFound,
    CouldNotRetrieveTranscript,
)
from yt_dlp import YoutubeDL
import assemblyai as aai

# -------------------- Helpers --------------------

_YT_ID_RE = re.compile(r"^[A-Za-z0-9_-]{6,}$")

def extract_video_id(url: str) -> str:
    if not url:
        return ""
    u = urlparse(url.strip())
    host = u.netloc.lower()
    if host.endswith("youtu.be"):
        seg = u.path.strip("/").split("/")[0]
        return seg
    if "youtube.com" in host and "/shorts/" in u.path:
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "shorts":
            return parts[1]
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and q["v"]:
            return q["v"][0]
    last = u.path.strip("/").split("/")[-1]
    if _YT_ID_RE.match(last):
        return last
    return ""

def _join(items) -> str:
    return " ".join([i.get("text", "").strip() for i in items if i.get("text")])

def summarize_text_to_json(transcript_text: str) -> dict:
    snippet = transcript_text.replace("\n", " ")[:1200]
    return {
        "title": "Podcast Pulse — Auto Summary",
        "topics": [{"name": "Key Ideas", "details": snippet}],
        "quotes": [],
        "advice": [],
        "resources": [],
        "questions": [],
    }

def _write_summary(video_id: str, data: dict) -> str:
    base = Path(__file__).parent.resolve()
    downloads = base / "downloads"
    downloads.mkdir(exist_ok=True)
    out = downloads / f"{video_id}_summary.txt"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(out)

# ---- cookies: prefer base64 to avoid multiline env issues ----
def _cookies_file_from_env() -> str | None:
    """
    Use YTDLP_COOKIES_B64 (base64 Netscape cookies.txt) if present,
    else YTDLP_COOKIES (raw single-line). Returns path to temp file or None.
    """
    b64 = os.getenv("YTDLP_COOKIES_B64", "").strip()
    raw = os.getenv("YTDLP_COOKIES", "").strip()
    if not b64 and not raw:
        return None
    try:
        data = base64.b64decode(b64).decode("utf-8") if b64 else raw
    except Exception:
        data = raw
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    fp.write(data.encode("utf-8")); fp.flush(); fp.close()
    return fp.name

# -------------------- Stage 2: audio download (no ffmpeg) + AAI --------------------

def _download_audio_to_tmp(youtube_url: str, cookies_path: str | None):
    """
    Download bestaudio (webm/opus/m4a/etc.) to temp dir.
    Return (local_path, video_id) or (None, None).
    """
    tmpdir = tempfile.mkdtemp(prefix="pp_")
    outtpl = os.path.join(tmpdir, "%(id)s.%(ext)s")
    ydl_opts = {
        "quiet": True, "no_warnings": True, "noprogress": True,
        "outtmpl": outtpl, "noplaylist": True,
        "format": "bestaudio/best",
        "restrictfilenames": True,
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            vid = info.get("id")
            # pick the downloaded file by id.* in tmpdir
            for name in os.listdir(tmpdir):
                if name.startswith(f"{vid}."):
                    return os.path.join(tmpdir, name), vid
    except Exception:
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, None

    shutil.rmtree(tmpdir, ignore_errors=True)
    return None, None

def _transcribe_with_aai(local_audio_path: str) -> str:
    aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
    if not aai.settings.api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set")
    transcriber = aai.Transcriber()
    transcript = transcriber.transcribe(audio=local_audio_path)  # local file path
    if getattr(transcript, "status", "") != "completed" or not getattr(transcript, "text", ""):
        err = getattr(transcript, "error", "no text")
        raise RuntimeError(f"AssemblyAI failed: {err}")
    return transcript.text

# -------------------- Main entry --------------------

def download_audio_from_youtube(youtube_url: str) -> dict:
    """
    1) Seed (backend/seed/<id>.json) → write & return
    2) CC via youtube_transcript_api (incl. translate) → summarize
    3) Fallback: yt-dlp bestaudio (with cookies) → upload file to AAI → summarize
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # Seed
    seed = Path(__file__).parent / "seed" / f"{video_id}.json"
    if seed.exists():
        with open(seed, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _write_summary(video_id, data)
        return {"message": "Processed via demo seed", "video_id": video_id}

    # Stage 1: CC / translate
    try:
        try:
            items = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        except (NoTranscriptFound, TranscriptsDisabled):
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                t = transcripts.find_transcript(["en", "en-US", "en-GB"])
                items = t.fetch()
            except Exception:
                any_t = next(iter(transcripts))
                items = any_t.translate("en").fetch()
        text = _join(items)
        if text.strip():
            summary = summarize_text_to_json(text)
            _write_summary(video_id, summary)
            return {"message": "Processed via transcript", "video_id": video_id}
    except (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled):
        pass
    except Exception:
        pass

    # Stage 2: download file + AAI
    try:
        cookies = _cookies_file_from_env()
        local_path, _ = _download_audio_to_tmp(youtube_url, cookies)
        if not local_path:
            return {"error": "Could not download audio from YouTube (blocked). Add cookies or try another link."}
        text = _transcribe_with_aai(local_path)
        summary = summarize_text_to_json(text)
        _write_summary(video_id, summary)
        return {"message": "Processed via AssemblyAI (file upload)", "video_id": video_id}
    except Exception as e:
        return {"error": f"Audio fallback failed: {e}"}
