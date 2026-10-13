from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from ..audio import ffmpeg as ff
from ..manifest import Manifest, Section, load_manifest, validate_manifest
from ..pdf.extractor import extract_section_pages
from ..speech.preprocess import (
    SPEECH_VERSION,
    SpeechConfig,
    load_pronunciation_file,
    preprocess_for_speech,
)
from ..text.cleanup import CLEANUP_VERSION, CleanupConfig, cleanup_text
from ..tts.base import BaseTTS
from ..tts.mock import MockTTS
from ..utils.files import compute_text_hash, file_sha256, safe_filename
from .state import SectionStatus, StateStore, build_report, write_report

logger = logging.getLogger(__name__)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunConfig:
    pdf_path: Path
    manifest_path: Path
    output_dir: Path = Path("output")
    only_sections: Optional[List[str]] = None
    retry_failed: bool = False
    stop_after: Optional[str] = None  # "extract" | "clean" | "speech" | "audio"
    combine: Optional[bool] = None  # override manifest setting
    force: bool = False
    keep_intermediate: Optional[bool] = None
    # CLI overrides; applied in memory so the user's manifest file is untouched
    tts_engine: Optional[str] = None
    voice: Optional[str] = None
    speed: Optional[float] = None
    max_chunks_per_section: Optional[int] = None  # useful for smoke tests
    cleanup_config: CleanupConfig = field(default_factory=CleanupConfig)
    speech_config: SpeechConfig = field(default_factory=SpeechConfig)


