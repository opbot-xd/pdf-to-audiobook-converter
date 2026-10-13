from __future__ import annotations

import abc
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


@dataclass
class TTSChunk:
    text: str
    audio_path: Path
    index: int
    duration_seconds: Optional[float] = None


@dataclass
class TTSResult:
    chunks: List[TTSChunk]
    total_duration_seconds: Optional[float] = None


class BaseTTS(abc.ABC):
    @abc.abstractmethod
    def split_text(self, text: str, max_chars: int = 500) -> List[str]:
        raise NotImplementedError

    @abc.abstractmethod
    def synthesize(self, text: str, output_dir: Path, voice: str = "af_heart", speed: float = 1.0) -> TTSResult:
        raise NotImplementedError
