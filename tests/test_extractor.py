from __future__ import annotations

from src.pdf.extractor import extract_section_pages


def test_extract_inclusive_range(sample_pdf):
    res = extract_section_pages(sample_pdf, "preface", 1, 3)
    assert res.page_range == (1, 3)
    assert "Preface" in res.raw_text
    # page 4 content must not leak in
    assert "Chapter 1" not in res.raw_text


def test_extract_single_page(sample_pdf):
    res = extract_section_pages(sample_pdf, "one", 4, 4)
    assert "Chapter 1" in res.raw_text
    assert "Final preface page" not in res.raw_text


def test_extract_records_block_provenance(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 4, 5)
    pages = {b.page_num for b in res.blocks}
    assert pages == {4, 5}
    assert all(0 < b.page_num <= 12 for b in res.blocks)


def test_extract_page_height_recorded(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 4, 4)
    assert res.page_height > 700  # letter size 792
    assert res.page_width > 500


def test_extract_out_of_bounds_is_clamped_with_warning(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 11, 50)
    assert any("adjusted" in w for w in res.warnings)
    assert "Appendix conclusion" in res.raw_text


def test_extract_metadata_roundtrip(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 6, 6)
    meta = res.to_metadata()
    assert meta["section_id"] == "ch"
    assert meta["page_range"] == [6, 6]
    assert meta["page_height"] > 700
    assert isinstance(meta["blocks"], list) and meta["blocks"]
