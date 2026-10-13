from __future__ import annotations

import json

import pytest

from src.manifest.schema import (
    Manifest,
    generate_template_manifest,
    load_manifest,
    validate_manifest,
)
from tests.conftest import make_manifest


def _load(tmp_path, data) -> Manifest:
    p = tmp_path / "m.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return load_manifest(p)


def test_load_manifest_basic(tmp_path, sample_pdf):
    m = _load(tmp_path, make_manifest(sample_pdf))
    assert m.schema_version == "1.0"
    assert m.book.title == "Sample Test Book"
    assert m.book.page_index_base == 1
    assert [s.id for s in m.sections] == ["preface", "chapter_01", "appendix_a"]
    assert m.sections[0].start_page == 1 and m.sections[0].end_page == 3
    assert m.sections[0].page_count() == 3  # inclusive


def test_validate_ok(sample_pdf, tmp_path):
    m = _load(tmp_path, make_manifest(sample_pdf))
    errors, warnings = validate_manifest(m, pdf_page_count=20)
    assert errors == []


def test_page_range_out_of_bounds(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[{"id": "x", "title": "X", "type": "chapter", "start_page": 1, "end_page": 99}],
    )
    m = _load(tmp_path, data)
    errors, _ = validate_manifest(m, pdf_page_count=12)
    assert any("end_page" in e and "99" in e for e in errors)


def test_start_after_end_is_error(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[{"id": "x", "title": "X", "type": "chapter", "start_page": 9, "end_page": 4}],
    )
    m = _load(tmp_path, data)
    errors, _ = validate_manifest(m, pdf_page_count=12)
    assert any("start_page" in e and "end_page" in e for e in errors)


def test_zero_and_negative_pages_invalid(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[{"id": "x", "title": "X", "type": "chapter", "start_page": 0, "end_page": 3}],
    )
    m = _load(tmp_path, data)
    errors, _ = validate_manifest(m, pdf_page_count=12)
    assert any(">= 1" in e for e in errors)


def test_overlap_reported(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[
            {"id": "a", "title": "A", "type": "chapter", "start_page": 1, "end_page": 5},
            {"id": "b", "title": "B", "type": "chapter", "start_page": 5, "end_page": 9},
        ],
    )
    m = _load(tmp_path, data)
    errors, warnings = validate_manifest(m, pdf_page_count=12)
    assert any("Overlapping" in e for e in errors)


def test_overlap_allowed_when_explicit(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[
            {"id": "a", "title": "A", "type": "chapter", "start_page": 1, "end_page": 5,
             "allow_overlap": True},
            {"id": "b", "title": "B", "type": "chapter", "start_page": 5, "end_page": 9},
        ],
    )
    m = _load(tmp_path, data)
    errors, warnings = validate_manifest(m, pdf_page_count=12)
    assert errors == []
    assert any("Overlapping" in w and "allowed" in w for w in warnings)


def test_excluded_sections_do_not_trigger_overlap(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[
            {"id": "a", "title": "A", "type": "chapter", "start_page": 1, "end_page": 5, "include": True},
            {"id": "b", "title": "B", "type": "chapter", "start_page": 1, "end_page": 5, "include": False},
        ],
    )
    m = _load(tmp_path, data)
    errors, _ = validate_manifest(m, pdf_page_count=12)
    assert errors == []


def test_gaps_are_allowed(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[
            {"id": "a", "title": "A", "type": "chapter", "start_page": 1, "end_page": 3},
            {"id": "b", "title": "B", "type": "chapter", "start_page": 7, "end_page": 9},
        ],
    )
    m = _load(tmp_path, data)
    errors, _ = validate_manifest(m, pdf_page_count=12)
    assert errors == []


def test_section_order_preserved(tmp_path, sample_pdf):
    data = make_manifest(
        sample_pdf,
        sections=[
            {"id": "z", "title": "Z", "type": "chapter", "start_page": 9, "end_page": 12},
            {"id": "a", "title": "A", "type": "preface", "start_page": 1, "end_page": 3},
        ],
    )
    m = _load(tmp_path, data)
    assert [s.id for s in m.sections] == ["z", "a"]


def test_template_generation(tmp_path, sample_pdf):
    out = generate_template_manifest(tmp_path / "tpl.json", sample_pdf)
    data = json.loads(out.read_text(encoding="utf-8"))
    assert data["schema_version"] == "1.0"
    assert data["sections"]
    # Template must not claim real boundaries
    assert data["book"]["notes"]


def test_missing_manifest_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        load_manifest(tmp_path / "nope.json")


def test_future_settings_preserved(tmp_path, sample_pdf):
    data = make_manifest(sample_pdf)
    data["settings"]["some_future_option"] = "x"
    data["sections"][0]["settings"] = {"voice": "am_adam"}
    m = _load(tmp_path, data)
    assert m.sections[0].settings == {"voice": "am_adam"}
