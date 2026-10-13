from __future__ import annotations

import logging
import math
import struct
import wave
from pathlib import Path
from typing import List

from .base import BaseTTS, TTSChunk, TTSResult

logger = logging.getLogger(__name__)


class MockTTS(BaseTTS):
    def split_text(self, text: str, max_chars: int = 500) -> List[str]:
        if not text:
            return []
        # Simple sentence/paragraph aware splitting
        # Split on newlines first
        parts = []
        for para in text.split("\n\n"):
            para = para.strip()
            if not para:
                continue
            if len(para) <= max_chars:
                parts.append(para)
                continue
            # split by sentences
            # crude: . ? ! followed by space
            import re

            sentences = re.split(r"(?<=[.!?])\s+", para)
            current = ""
            for s in sentences:
                if len(current) + len(s) + 1 <= max_chars:
                    current = (current + " " + s).strip()
                else:
                    if current:
                        parts.append(current)
                    current = s
                if len(current) > max_chars:
                    # hard split
                    for i in range(0, len(current), max_chars):
                        parts.append(current[i : i + max_chars])
                    current = ""
            if current:
                parts.append(current)
        return parts

    def synthesize(self, text: str, output_dir: Path, voice: str = "af_heart", speed: float = 1.0) -> TTSResult:
        output_dir.mkdir(parents=True, exist_ok=True)
        chunks = self.split_text(text)
        results: List[TTSChunk] = []
        for i, chunk in enumerate(chunks, start=1):
            wav_path = output_dir / f"chunk_{i:04d}.wav"
            # generate a simple 1kHz tone of ~0.3s per 100 chars as mock
            duration = max(0.2, min(5.0, len(chunk) / 300.0 / max(0.1, speed)))
            self._write_sine_wav(wav_path, duration=duration, freq=1000)
            results.append(TTSChunk(text=chunk, audio_path=wav_path, index=i, duration_seconds=duration))
        return TTSResult(chunks=results)

    def _write_sine_wav(self, path: Path, duration: float = 0.5, freq: int = 440, sample_rate: int = 22050):
        n_samples = int(duration * sample_rate)
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(sample_rate)
            for i in range(n_samples):
                val = int(32767 * 0.3 * math.sin(2 * math.pi * freq * i / sample_rate))
                wf.writeframes(struct.pack("<h", val))
