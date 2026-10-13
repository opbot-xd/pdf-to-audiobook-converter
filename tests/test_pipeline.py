from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.audio import ffmpeg as ff
from src.pipeline import runner as runner_mod
from src.pipeline.runner import PipelineRunner, RunConfig
from src.pipeline.state import SectionStatus
from src.tts.mock import MockTTS
from tests.conftest import make_manifest

pytestmark = pytest.mark.skipif(not ff.ffmpeg_available(), reason="ffmpeg not installed")


class CountingTTS(MockTTS):
    def __init__(self):
        self.calls = []

    def synthesize(self, text, output_dir, voice="af_heart", speed=1.0):
        self.calls.append({"dir": str(output_dir), "chars": len(text), "voice": voice, "speed": speed})
        return super().synthesize(text, output_dir, voice, speed)


def _factory(tts: CountingTTS):
    def factory(engine: str):
        return tts

    return factory


@pytest.fixture
def manifest_file(tmp_path, sample_pdf):
    p = tmp_path / "book_manifest.json"
    p.write_text(json.dumps(make_manifest(sample_pdf), indent=2), encoding="utf-8")
    return p


def _config(pdf, manifest, out, **kw):
    return RunConfig(pdf_path=Path(pdf), manifest_path=Path(manifest), output_dir=Path(out), **kw)


def test_end_to_end_outputs(tmp_path, sample_pdf, manifest_file):
    tts = CountingTTS()
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"), tts_factory=_factory(tts))
    report = runner.run()

    book_dir = runner.book_dir
    for sid in ("preface", "chapter_01", "appendix_a"):
        sec = book_dir / "sections" / sid
        assert (sec / "raw.txt").exists()
        assert (sec / "cleaned.txt").exists()
        assert (sec / "speech.txt").exists()
        assert (sec / f"{sid}.mp3").exists()
        assert ff.verify_audio(sec / f"{sid}.mp3")

    combined = book_dir / "audiobooks" / "complete_audiobook.mp3"
    assert combined.exists() and ff.verify_audio(combined)
    assert (book_dir / "report.json").exists()
    assert report["totals"]["completed"] == 3
    assert report["totals"]["failed"] == 0
    assert tts.calls  # audio was synthesized


def test_output_files_named_from_section_id(tmp_path, sample_pdf, manifest_file):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"))
    runner.run()
    mp3s = sorted(p.name for p in (runner.book_dir / "sections").glob("*/*.mp3"))
    assert mp3s == ["appendix_a.mp3", "chapter_01.mp3", "preface.mp3"]


def test_combine_follows_manifest_order(tmp_path, sample_pdf):
    # Appendix first, then preface -> combined order must match manifest, not alphabet.
    sections = [
        {"id": "appendix_a", "title": "Appendix", "type": "appendix", "start_page": 9, "end_page": 12},
        {"id": "preface", "title": "Preface", "type": "preface", "start_page": 1, "end_page": 3},
    ]
    mp = tmp_path / "ordered.json"
    mp.write_text(json.dumps(make_manifest(sample_pdf, sections=sections)), encoding="utf-8")

    captured = {}
    original = runner_mod.ff.concat_audio

    def spy(input_files, output_path, **kwargs):
        if str(output_path).endswith("complete_audiobook.mp3"):
            captured["order"] = [Path(f).name for f in input_files]
        return original(input_files, output_path, **kwargs)

    runner_mod.ff.concat_audio = spy
    try:
        runner = PipelineRunner(_config(sample_pdf, mp, tmp_path / "out"))
        runner.run()
    finally:
        runner_mod.ff.concat_audio = original

    assert captured["order"] == ["appendix_a.mp3", "preface.mp3"]


def test_resume_skips_completed_work(tmp_path, sample_pdf, manifest_file):
    tts1 = CountingTTS()
    r1 = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"), tts_factory=_factory(tts1))
    r1.run()
    assert len(tts1.calls) == 3

    tts2 = CountingTTS()
    r2 = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"), tts_factory=_factory(tts2))
    report = r2.run()
    assert tts2.calls == []  # nothing regenerated
    assert report["totals"]["completed"] == 3


def test_force_regenerates(tmp_path, sample_pdf, manifest_file):
    tts1 = CountingTTS()
    PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"), tts_factory=_factory(tts1)).run()
    tts2 = CountingTTS()
    PipelineRunner(
        _config(sample_pdf, manifest_file, tmp_path / "out", force=True), tts_factory=_factory(tts2)
    ).run()
    assert len(tts2.calls) == 3


