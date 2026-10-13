from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import BaseTTS, TTSChunk, TTSResult
from ..utils.files import compute_text_hash

logger = logging.getLogger(__name__)

KOKORO_SAMPLE_RATE = 24000
DEFAULT_MAX_CHARS = 450  # conservative; Kokoro handles short contexts best


class KokoroUnavailableError(RuntimeError):
    """Raised when the kokoro package or model weights are not available."""


def kokoro_available() -> bool:
    try:
        import kokoro  # noqa: F401
        return True
    except Exception:
        return False


class KokoroTTS(BaseTTS):
    """Kokoro-82M backend.

    The heavy ``kokoro`` import and model load happen lazily on the first
    synthesis call so the rest of the pipeline (and the test suite) can run
    without torch or the model weights installed.
    """

    def __init__(
        self,
        lang_code: str = "a",
        model_path: Optional[str] = None,
        device: Optional[str] = None,
        max_chars: int = DEFAULT_MAX_CHARS,
    ) -> None:
        self.lang_code = lang_code
        self.model_path = model_path
        self.device = device
        self.max_chars = max_chars
        self._pipeline: Any = None
        self._voice_cache: Dict[str, Any] = {}

    # -- pipeline ----------------------------------------------------------

    def _ensure_pipeline(self) -> Any:
        if self._pipeline is not None:
            return self._pipeline
        try:
            from kokoro import KPipeline
        except Exception as e:  # pragma: no cover - depends on env
            raise KokoroUnavailableError(
                "The 'kokoro' package is not installed. Install it with "
                "`pip install kokoro` (see docs/INSTALL.md)."
            ) from e

        kwargs: Dict[str, Any] = {"lang_code": self.lang_code}
        if self.model_path:
            kwargs["model"] = self.model_path
        if self.device:
            kwargs["device"] = self.device
        try:
            self._pipeline = KPipeline(**kwargs)
        except TypeError:
            # Older/newer signatures may not accept device/model.
            self._pipeline = KPipeline(lang_code=self.lang_code)
        return self._pipeline

    # -- chunking ----------------------------------------------------------

    def split_text(self, text: str, max_chars: Optional[int] = None) -> List[str]:
        """Split into sentence/paragraph-bounded chunks under ``max_chars``."""
        limit = max_chars or self.max_chars
        if not text or not text.strip():
            return []

        chunks: List[str] = []
        for para in re.split(r"\n\s*\n", text):
            para = para.strip()
            if not para:
                continue
            if len(para) <= limit:
                chunks.append(para)
                continue
            chunks.extend(self._split_long_paragraph(para, limit))
        return [c for c in chunks if c.strip()]

    def _split_long_paragraph(self, para: str, limit: int) -> List[str]:
        sentences = re.split(r"(?<=[.!?])[\"')\]]?\s+", para)
        out: List[str] = []
        current = ""
        for sentence in sentences:
            if not sentence:
                continue
            if len(sentence) > limit:
                # flush, then hard-split the oversized sentence on commas/words
                if current:
                    out.append(current.strip())
                    current = ""
                out.extend(self._hard_split(sentence, limit))
                continue
            candidate = f"{current} {sentence}".strip() if current else sentence
            if len(candidate) <= limit:
                current = candidate
            else:
                out.append(current.strip())
                current = sentence
        if current.strip():
            out.append(current.strip())
        return out

    @staticmethod
    def _hard_split(sentence: str, limit: int) -> List[str]:
        pieces: List[str] = []
        remaining = sentence.strip()
        while len(remaining) > limit:
            window = remaining[:limit]
            cut = max(window.rfind(", "), window.rfind("; "), window.rfind(" "))
            if cut <= 0:
                cut = limit
            pieces.append(remaining[:cut].strip())
            remaining = remaining[cut:].strip()
        if remaining:
            pieces.append(remaining)
        return [p for p in pieces if p]

    # -- synthesis ---------------------------------------------------------

    def _load_voice(self, voice: str) -> Any:
        """Resolve a voice id. Kokoro accepts the id string directly (e.g. 'af_heart').

        The result is memoised so repeated chunks do not re-resolve it.
        """
        if voice not in self._voice_cache:
            if not voice or not isinstance(voice, str):
                raise ValueError(f"invalid Kokoro voice id: {voice!r}")
            self._voice_cache[voice] = voice
        return self._voice_cache[voice]

    def synthesize(
        self,
        text: str,
        output_dir: Path,
        voice: str = "af_heart",
        speed: float = 1.0,
        sample_rate: int = KOKORO_SAMPLE_RATE,
    ) -> TTSResult:
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        chunks = self.split_text(text)
        cache = self._load_cache(output_dir)

        results: List[TTSChunk] = []
        total = 0.0
        for i, chunk_text in enumerate(chunks, start=1):
            text_hash = compute_text_hash(chunk_text)
            key = f"chunk_{i:04d}"
            wav_path = output_dir / f"{key}.wav"

            entry = cache.get(key)
            if entry and wav_path.exists() and self._cache_hit(entry, text_hash, voice, speed):
                results.append(TTSChunk(chunk_text, wav_path, i, entry.get("duration_seconds")))
                total += entry.get("duration_seconds") or 0.0
                logger.debug("Reusing cached chunk %s", key)
                continue

            audio = self._generate_with_retry(chunk_text, voice, speed)
            if audio is None:
                logger.error("Failed to synthesize chunk %s; skipping", key)
                continue

            duration = self._write_wav(wav_path, audio, sample_rate)
            cache[key] = {
                "text_hash": text_hash,
                "voice": voice,
                "speed": speed,
                "duration_seconds": duration,
                "file": wav_path.name,
            }
            self._save_cache(output_dir, cache)
            results.append(TTSChunk(chunk_text, wav_path, i, duration))
            total += duration

        return TTSResult(chunks=results, total_duration_seconds=round(total, 3))

    # -- internals ---------------------------------------------------------

    def _generate_with_retry(self, text: str, voice: str, speed: float) -> Optional[Any]:
        """Generate one chunk, recovering from CUDA OOM by falling back to CPU."""
        pipeline = self._ensure_pipeline()
        self._load_voice(voice)

        try:
            return self._run_pipeline(pipeline, text, voice, speed)
        except RuntimeError as e:  # pragma: no cover - hardware dependent
            if "out of memory" in str(e).lower():
                logger.warning("CUDA OOM while synthesizing; clearing cache and retrying on CPU")
                try:
                    import torch

                    if torch.cuda.is_available():
                        torch.cuda.empty_cache()
                except Exception:
                    pass
                try:
                    self._pipeline = None
                    self.device = "cpu"
                    pipeline = self._ensure_pipeline()
                    return self._run_pipeline(pipeline, text, voice, speed)
                except Exception as e2:
                    logger.error("CPU retry failed: %s", e2)
                    return None
            logger.error("TTS runtime error: %s", e)
            return None

    def _run_pipeline(self, pipeline: Any, text: str, voice: str, speed: float) -> Any:
        import numpy as np

        pieces: List[Any] = []
        generator = pipeline(text, voice=voice, speed=speed, split_pattern=r"\n+")
        for _, _, audio in generator:
            if audio is None:
                continue
            if hasattr(audio, "detach"):  # torch tensor
                audio = audio.detach().cpu().numpy()
            pieces.append(np.asarray(audio))
        if not pieces:
            return None
        return np.concatenate(pieces)

    @staticmethod
    def _write_wav(path: Path, audio: Any, sample_rate: int) -> float:
        import soundfile as sf

        path.parent.mkdir(parents=True, exist_ok=True)
        sf.write(str(path), audio, sample_rate)
        duration = float(len(audio)) / float(sample_rate)
        return round(duration, 3)

    def _cache_path(self, output_dir: Path) -> Path:
        return output_dir / "chunks_cache.json"

    def _load_cache(self, output_dir: Path) -> Dict[str, Any]:
        p = self._cache_path(output_dir)
        if p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except Exception as e:
                logger.warning("Could not read chunk cache %s: %s", p, e)
        return {}

    def _save_cache(self, output_dir: Path, cache: Dict[str, Any]) -> None:
        self._cache_path(output_dir).write_text(json.dumps(cache, indent=2), encoding="utf-8")

    @staticmethod
    def _cache_hit(entry: Dict[str, Any], text_hash: str, voice: str, speed: float) -> bool:
        return (
            entry.get("text_hash") == text_hash
            and entry.get("voice") == voice
            and float(entry.get("speed", -1)) == float(speed)
        )
