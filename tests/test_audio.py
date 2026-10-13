from __future__ import annotations

import wave

import pytest

from src.audio import ffmpeg as ff
from src.tts.mock import MockTTS

pytestmark = pytest.mark.skipif(not ff.ffmpeg_available(), reason="ffmpeg not installed")


def _wav(path, seconds: float, freq: int = 440):
    import math
    import struct

    sr = 24000
    n = int(seconds * sr)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(b"".join(struct.pack("<h", int(3000 * math.sin(2 * math.pi * freq * i / sr))) for i in range(n)))
    return path


def test_encode_mp3_produces_playable_file(tmp_path):
    wav = _wav(tmp_path / "a.wav", 0.5)
    mp3 = ff.encode_mp3(wav, tmp_path / "a.mp3")
    assert mp3.exists() and mp3.stat().st_size > 0
    assert ff.verify_audio(mp3)


def test_concat_preserves_order_and_total_duration(tmp_path):
    a = _wav(tmp_path / "a.wav", 0.5, 440)
    b = _wav(tmp_path / "b.wav", 0.7, 660)
    out = ff.concat_audio([a, b], tmp_path / "out.mp3")
    assert ff.verify_audio(out)
    dur = ff.probe_duration(out)
    assert dur is not None
    # ~1.2s of audio (allow encoder padding)
    assert 1.0 < dur < 1.6


def test_concat_missing_input_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        ff.concat_audio([tmp_path / "nope.wav"], tmp_path / "out.mp3")


def test_concat_empty_raises(tmp_path):
    with pytest.raises(ValueError):
        ff.concat_audio([], tmp_path / "out.mp3")


def test_inter_section_pause_added(tmp_path):
    a = _wav(tmp_path / "a.wav", 0.3)
    b = _wav(tmp_path / "b.wav", 0.3)
    no_pause = ff.concat_audio([a, b], tmp_path / "np.mp3")
    with_pause = ff.concat_audio([a, b], tmp_path / "wp.mp3", pause_ms=500)
    assert ff.probe_duration(with_pause) > ff.probe_duration(no_pause) + 0.3


def test_verify_audio_rejects_empty_file(tmp_path):
    empty = tmp_path / "empty.mp3"
    empty.write_bytes(b"")
    assert not ff.verify_audio(empty)


def test_mock_chunks_concatenate(tmp_path):
    mock = MockTTS()
    res = mock.synthesize("First chunk.\n\nSecond chunk.", tmp_path / "chunks")
    out = ff.concat_audio([c.audio_path for c in res.chunks], tmp_path / "section.mp3")
    assert ff.verify_audio(out)
