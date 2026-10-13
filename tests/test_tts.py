from __future__ import annotations

import numpy as np

from src.tts.kokoro_engine import KokoroTTS
from src.tts.mock import MockTTS


class StubKokoro(KokoroTTS):
    """Kokoro adapter with the model call replaced by a fake audio buffer."""

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.generate_calls = 0
        self.fail_on: set[str] = set()

    def _generate_with_retry(self, text, voice, speed):  # noqa: D102
        if text in self.fail_on:
            return None
        self.generate_calls += 1
        return np.zeros(2400, dtype=np.float32)  # 0.1s at 24kHz


def test_split_text_respects_limit():
    tts = KokoroTTS(max_chars=50)
    text = "First sentence. Second sentence. Third sentence that is quite long indeed."
    chunks = tts.split_text(text)
    assert chunks
    assert all(len(c) <= 50 or " " not in c for c in chunks)


def test_split_text_keeps_paragraphs_separate():
    tts = KokoroTTS(max_chars=500)
    chunks = tts.split_text("Para one.\n\nPara two.")
    assert len(chunks) == 2


def test_split_hard_wraps_oversized_sentence():
    tts = KokoroTTS(max_chars=20)
    chunks = tts.split_text("word " * 30)
    assert chunks and all(len(c) <= 20 for c in chunks)


def test_hard_split_preserves_all_words():
    pieces = KokoroTTS._hard_split("alpha beta gamma delta epsilon", 10)
    assert " ".join(pieces).split() == "alpha beta gamma delta epsilon".split()


def test_synthesize_writes_chunks_and_cache(tmp_path):
    tts = StubKokoro(max_chars=500)
    result = tts.synthesize("One sentence.\n\nTwo sentence.", tmp_path, voice="af_heart", speed=1.0)
    assert len(result.chunks) == 2
    assert all(c.audio_path.exists() for c in result.chunks)
    assert (tmp_path / "chunks_cache.json").exists()
    assert tts.generate_calls == 2


def test_cache_hit_avoids_regeneration(tmp_path):
    tts = StubKokoro(max_chars=500)
    tts.synthesize("Repeat me.", tmp_path, voice="af_heart", speed=1.0)
    first_calls = tts.generate_calls
    tts2 = StubKokoro(max_chars=500)
    result = tts2.synthesize("Repeat me.", tmp_path, voice="af_heart", speed=1.0)
    assert tts2.generate_calls == 0
    assert len(result.chunks) == 1
    assert first_calls == 1


def test_speed_change_invalidates_cache(tmp_path):
    tts = StubKokoro(max_chars=500)
    tts.synthesize("Repeat me.", tmp_path, voice="af_heart", speed=1.0)
    tts2 = StubKokoro(max_chars=500)
    tts2.synthesize("Repeat me.", tmp_path, voice="af_heart", speed=1.5)
    assert tts2.generate_calls == 1


def test_voice_change_invalidates_cache(tmp_path):
    tts = StubKokoro(max_chars=500)
    tts.synthesize("Repeat me.", tmp_path, voice="af_heart", speed=1.0)
    tts2 = StubKokoro(max_chars=500)
    tts2.synthesize("Repeat me.", tmp_path, voice="am_adam", speed=1.0)
    assert tts2.generate_calls == 1


def test_text_change_invalidates_cache(tmp_path):
    tts = StubKokoro(max_chars=500)
    tts.synthesize("Original text.", tmp_path, voice="af_heart", speed=1.0)
    tts2 = StubKokoro(max_chars=500)
    tts2.synthesize("Different text.", tmp_path, voice="af_heart", speed=1.0)
    assert tts2.generate_calls == 1


def test_failed_chunk_is_skipped_not_fatal(tmp_path):
    tts = StubKokoro(max_chars=500)
    tts.fail_on = {"Broken chunk."}
    result = tts.synthesize("Broken chunk.\n\nGood chunk.", tmp_path, voice="af_heart", speed=1.0)
    assert len(result.chunks) == 1
    assert result.chunks[0].text == "Good chunk."


def test_empty_text_produces_no_chunks(tmp_path):
    result = StubKokoro().synthesize("", tmp_path)
    assert result.chunks == []


def test_mock_tts_splits_and_writes(tmp_path):
    mock = MockTTS()
    result = mock.synthesize("Hello.\n\nWorld.", tmp_path)
    assert len(result.chunks) == 2
    assert all(p.audio_path.suffix == ".wav" for p in result.chunks)
