from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)


class FFmpegError(RuntimeError):
    pass


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def ffprobe_available() -> bool:
    return shutil.which("ffprobe") is not None


def _run(cmd: Sequence[str]) -> subprocess.CompletedProcess:
    logger.debug("Running: %s", " ".join(cmd))
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise FFmpegError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\n{proc.stderr[-2000:]}"
        )
    return proc


def encode_mp3(
    input_path: Path,
    output_path: Path,
    bitrate: str = "192k",
    sample_rate: int = 24000,
    channels: int = 1,
) -> Path:
    """Encode a single audio file to MP3 with consistent parameters."""
    input_path = Path(input_path)
    output_path = Path(output_path)
    if not input_path.exists():
        raise FileNotFoundError(f"Input audio not found: {input_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    _run(
        [
            "ffmpeg",
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(input_path),
            "-ar",
            str(sample_rate),
            "-ac",
            str(channels),
            "-c:a",
            "libmp3lame",
            "-b:a",
            bitrate,
            str(output_path),
        ]
    )
    return output_path


def concat_audio(
    input_files: Sequence[Path],
    output_path: Path,
    bitrate: str = "192k",
    sample_rate: int = 24000,
    channels: int = 1,
    pause_ms: int = 0,
) -> Path:
    """Concatenate audio files in the given order using ffmpeg's concat demuxer.

    Re-encodes the result so mismatched inputs still join cleanly.  Never
    concatenates raw MP3 byte streams.
    """
    files = [Path(f) for f in input_files]
    if not files:
        raise ValueError("concat_audio requires at least one input file")
    missing = [str(f) for f in files if not f.exists()]
    if missing:
        raise FileNotFoundError(f"Missing audio inputs: {missing}")

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        list_file = Path(tmp) / "concat.txt"
        lines: List[str] = []
        silence: Optional[Path] = None
        if pause_ms > 0:
            silence = Path(tmp) / "silence.wav"
            _run(
                [
                    "ffmpeg",
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"anullsrc=r={sample_rate}:cl={'mono' if channels == 1 else 'stereo'}",
                    "-t",
                    f"{pause_ms / 1000.0:.3f}",
                    str(silence),
                ]
            )
        for i, f in enumerate(files):
            if i > 0 and silence is not None:
                lines.append(f"file '{silence.as_posix()}'")
            lines.append(f"file '{f.resolve().as_posix()}'")
        list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

        _run(
            [
                "ffmpeg",
                "-y",
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-ar",
                str(sample_rate),
                "-ac",
                str(channels),
                "-c:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                str(output_path),
            ]
        )
    return output_path


def probe_duration(path: Path) -> Optional[float]:
    path = Path(path)
    if not path.exists() or not ffprobe_available():
        return None
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "json",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        data = json.loads(proc.stdout)
        return float(data["format"]["duration"])
    except Exception:
        return None


def verify_audio(path: Path) -> bool:
    """Return True if the file exists, is non-empty and decodes as valid audio."""
    path = Path(path)
    if not path.exists() or path.stat().st_size == 0:
        return False
    if not ffprobe_available():
        return True
    return probe_duration(path) is not None
