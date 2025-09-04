# backend/downloader.py
from __future__ import annotations
from pathlib import Path
from urllib.parse import urlparse, parse_qs
import os, re, json, tempfile, shutil

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
    """Robust YouTube ID extractor."""
    if not url:
        return ""
    u = urlparse(url.strip())
    host = u.netloc.lower()

    # youtu.be/<id>
    if host.endswith("youtu.be"):
        seg = u.path.strip("/").split("/")[0]
        return seg

    # youtube.com/shorts/<id>
    if "youtube.com" in host and "/shorts/" in u.path:
        parts = [p for p in u.path.split("/") if p]
        if len(parts) >= 2 and parts[0].lower() == "shorts":
            return parts[1]

    # youtube.com/watch?v=<id>
    if "youtube.com" in host:
        q = parse_qs(u.query)
        if "v" in q and q["v"]:
            return q["v"][0]

    # last path segment fallback
    last = u.path.strip("/").split("/")[-1]
    if _YT_ID_RE.match(last):
        return last
    return ""

def _join(items) -> str:
    return " ".join([i["text"].strip() for i in items if i.get("text")])

def summarize_text_to_json(transcript_text: str) -> dict:
    # Minimal deterministic summary stub (replace later with LLM)
    snippet = transcript_text.replace("\n", " ")[:1200]
    return {
        "title": "Podcast Pulse — Auto Summary",
        "topics": [{"name": "Key Ideas", "details": snippet}],
        "quotes": [],
        "advice": [],
        "resources": [],
        "key_questions": [],
    }

def _write_summary(video_id: str, data: dict) -> str:
    base = Path(__file__).parent.resolve()
    downloads = base / "downloads"
    downloads.mkdir(exist_ok=True)
    out = downloads / f"{video_id}_summary.txt"
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    return str(out)

def _cookies_file_from_env() -> str | None:
    """
    Accept cookies via env var YTDLP_COOKIES (paste your cookies.txt content).
    We write it to a temp file for yt-dlp to read.
    """
    data = os.getenv("YTDLP_COOKIES")
    if not data:
        return None
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    fp.write(data.encode("utf-8"))
    fp.flush(); fp.close()
    return fp.name

# -------------------- Stage 2 helpers (audio download + AAI) --------------------

def _download_audio_to_tmp(youtube_url: str, cookies_path: str | None):
    """
    Download small audio file to a temp dir.
    Returns (local_audio_path, video_id) or (None, None) on failure.
    """
    tmpdir = tempfile.mkdtemp(prefix="pp_")
    outtpl = os.path.join(tmpdir, "%(id)s.%(ext)s")

    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "noprogress": True,
        "outtmpl": outtpl,
        "format": "bestaudio[ext=m4a]/bestaudio/best",
        "restrictfilenames": True,
        "noplaylist": True,
        # Avoid android client (may 403); use web
        "extractor_args": {"youtube": {"player_client": ["web"]}},
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "2"}
        ],
        "http_headers": {"User-Agent": "Mozilla/5.0"},
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    try:
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(youtube_url, download=True)
            vid = info.get("id")
            # file becomes <tmpdir>/<id>.m4a after postprocess
            for ext in ("m4a", "mp3", "webm", "opus"):
                candidate = os.path.join(tmpdir, f"{vid}.{ext}")
                if os.path.exists(candidate):
                    return candidate, vid
    except Exception:
        # cleanup tempdir when failing
        shutil.rmtree(tmpdir, ignore_errors=True)
        return None, None

    shutil.rmtree(tmpdir, ignore_errors=True)
    return None, None

def _transcribe_with_aai(local_audio_path: str) -> str:
    """Upload local file and return transcript text, or raise on error."""
    aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
    if not aai.settings.api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set")

    transcriber = aai.Transcriber()
    # SDK supports local file path via 'audio' parameter
    transcript = transcriber.transcribe(audio=local_audio_path)

    if transcript.status != "completed" or not getattr(transcript, "text", ""):
        err = getattr(transcript, "error", "no text")
        raise RuntimeError(f"AssemblyAI failed: {err}")
    return transcript.text

# -------------------- Main entry --------------------

def download_audio_from_youtube(youtube_url: str) -> dict:
    """
    Flow:
      1) Seed demo (if backend/seed/<id>.json exists)
      2) Try official/translated subtitles via youtube_transcript_api
      3) Fallback: download short audio locally and upload to AssemblyAI
    Saves JSON to downloads/{video_id}_summary.txt and returns {message, video_id}
    """
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # --- Seeded demos for stable demos/interviews ---
    seed = Path(__file__).parent / "seed" / f"{video_id}.json"
    if seed.exists():
        with open(seed, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _write_summary(video_id, data)
        return {"message": "Processed via demo seed", "video_id": video_id}

    # --- Stage 1: Try to get captions (CC). Translate if needed ---
    try:
        try:
            items = YouTubeTranscriptApi.get_transcript(
                video_id, languages=["en", "en-US", "en-GB"]
            )
        except (NoTranscriptFound, TranscriptsDisabled):
            transcripts = YouTubeTranscriptApi.list_transcripts(video_id)
            try:
                t = transcripts.find_transcript(["en", "en-US", "en-GB"])
                items = t.fetch()
            except Exception:
                # translate first available to English
                any_t = next(iter(transcripts))
                items = any_t.translate("en").fetch()

        text = _join(items)
        if text.strip():
            summary = summarize_text_to_json(text)
            _write_summary(video_id, summary)
            return {"message": "Processed via transcript", "video_id": video_id}
        else:
            # fall through to Stage 2
            pass
    except (CouldNotRetrieveTranscript, NoTranscriptFound, TranscriptsDisabled):
        # fall through to Stage 2
        pass
    except Exception:
        # parser/HTTP glitches → fall through
        pass

    # --- Stage 2: Download audio file locally → upload to AAI
    try:
        cookies = _cookies_file_from_env()
        local_path, vid = _download_audio_to_tmp(youtube_url, cookies)
        if not local_path:
            return {"error": "Could not download audio from YouTube (blocked). Add cookies or try another link."}

        text = _transcribe_with_aai(local_path)
        summary = summarize_text_to_json(text)
        _write_summary(video_id, summary)
        return {"message": "Processed via AssemblyAI (file upload)", "video_id": video_id}
    except Exception as e:
        return {"error": f"Audio fallback failed: {e}"}
