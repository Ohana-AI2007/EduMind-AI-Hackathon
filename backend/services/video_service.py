"""Lecture video/audio -> timestamped transcript chunks (FFmpeg + OpenAI transcription)."""
import shutil
import subprocess
import tempfile
from pathlib import Path

from backend import llm
from backend.config import settings
from backend.errors import AIServiceError, ExtractionError


def group_transcript(pieces: list, size: int) -> list:
    groups: list = []
    cur = None
    for p in pieces:
        if cur and len(cur["text"]) + len(p["text"]) + 1 <= size:
            cur["text"] += " " + p["text"]
            if p["end"] is not None:
                cur["end_sec"] = p["end"]
        else:
            if cur:
                groups.append(cur)
            cur = {"text": p["text"], "start_sec": p["start"], "end_sec": p["end"]}
    if cur:
        groups.append(cur)
    return groups


def transcribe_video(path: Path, warns: list) -> list:
    """Returns [{'text','start_sec','end_sec'}]. Raises ExtractionError when nothing real could be produced."""
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise ExtractionError("FFmpeg was not found on PATH, so no audio or transcript could be extracted. "
                              "Install FFmpeg and re-process this document.")
    llm.require_configured()
    seg_len = max(60, settings.video_segment_seconds)
    with tempfile.TemporaryDirectory(prefix="edumind_") as tmp:
        cmd = [ffmpeg, "-y", "-i", str(path), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "libmp3lame", "-b:a", "32k",
               "-f", "segment", "-segment_time", str(seg_len), "-reset_timestamps", "1", str(Path(tmp) / "part_%04d.mp3")]
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=3600, check=False)
        except subprocess.TimeoutExpired:
            raise ExtractionError("FFmpeg timed out while extracting audio.")
        parts = sorted(Path(tmp).glob("part_*.mp3"))
        if proc.returncode != 0 or not parts:
            raise ExtractionError("FFmpeg could not extract an audio track (no audio stream, or the file is corrupt).")
        pieces = []
        for i, part in enumerate(parts):
            try:
                segs = llm.transcribe(str(part))
            except AIServiceError as exc:
                raise ExtractionError(f"Transcription failed on audio segment {i + 1}: {exc.message}")
            offset = i * seg_len
            for s in segs:
                nots = s.get("no_timestamps")
                pieces.append({"text": s["text"], "start": None if nots else s["start"] + offset,
                               "end": None if nots else s["end"] + offset})
    if not pieces:
        raise ExtractionError("The transcription returned no speech.")
    if any(p["start"] is None for p in pieces):
        warns.append("The transcription model returned no timestamps; citations for this file have no time location.")
    warns.append("Video timestamps are approximate (audio is split into fixed-length parts before transcription).")
    return group_transcript(pieces, settings.chunk_size)