# downloader.py (only Stage-2 changed; keep your Stage-1 CC flow)
from pathlib import Path
import os, json, re, tempfile
from yt_dlp import YoutubeDL
import assemblyai as aai

# ... keep your extract_video_id, summarize_text_to_json, _write_summary, etc ...

def _cookies_file_from_env():
    data = os.getenv("YTDLP_COOKIES")
    if not data:
        return None
    fp = tempfile.NamedTemporaryFile(delete=False, suffix=".txt")
    fp.write(data.encode("utf-8"))
    fp.flush(); fp.close()
    return fp.name

def _download_audio_to_tmp(youtube_url: str, cookies_path: str | None):
    """Return (local_path, video_id) or (None, None) on failure."""
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
        "extractor_args": {"youtube": {"player_client": ["web"]}},  # avoid android 403
        "postprocessors": [
            {"key": "FFmpegExtractAudio", "preferredcodec": "m4a", "preferredquality": "2"}
        ],
        "http_headers": {
            "User-Agent": "Mozilla/5.0"
        }
    }
    if cookies_path:
        ydl_opts["cookiefile"] = cookies_path

    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(youtube_url, download=True)
        vid = info.get("id")
        # file will be <tmpdir>/<id>.m4a after pp
        for ext in ("m4a", "mp3", "webm", "opus"):
            candidate = os.path.join(tmpdir, f"{vid}.{ext}")
            if os.path.exists(candidate):
                return candidate, vid
    return None, None

def _transcribe_with_aai(local_audio_path: str) -> str:
    """Upload local file and return transcript text or raise."""
    aai.settings.api_key = os.getenv("ASSEMBLYAI_API_KEY", "")
    if not aai.settings.api_key:
        raise RuntimeError("ASSEMBLYAI_API_KEY not set")

    transcriber = aai.Transcriber()
    # AssemblyAI Python SDK accepts local file path via 'audio' parameter
    transcript = transcriber.transcribe(audio=local_audio_path)

    if transcript.status != "completed" or not transcript.text:
        err = getattr(transcript, "error", "no text")
        raise RuntimeError(f"AssemblyAI failed: {err}")
    return transcript.text

def download_audio_from_youtube(youtube_url: str) -> dict:
    # ----- parse id -----
    video_id = extract_video_id(youtube_url)
    if not video_id:
        return {"error": "Invalid YouTube URL. Could not parse a video ID."}

    # ----- Seeded demos (keep) -----
    seed = Path(__file__).parent / "seed" / f"{video_id}.json"
    if seed.exists():
        with open(seed, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
        _write_summary(video_id, data)
        return {"message": "Processed via demo seed", "video_id": video_id}

    # ----- Stage 1: CC transcript (keep your existing robust CC logic) -----
    try:
        # ... your YouTubeTranscriptApi code here ...
        pass
    except Exception:
        pass  # fall through

    # ----- Stage 2: Download small audio -> upload file to AAI -----
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