def test_single_section_processing(tmp_path, sample_pdf, manifest_file):
    tts = CountingTTS()
    PipelineRunner(
        _config(sample_pdf, manifest_file, tmp_path / "out", only_sections=["preface"], combine=False),
        tts_factory=_factory(tts),
    ).run()
    assert len(tts.calls) == 1
    assert (tmp_path / "out" / "Sample_Test_Book" / "sections" / "preface" / "preface.mp3").exists()


def test_partial_run_does_not_attempt_combine(tmp_path, sample_pdf, manifest_file):
    """`--section` cannot yield a complete audiobook, so combining is skipped."""
    runner = PipelineRunner(
        _config(sample_pdf, manifest_file, tmp_path / "out", only_sections=["preface"])
    )
    report = runner.run()
    assert not (runner.book_dir / "audiobooks" / "complete_audiobook.mp3").exists()
    assert "complete_audiobook" not in report
    assert not any("combine failed" in w for w in report["extraction_warnings"])


def test_partial_run_then_resume_completes_book(tmp_path, sample_pdf, manifest_file):
    out = tmp_path / "out"
    one = CountingTTS()
    PipelineRunner(
        _config(sample_pdf, manifest_file, out, only_sections=["preface"]), tts_factory=_factory(one)
    ).run()
    assert len(one.calls) == 1

    rest = CountingTTS()
    runner = PipelineRunner(_config(sample_pdf, manifest_file, out), tts_factory=_factory(rest))
    report = runner.run()
    # only the remaining two sections are synthesized
    assert len(rest.calls) == 2
    assert report["totals"]["completed"] == 3
    assert (runner.book_dir / "audiobooks" / "complete_audiobook.mp3").exists()


def test_extract_only_stops_before_audio(tmp_path, sample_pdf, manifest_file):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out", stop_after="extract"))
    runner.run()
    sec = runner.book_dir / "sections" / "preface"
    assert (sec / "raw.txt").exists()
    assert not (sec / "cleaned.txt").exists()
    assert not (sec / "preface.mp3").exists()


def test_failure_recovery_and_retry(tmp_path, sample_pdf, manifest_file, monkeypatch):
    original = runner_mod.extract_section_pages

    def flaky(pdf, section_id, *args, **kwargs):
        if section_id == "appendix_a":
            raise RuntimeError("simulated extraction failure")
        return original(pdf, section_id, *args, **kwargs)

    monkeypatch.setattr(runner_mod, "extract_section_pages", flaky)
    r1 = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"))
    report1 = r1.run()
    assert report1["totals"]["failed"] == 1
    assert "appendix_a" in report1["failed_sections"]
    # Other sections survived
    assert report1["totals"]["completed"] == 2
    # No combined audiobook from incomplete sections
    assert not (r1.book_dir / "audiobooks" / "complete_audiobook.mp3").exists()

    monkeypatch.setattr(runner_mod, "extract_section_pages", original)
    r2 = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out", retry_failed=True))
    report2 = r2.run()
    assert report2["totals"]["failed"] == 0
    assert report2["totals"]["completed"] == 3
    assert (r2.book_dir / "audiobooks" / "complete_audiobook.mp3").exists()


def test_combine_refuses_incomplete(tmp_path, sample_pdf, manifest_file):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out", combine=False))
    runner.run()
    # Remove one section's audio to simulate an incomplete run
    mp3 = runner.book_dir / "sections" / "preface" / "preface.mp3"
    mp3.unlink()
    runner.store.update("preface", status=SectionStatus.FAILED.value, error="gone")
    with pytest.raises(RuntimeError, match="incomplete"):
        runner.combine_audiobook()


def test_no_combine_flag(tmp_path, sample_pdf, manifest_file):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out", combine=False))
    runner.run()
    assert not (runner.book_dir / "audiobooks" / "complete_audiobook.mp3").exists()


def test_excluded_section_is_skipped(tmp_path, sample_pdf):
    sections = [
        {"id": "preface", "title": "Preface", "type": "preface", "start_page": 1, "end_page": 3},
        {"id": "chapter_01", "title": "Chapter 1", "type": "chapter", "start_page": 4, "end_page": 8,
         "include": False},
    ]
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(make_manifest(sample_pdf, sections=sections)), encoding="utf-8")
    runner = PipelineRunner(_config(sample_pdf, mp, tmp_path / "out"))
    report = runner.run()
    assert report["totals"]["skipped"] == 1
    assert not (runner.book_dir / "sections" / "chapter_01" / "chapter_01.mp3").exists()


