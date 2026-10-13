from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

DEFAULT_SCHEMA_VERSION = "1.0"


@dataclass
class Book:
    title: str
    source_pdf: str
    language: str = "en"
    page_index_base: int = 1
    notes: str = ""


@dataclass
class Settings:
    tts_engine: str = "kokoro"
    voice: str = "af_heart"
    speed: float = 1.0
    audio_format: str = "mp3"
    combine_into_single_audiobook: bool = True
    keep_intermediate_files: bool = True
    # optional, for future
    inter_section_pause_ms: int = 0
    code_block_policy: str = "read"  # read|announce|skip
    pronunciation_file: Optional[str] = None
    # Optional cleanup overrides; see src/text/cleanup.py::CleanupConfig.
    cleanup: Dict[str, Any] = field(default_factory=dict)


@dataclass
class Section:
    id: str
    title: str
    type: str
    start_page: int
    end_page: int
    include: bool = True
    allow_overlap: bool = False  # explicit opt-in for documented overlaps
    settings: Optional[Dict[str, Any]] = None

    def page_count(self) -> int:
        if self.end_page < self.start_page:
            return 0
        return self.end_page - self.start_page + 1


@dataclass
class Manifest:
    schema_version: str = DEFAULT_SCHEMA_VERSION
    book: Book = field(default_factory=lambda: Book(title="Untitled", source_pdf="book.pdf"))
    settings: Settings = field(default_factory=Settings)
    sections: List[Section] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def generate_template_manifest(output_path: str | Path, pdf_path: str | Path | None = None) -> Path:
    template = {
        "schema_version": "1.0",
        "book": {
            "title": "Example Technical Book",
            "source_pdf": str(pdf_path) if pdf_path else "book.pdf",
            "language": "en",
            "page_index_base": 1,
            "notes": "Replace page ranges with actual PDF physical page indices (1-based, inclusive).",
        },
        "settings": {
            "tts_engine": "kokoro",
            "voice": "af_heart",
            "speed": 1.0,
            "audio_format": "mp3",
            "combine_into_single_audiobook": True,
            "keep_intermediate_files": True,
            "inter_section_pause_ms": 0,
            "code_block_policy": "read",
            "pronunciation_file": None,
            "cleanup": {
                "known_headers": [],
                "known_footers": [],
                "remove_toc": False,
                "remove_bibliography": False,
                "remove_index": False,
                "remove_footnotes": False,
            },
        },
        "sections": [
            {
                "id": "preface",
                "title": "Preface",
                "type": "preface",
                "start_page": 1,
                "end_page": 5,
                "include": True,
            },
            {
                "id": "chapter_01",
                "title": "Chapter 1",
                "type": "chapter",
                "start_page": 6,
                "end_page": 15,
                "include": True,
            },
        ],
    }
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open("w", encoding="utf-8") as f:
        json.dump(template, f, indent=2)
    logger.info("Generated manifest template at %s", out)
    return out


def _validate_section(section: Section, pdf_page_count: int) -> List[str]:
    errors: List[str] = []
    if section.start_page < 1 or section.end_page < 1:
        errors.append(f"Section {section.id}: page numbers must be >= 1")
    if section.start_page > section.end_page:
        errors.append(f"Section {section.id}: start_page ({section.start_page}) > end_page ({section.end_page})")
    if pdf_page_count > 0:
        if section.start_page > pdf_page_count:
            errors.append(f"Section {section.id}: start_page ({section.start_page}) > PDF pages ({pdf_page_count})")
        if section.end_page > pdf_page_count:
            errors.append(f"Section {section.id}: end_page ({section.end_page}) > PDF pages ({pdf_page_count})")
    return errors


def validate_manifest(manifest: Manifest, pdf_page_count: int) -> Tuple[List[str], List[str]]:
    errors: List[str] = []
    warnings: List[str] = []

    if manifest.schema_version != DEFAULT_SCHEMA_VERSION:
        warnings.append(f"schema_version {manifest.schema_version} != {DEFAULT_SCHEMA_VERSION}; treating as compatible")

    if manifest.book.page_index_base not in (0, 1):
        warnings.append(f"page_index_base {manifest.book.page_index_base} unusual (expected 0 or 1)")

    if pdf_page_count < 0:
        pdf_page_count = 0

    # validate each section
    for sec in manifest.sections:
        errors.extend(_validate_section(sec, pdf_page_count))

    # detect overlaps (report). Allow if explicitly allowed per section? spec says "allow explicitly documented overlapping ranges if user deliberately wants same content included more than once"
    # We treat overlap as issue to report; if any involved section has allow_overlap True, we can downgrade to warning? Or just report as warning/info. But spec states "Detect overlapping page ranges and report them for confirmation. Do not silently duplicate or discard pages. Allow explicitly documented overlapping ranges..."
    included = [s for s in manifest.sections if s.include]
    n = len(included)
    for i in range(n):
        for j in range(i + 1, n):
            a = included[i]
            b = included[j]
            # check overlap: ranges [a.start,a.end] and [b.start,b.end] overlap if not (a.end < b.start or b.end < a.start)
            if not (a.end_page < b.start_page or b.end_page < a.start_page):
                msg = f"Overlapping ranges detected: {a.id}({a.start_page}-{a.end_page}) and {b.id}({b.start_page}-{b.end_page})"
                if a.allow_overlap or b.allow_overlap:
                    warnings.append(msg + " [allowed]")
                else:
                    errors.append(msg)

    return errors, warnings


def load_manifest(path: str | Path) -> Manifest:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Manifest not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        data = json.load(f)

    book = Book(
        title=data.get("book", {}).get("title", "Untitled"),
        source_pdf=data.get("book", {}).get("source_pdf", "book.pdf"),
        language=data.get("book", {}).get("language", "en"),
        page_index_base=data.get("book", {}).get("page_index_base", 1),
        notes=data.get("book", {}).get("notes", ""),
    )
    settings_raw = data.get("settings", {}) or {}
    settings = Settings(
        tts_engine=settings_raw.get("tts_engine", "kokoro"),
        voice=settings_raw.get("voice", "af_heart"),
        speed=float(settings_raw.get("speed", 1.0)),
        audio_format=settings_raw.get("audio_format", "mp3"),
        combine_into_single_audiobook=bool(settings_raw.get("combine_into_single_audiobook", True)),
        keep_intermediate_files=bool(settings_raw.get("keep_intermediate_files", True)),
        inter_section_pause_ms=int(settings_raw.get("inter_section_pause_ms", 0)),
        code_block_policy=str(settings_raw.get("code_block_policy", "read")),
        pronunciation_file=settings_raw.get("pronunciation_file"),
        cleanup=dict(settings_raw.get("cleanup", {}) or {}),
    )
    sections: List[Section] = []
    for s in data.get("sections", []):
        sections.append(
            Section(
                id=s["id"],
                title=s.get("title", s["id"]),
                type=s.get("type", "section"),
                start_page=int(s["start_page"]),
                end_page=int(s["end_page"]),
                include=bool(s.get("include", True)),
                allow_overlap=bool(s.get("allow_overlap", False)),
                settings=s.get("settings"),
            )
        )
    return Manifest(schema_version=data.get("schema_version", DEFAULT_SCHEMA_VERSION), book=book, settings=settings, sections=sections)
