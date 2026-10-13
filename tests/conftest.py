from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    import pymupdf as fitz
except ImportError:  # pragma: no cover
    import fitz  # type: ignore

HEADER = "THE TEST BOOK"
PAGE_W, PAGE_H = 612.0, 792.0


def _add_page(doc, body_lines, page_no: int) -> None:
    page = doc.new_page(width=PAGE_W, height=PAGE_H)
    # Running header near the top margin
    page.insert_text((72, 40), HEADER, fontsize=10)
    y = 110.0
    for line in body_lines:
        page.insert_text((72, y), line, fontsize=11)
        y += 18.0
    # Standalone page number near the bottom margin
    page.insert_text((300, 770), str(page_no), fontsize=10)


@pytest.fixture(scope="session")
def sample_pdf(tmp_path_factory) -> Path:
    """A 12-page synthetic technical PDF with headers, footers, page numbers,
    hyphenated line breaks, a numbered list, an equation and a code block."""
    out = tmp_path_factory.mktemp("pdf") / "sample_book.pdf"
    doc = fitz.open()

    # Pages 1-3: preface with a hyphenated word split across lines.
    _add_page(doc, ["Preface", "This preface explains hyphen-", "ation handling in depth.",
                    "It also mentions 42 things."], 1)
    _add_page(doc, ["The preface continues here.", "Second paragraph of the preface."], 2)
    _add_page(doc, ["Final preface page.", "See Figure 3 for details."], 3)

    # Pages 4-8: chapter 1 with list, equation and code.
    _add_page(doc, ["Chapter 1: Foundations", "Introductory paragraph for the chapter.",
                    "1. First numbered item", "2. Second numbered item"], 4)
    _add_page(doc, ["A paragraph that wraps onto the next", "line without a hyphen.",
                    "Equation: E = mc^2 is famous."], 5)
    _add_page(doc, ["Code follows:", "```python", "def add(a, b):", "    return a + b", "```"], 6)
    _add_page(doc, ["Another body page mentioning references", "and citations [1] and [2]."], 7)
    _add_page(doc, ["The chapter summary appears here.", "variable_name should be preserved."], 8)

    # Pages 9-12: appendix.
    _add_page(doc, ["Appendix A", "Supplementary material begins."], 9)
    _add_page(doc, ["More appendix text about tables."], 10)
    _add_page(doc, ["More appendix text about figures."], 11)
    _add_page(doc, ["Appendix conclusion."], 12)

    doc.save(str(out))
    doc.close()
    return out


def make_manifest(pdf_path: Path, sections=None, settings=None, book=None) -> dict:
    base = {
        "schema_version": "1.0",
        "book": {
            "title": "Sample Test Book",
            "source_pdf": str(pdf_path),
            "language": "en",
            "page_index_base": 1,
            "notes": "",
        },
        "settings": {
            "tts_engine": "mock",
            "voice": "af_heart",
            "speed": 1.0,
            "audio_format": "mp3",
            "combine_into_single_audiobook": True,
            "keep_intermediate_files": True,
        },
        "sections": sections
        or [
            {"id": "preface", "title": "Preface", "type": "preface",
             "start_page": 1, "end_page": 3, "include": True},
            {"id": "chapter_01", "title": "Chapter 1", "type": "chapter",
             "start_page": 4, "end_page": 8, "include": True},
            {"id": "appendix_a", "title": "Appendix A", "type": "appendix",
             "start_page": 9, "end_page": 12, "include": True},
        ],
    }
    if book:
        base["book"].update(book)
    if settings:
        base["settings"].update(settings)
    return base


@pytest.fixture
def manifest_path(tmp_path, sample_pdf) -> Path:
    p = tmp_path / "book_manifest.json"
    p.write_text(json.dumps(make_manifest(sample_pdf), indent=2), encoding="utf-8")
    return p


@pytest.fixture
def write_manifest(tmp_path):
    def _write(data: dict, name: str = "manifest.json") -> Path:
        p = tmp_path / name
        p.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return p

    return _write