def test_report_lists_outputs_and_warnings(tmp_path, sample_pdf, manifest_file):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"))
    report = runner.run()
    preface = next(s for s in report["sections"] if s["id"] == "preface")
    assert "audio" in preface["outputs"]
    assert preface["status"] == "audio_ready"
    assert report["pdf_hash"]
    assert report["extraction_warnings"] is not None


def test_manifest_settings_drive_cleanup_and_speech(tmp_path, sample_pdf):
    """settings.cleanup and settings.code_block_policy must reach the stages."""
    sections = [{"id": "preface", "title": "Preface", "type": "preface",
                 "start_page": 1, "end_page": 3}]
    data = make_manifest(sample_pdf, sections=sections)
    data["settings"]["code_block_policy"] = "skip"
    data["settings"]["cleanup"] = {
        "known_headers": ["SAMPLE TECHNICAL BOOK"],
        "remove_toc": True,
    }
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(data), encoding="utf-8")

    runner = PipelineRunner(_config(sample_pdf, mp, tmp_path / "out", combine=False))
    runner.run()

    cleaned = (runner.book_dir / "sections" / "preface" / "cleaned.txt").read_text(encoding="utf-8")
    assert "SAMPLE TECHNICAL BOOK" not in cleaned
    cleanup_info = json.loads(
        (runner.book_dir / "sections" / "preface" / "cleanup.json").read_text(encoding="utf-8")
    )
    assert "strip_toc" in cleanup_info["applied"]
    assert runner.config.speech_config.code_block_policy == "skip"


def test_manifest_pronunciation_file_is_loaded(tmp_path, sample_pdf):
    rules = tmp_path / "pron.json"
    rules.write_text(json.dumps({"rules": [{"pattern": "GPU", "replacement": "G P U"}]}), encoding="utf-8")
    sections = [{"id": "preface", "title": "Preface", "type": "preface",
                 "start_page": 1, "end_page": 3}]
    data = make_manifest(sample_pdf, sections=sections)
    data["settings"]["pronunciation_file"] = "pron.json"  # relative to the manifest
    mp = tmp_path / "m.json"
    mp.write_text(json.dumps(data), encoding="utf-8")

    runner = PipelineRunner(_config(sample_pdf, mp, tmp_path / "out", combine=False))
    assert [r.pattern for r in runner.config.speech_config.pronunciation_rules] == ["GPU"]


def test_cleanup_logic_version_invalidates_cache(tmp_path, sample_pdf, manifest_file, monkeypatch):
    """Changing cleanup *logic* (not config) must invalidate cached cleaned text."""
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"))
    before = runner._hash_cleanup()
    monkeypatch.setattr(runner_mod, "CLEANUP_VERSION", "999")
    assert runner._hash_cleanup() != before


def test_speech_logic_version_invalidates_cache(tmp_path, sample_pdf, manifest_file, monkeypatch):
    runner = PipelineRunner(_config(sample_pdf, manifest_file, tmp_path / "out"))
    before = runner._hash_speech()
    monkeypatch.setattr(runner_mod, "SPEECH_VERSION", "999")
    assert runner._hash_speech() != before


def test_cleanup_version_bump_recleans(tmp_path, sample_pdf, manifest_file, monkeypatch):
    """End-to-end: bumping the version forces re-cleaning on the next run."""
    out = tmp_path / "out"
    PipelineRunner(_config(sample_pdf, manifest_file, out)).run()
    cleaned = out / "Sample_Test_Book" / "sections" / "preface" / "cleaned.txt"
    cleaned.write_text("STALE", encoding="utf-8")
    monkeypatch.setattr(runner_mod, "CLEANUP_VERSION", "999")
    PipelineRunner(_config(sample_pdf, manifest_file, out)).run()
    assert "STALE" not in cleaned.read_text(encoding="utf-8")


def test_invalid_manifest_raises_before_work(tmp_path, sample_pdf):
    sections = [{"id": "bad", "title": "Bad", "type": "chapter", "start_page": 5, "end_page": 999}]
    mp = tmp_path / "bad.json"
    mp.write_text(json.dumps(make_manifest(sample_pdf, sections=sections)), encoding="utf-8")
    runner = PipelineRunner(_config(sample_pdf, mp, tmp_path / "out"))
    with pytest.raises(ValueError):
        runner.prepare()