class PipelineRunner:
    def __init__(
        self,
        config: RunConfig,
        tts_factory: Optional[Callable[[str], BaseTTS]] = None,
    ) -> None:
        self.config = config
        self.tts_factory = tts_factory or self._default_tts_factory
        self.manifest: Manifest = load_manifest(config.manifest_path)
        self._apply_overrides()
        self.book_dir = Path(config.output_dir) / safe_filename(self.manifest.book.title or "book")
        self.sections_dir = self.book_dir / "sections"
        self.audiobooks_dir = self.book_dir / "audiobooks"
        self.logs_dir = self.book_dir / "logs"
        self.store = StateStore(self.book_dir / "manifest.json")
        self._tts: Optional[BaseTTS] = None

    def _apply_overrides(self) -> None:
        """Apply CLI overrides to the in-memory manifest only."""
        if self.config.tts_engine:
            self.manifest.settings.tts_engine = self.config.tts_engine
        if self.config.voice:
            self.manifest.settings.voice = self.config.voice
        if self.config.speed is not None:
            self.manifest.settings.speed = float(self.config.speed)
        self._apply_manifest_settings()

    def _apply_manifest_settings(self) -> None:
        """Feed manifest ``settings`` into the cleanup/speech configurations."""
        settings = self.manifest.settings

        # Speech: code-block handling and pronunciation rules.
        self.config.speech_config.code_block_policy = settings.code_block_policy
        if settings.pronunciation_file:
            path = Path(settings.pronunciation_file)
            if not path.is_absolute():
                # Resolve relative to the manifest so paths stay portable.
                path = Path(self.config.manifest_path).parent / path
            rules = load_pronunciation_file(path)
            if rules:
                self.config.speech_config.pronunciation_rules = rules
            else:
                logger.warning("No pronunciation rules loaded from %s", path)

        # Cleanup: optional known headers/footers and content filters.
        cleanup_opts = settings.cleanup or {}
        if not cleanup_opts:
            return
        cfg = self.config.cleanup_config
        for key in ("known_headers", "known_footers"):
            if isinstance(cleanup_opts.get(key), list):
                setattr(cfg, key, [str(v) for v in cleanup_opts[key]])
        for key in ("remove_toc", "remove_bibliography", "remove_index", "remove_footnotes",
                    "repair_hyphenation", "join_wrapped_lines", "remove_page_numbers",
                    "remove_running_headers"):
            if key in cleanup_opts:
                setattr(cfg, key, bool(cleanup_opts[key]))

    # -- TTS ---------------------------------------------------------------

    @staticmethod
    def _default_tts_factory(engine: str) -> BaseTTS:
        if engine == "mock":
            return MockTTS()
        from ..tts.kokoro_engine import KokoroTTS

        return KokoroTTS()

    @property
    def tts(self) -> BaseTTS:
        if self._tts is None:
            self._tts = self.tts_factory(self.manifest.settings.tts_engine)
        return self._tts

    # -- setup -------------------------------------------------------------

    def prepare(self) -> List[str]:
        """Validate inputs, create directories, seed state. Returns warnings."""
        pdf_path = Path(self.config.pdf_path)
        if not pdf_path.exists():
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        # Page count for validation
        try:
            import pymupdf as fitz
        except ImportError:  # pragma: no cover
            import fitz  # type: ignore

        doc = fitz.open(pdf_path)
        try:
            page_count = doc.page_count
        finally:
            doc.close()

        errors, warnings = validate_manifest(self.manifest, page_count)
        if errors:
            raise ValueError("Manifest validation failed:\n  - " + "\n  - ".join(errors))

        self.book_dir.mkdir(parents=True, exist_ok=True)
        self.sections_dir.mkdir(parents=True, exist_ok=True)
        self.audiobooks_dir.mkdir(parents=True, exist_ok=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)

        self.store.state.book_title = self.manifest.book.title
        self.store.state.pdf_path = str(pdf_path)
        self.store.state.manifest_path = str(self.config.manifest_path)
        if not self.store.state.pdf_hash:
            self.store.state.pdf_hash = file_sha256(pdf_path)
        self.store.state.settings = {
            "tts_engine": self.manifest.settings.tts_engine,
            "voice": self.manifest.settings.voice,
            "speed": self.manifest.settings.speed,
            "audio_format": self.manifest.settings.audio_format,
            "combine_into_single_audiobook": self.manifest.settings.combine_into_single_audiobook,
        }

        for sec in self.manifest.sections:
            self.store.ensure_section(
                sec.id,
                title=sec.title,
                type=sec.type,
                start_page=sec.start_page,
                end_page=sec.end_page,
                include=sec.include,
            )
        self.store.save()
        return warnings

    def run(self) -> Dict[str, Any]:
        started = _now()
        warnings = self.prepare()
        for w in warnings:
            logger.warning(w)

        stop_after = self.config.stop_after
        stage_index = {"extract": 0, "clean": 1, "speech": 2, "audio": 3, None: 3}

        for section in self.manifest.sections:
            if not section.include:
                logger.info("Skipping excluded section %s", section.id)
                continue
            if self.config.only_sections and section.id not in self.config.only_sections:
                continue
            sec_state = self.store.state.sections[section.id]
            if self.config.retry_failed and not sec_state.is_failed():
                continue
            try:
                self._process_section(section, stage_index.get(stop_after, 3))
            except Exception as e:  # keep going with other sections
                logger.exception("Section %s failed", section.id)
                self.store.mark_failed(section.id, str(e))

        combine = self._should_combine()
        combined_path: Optional[Path] = None
        if combine and stage_index.get(stop_after, 3) >= 3:
            try:
                combined_path = self.combine_audiobook()
            except Exception as e:
                logger.exception("Failed to combine audiobook")
                for sid in self.store.state.order:
                    self.store.add_warning(sid, f"combine failed: {e}")

        finished = _now()
        extra: Dict[str, Any] = {}
        if combined_path:
            extra["complete_audiobook"] = str(combined_path)
        report = build_report(self.store, self.book_dir, started, finished, extra)
        report_path = write_report(report, self.book_dir / "report.json")
        logger.info("Wrote report to %s", report_path)
        return report

    # -- per section -------------------------------------------------------

    def _section_dir(self, section: Section) -> Path:
        return self.sections_dir / safe_filename(section.id)

    def _hash_section_config(self, section: Section) -> str:
        return compute_text_hash(
            json.dumps(
                {
                    "id": section.id,
                    "type": section.type,
                    "start": section.start_page,
                    "end": section.end_page,
                },
                sort_keys=True,
            )
        )

    def _hash_cleanup(self) -> str:
        c = self.config.cleanup_config
        return compute_text_hash(
            json.dumps(
                {"version": CLEANUP_VERSION, "config": c.__dict__},
                sort_keys=True,
                default=str,
            )
        )

    def _hash_speech(self) -> str:
        c = self.config.speech_config
        return compute_text_hash(
            json.dumps(
                {
                    "version": SPEECH_VERSION,
                    "code_block_policy": c.code_block_policy,
                    "abbreviations": c.abbreviations,
                    "rules": [(r.pattern, r.replacement, r.regex) for r in c.pronunciation_rules],
                    "expand": c.expand_abbreviations,
                },
                sort_keys=True,
                default=str,
            )
        )

    def _hash_tts_params(self) -> str:
        s = self.manifest.settings
        return compute_text_hash(
            json.dumps(
                {
                    "engine": s.tts_engine,
                    "voice": s.voice,
                    "speed": s.speed,
                    "format": s.audio_format,
                },
                sort_keys=True,
            )
        )

    def _process_section(self, section: Section, max_stage: int) -> None:
        sec_dir = self._section_dir(section)
        sec_dir.mkdir(parents=True, exist_ok=True)
        (sec_dir / "chunks").mkdir(exist_ok=True)

        state = self.store.ensure_section(section.id)
        cfg_hash = self._hash_section_config(section)
        pdf_hash = self.store.state.pdf_hash

        # ---- 1. extract --------------------------------------------------
        raw_path = sec_dir / "raw.txt"
        need_extract = self.config.force or not (
            raw_path.exists()
            and state.is_extracted()
            and state.hashes.get("section_config") == cfg_hash
            and state.hashes.get("pdf") == pdf_hash
        )
        if need_extract:
            self.store.set_status(section.id, SectionStatus.EXTRACTING)
            result = extract_section_pages(
                Path(self.config.pdf_path),
                section.id,
                section.start_page,
                section.end_page,
                page_index_base=self.manifest.book.page_index_base,
            )
            raw_path.write_text(result.raw_text, encoding="utf-8")
            meta_path = sec_dir / "extraction.json"
            meta_path.write_text(json.dumps(result.to_metadata(), indent=2), encoding="utf-8")
            state.warnings = list(dict.fromkeys(state.warnings + result.warnings))
            self.store.update(
                section.id,
                status=SectionStatus.EXTRACTED.value,
                error=None,
                outputs={"raw": str(raw_path), "extraction_meta": str(meta_path)},
                hashes={
                    "section_config": cfg_hash,
                    "pdf": pdf_hash,
                    "raw": compute_text_hash(result.raw_text),
                },
            )
            logger.info("Section %s: extracted %d pages", section.id, section.page_count())

        if max_stage < 1:
            return

        # ---- 2. clean ----------------------------------------------------
        cleaned_path = sec_dir / "cleaned.txt"
        cleanup_hash = self._hash_cleanup()
        need_clean = self.config.force or not (
            cleaned_path.exists()
            and state.is_cleaned()
            and state.hashes.get("cleanup") == cleanup_hash
            and state.hashes.get("raw") == compute_text_hash(raw_path.read_text(encoding="utf-8"))
        )
        if need_clean:
            self.store.set_status(section.id, SectionStatus.CLEANING)
            raw_text = raw_path.read_text(encoding="utf-8")
            meta = json.loads((sec_dir / "extraction.json").read_text(encoding="utf-8"))
            page_height = float(meta.get("page_height", 0)) or self._page_height(meta)
            blocks = _blocks_from_meta(meta)
            cleaned, info = cleanup_text(
                raw_text,
                config=self.config.cleanup_config,
                blocks=blocks,
                page_height=page_height,
            )
            cleaned_path.write_text(cleaned, encoding="utf-8")
            (sec_dir / "cleanup.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
            self.store.update(
                section.id,
                status=SectionStatus.CLEANED.value,
                outputs={"cleaned": str(cleaned_path)},
                hashes={"cleanup": cleanup_hash, "cleaned": compute_text_hash(cleaned)},
            )
            logger.info("Section %s: cleaned (%d chars)", section.id, len(cleaned))

        if max_stage < 2:
            return

        # ---- 3. speech ---------------------------------------------------
        speech_path = sec_dir / "speech.txt"
        speech_hash_cfg = self._hash_speech()
        cleaned_text = cleaned_path.read_text(encoding="utf-8")
        need_speech = self.config.force or not (
            speech_path.exists()
            and state.hashes.get("speech") == speech_hash_cfg
            and state.hashes.get("cleaned") == compute_text_hash(cleaned_text)
        )
        if need_speech:
            speech_text, info = preprocess_for_speech(cleaned_text, config=self.config.speech_config)
            speech_path.write_text(speech_text, encoding="utf-8")
            (sec_dir / "speech.json").write_text(json.dumps(info, indent=2), encoding="utf-8")
            self.store.update(
                section.id,
                outputs={"speech": str(speech_path)},
                hashes={"speech": speech_hash_cfg, "speech_text": compute_text_hash(speech_text)},
            )
            logger.info("Section %s: prepared speech text (%d chars)", section.id, len(speech_text))

        if max_stage < 3:
            return

        # ---- 4. synthesize ----------------------------------------------
        speech_text = speech_path.read_text(encoding="utf-8")
        chunks_dir = sec_dir / "chunks"
        section_mp3 = sec_dir / f"{safe_filename(section.id)}.mp3"
        tts_hash = self._hash_tts_params()
        need_tts = self.config.force or not (
            section_mp3.exists()
            and state.is_audio_ready()
            and state.hashes.get("tts_params") == tts_hash
            and state.hashes.get("speech_text") == compute_text_hash(speech_text)
        )
        if need_tts:
            self.store.set_status(section.id, SectionStatus.SYNTHESIZING)
            if not speech_text.strip():
                raise RuntimeError("no speech text to synthesize")
            result = self.tts.synthesize(
                speech_text,
                chunks_dir,
                voice=self.manifest.settings.voice,
                speed=self.manifest.settings.speed,
            )
            chunks = [c.audio_path for c in result.chunks]
            if self.config.max_chunks_per_section:
                chunks = chunks[: self.config.max_chunks_per_section]
            if not chunks:
                raise RuntimeError("TTS produced no audio chunks")
            ff.concat_audio(
                chunks,
                section_mp3,
                sample_rate=24000,
                channels=1,
                # No silence between chunks inside a section; inter-section
                # pause (if configured) is applied when combining sections.
                pause_ms=0,
            )
            (chunks_dir / "index.json").write_text(
                json.dumps(
                    [{"index": c.index, "file": c.audio_path.name, "duration": c.duration_seconds, "text": c.text} for c in result.chunks],
                    indent=2,
                ),
                encoding="utf-8",
            )
            self.store.update(
                section.id,
                status=SectionStatus.AUDIO_READY.value,
                error=None,
                outputs={"audio": str(section_mp3), "chunks_dir": str(chunks_dir)},
                hashes={"tts_params": tts_hash},
                chunk_count=len(chunks),
                duration_seconds=ff.probe_duration(section_mp3),
            )
            logger.info("Section %s: audio ready -> %s", section.id, section_mp3)

        if not (self.config.keep_intermediate if self.config.keep_intermediate is not None
                else self.manifest.settings.keep_intermediate_files):
            self._cleanup_intermediates(sec_dir)

    # -- helpers -----------------------------------------------------------

    @staticmethod
    def _page_height(meta: Dict[str, Any]) -> float:
        heights = [b["bbox"][3] for b in meta.get("blocks", []) if b.get("bbox")]
        return max(heights) if heights else 0.0

    @staticmethod
    def _cleanup_intermediates(sec_dir: Path) -> None:
        chunks = sec_dir / "chunks"
        if chunks.exists():
            import shutil

            shutil.rmtree(chunks, ignore_errors=True)
        for name in ("extraction.json", "cleanup.json", "speech.json"):
            p = sec_dir / name
            if p.exists():
                p.unlink()

    def _should_combine(self) -> bool:
        if self.config.combine is not None:
            return self.config.combine
        # A partial run (--section / --retry-failed) can never produce a complete
        # audiobook, so do not attempt to combine unless explicitly requested.
        if self.config.only_sections:
            return False
        return self.manifest.settings.combine_into_single_audiobook

    def combine_audiobook(self) -> Path:
        """Concatenate section MP3s in manifest order."""
        inputs: List[Path] = []
        missing: List[str] = []
        for section in self.manifest.sections:
            if not section.include:
                continue
            sec = self.store.state.sections.get(section.id)
            if sec is None or not sec.is_audio_ready():
                missing.append(section.id)
                continue
            mp3 = self._section_dir(section) / f"{safe_filename(section.id)}.mp3"
            if not mp3.exists():
                missing.append(section.id)
                continue
            inputs.append(mp3)

        if not inputs:
            raise RuntimeError("no completed section audio to combine")
        if missing:
            raise RuntimeError(
                "refusing to combine incomplete audiobook; unfinished sections: " + ", ".join(missing)
            )

        output = self.audiobooks_dir / "complete_audiobook.mp3"
        ff.concat_audio(
            inputs,
            output,
            sample_rate=24000,
            channels=1,
            pause_ms=self.manifest.settings.inter_section_pause_ms,
        )
        if not ff.verify_audio(output):
            raise RuntimeError(f"combined audiobook is not playable: {output}")
        self.store.state.settings["complete_audiobook"] = str(output)
        self.store.save()
        logger.info("Combined audiobook -> %s", output)
        return output


def _blocks_from_meta(meta: Dict[str, Any]):
    from ..pdf.extractor import PageBlock

    blocks = []
    for b in meta.get("blocks", []):
        blocks.append(
            PageBlock(
                block_id=b.get("block_id", -1),
                page_num=b.get("page_num", 0),
                text=b.get("text", ""),
                bbox=tuple(b.get("bbox", (0, 0, 0, 0))),
            )
        )
    return blocks
