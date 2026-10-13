from __future__ import annotations

from src.pdf.extractor import extract_section_pages
from src.text.cleanup import (
    CleanupConfig,
    cleanup_text,
    detect_headers_footers,
    join_wrapped_lines,
    normalize_whitespace,
    remove_standalone_page_numbers,
    repair_hyphenation,
    reflow_paragraphs,
)


def test_repair_hyphenation_joins_wrapped_word():
    assert repair_hyphenation("hyphen-\nation") == "hyphenation"


def test_repair_hyphenation_keeps_compound_caps():
    # 'non-' + 'Gaussian' should not be blindly joined
    assert repair_hyphenation("non-\nGaussian") == "non-\nGaussian"


def test_standalone_page_numbers_removed():
    text = "Some text\n42\nMore text"
    assert "42" not in remove_standalone_page_numbers(text)


def test_numbered_list_preserved():
    text = "1. First\n2. Second\n10. Tenth"
    out = remove_standalone_page_numbers(text)
    assert "1. First" in out and "10. Tenth" in out


def test_equation_numbers_preserved():
    text = "The result is shown in (3.4) below."
    assert remove_standalone_page_numbers(text) == text


def test_numbers_in_prose_preserved():
    text = "There are 42 apples and 7 oranges."
    assert remove_standalone_page_numbers(text) == text


def test_normalize_collapses_blanks():
    assert normalize_whitespace("a\n\n\n\nb   c") == "a\n\nb c"


def test_join_wrapped_lines_reflows_prose():
    assert join_wrapped_lines("a paragraph that\nwraps over") == "a paragraph that wraps over"


def test_join_wrapped_lines_keeps_list():
    out = join_wrapped_lines("A sentence\n1. item one\n2. item two")
    assert "1. item one" in out and "2. item two" in out


def test_reflow_preserves_code_block():
    text = "Intro line\n\n```python\ndef add(a, b):\n    return a + b\n```"
    out = reflow_paragraphs(text)
    assert "def add(a, b):" in out
    assert "    return a + b" in out


def test_detect_headers_from_blocks(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 1, 12)
    headers, footers = detect_headers_footers(res.blocks, res.page_height, CleanupConfig())
    assert "the test book" in headers


def test_cleanup_removes_running_header_and_footer(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 1, 12)
    cleaned, info = cleanup_text(
        res.raw_text, CleanupConfig(), blocks=res.blocks, page_height=res.page_height
    )
    assert "THE TEST BOOK" not in cleaned
    assert "detect_running_headers_footers" in info["applied"]


def test_cleanup_preserves_technical_content(sample_pdf):
    res = extract_section_pages(sample_pdf, "ch", 4, 8)
    cleaned, _ = cleanup_text(
        res.raw_text, CleanupConfig(), blocks=res.blocks, page_height=res.page_height
    )
    assert "E = mc^2" in cleaned
    assert "variable_name" in cleaned
    assert "def add(a, b):" in cleaned
    assert "[1]" in cleaned


def test_cleanup_hyphenation_end_to_end(sample_pdf):
    res = extract_section_pages(sample_pdf, "preface", 1, 3)
    cleaned, _ = cleanup_text(
        res.raw_text, CleanupConfig(), blocks=res.blocks, page_height=res.page_height
    )
    assert "hyphenation handling" in cleaned


# Mirrors the real layout of a two-line running head split across lines, as
# PyMuPDF emits it into the text stream.
HEAD_L1 = "CHAPTER 1"
HEAD_L2 = "Foo Bar"


def _folio_blocks(n_pages: int):
    """Synthetic blocks: a running header block carrying the folio plus a body
    block.  The header block text is '2\\nCHAPTER 1\\nFoo Bar\\n' -- the same
    shape PyMuPDF returns for a real running head."""
    from src.pdf.extractor import PageBlock

    blocks = []
    for p in range(1, n_pages + 1):
        blocks.append(PageBlock(0, p, f"{p}\n{HEAD_L1}\n{HEAD_L2}\n", (20.0, 25.9, 580.0, 35.0)))
        blocks.append(PageBlock(1, p, f"Body paragraph number {p} continues here.\n",
                                (60.0, 100.0, 580.0, 300.0)))
    return blocks


def _folio_text(n_pages: int) -> str:
    """The extracted text stream: folio, then the head split over two lines."""
    return "\n".join(
        line
        for p in range(1, n_pages + 1)
        for line in (str(p), HEAD_L1, HEAD_L2, f"Body paragraph number {p} continues here.")
    )


def test_normalise_furniture_ignores_leading_folio():
    from src.text.cleanup import _normalise_furniture

    assert _normalise_furniture("2\nCHAPTER 1 Foo Bar") == _normalise_furniture("CHAPTER 1 Foo Bar")
    assert _normalise_furniture("CHAPTER 1 Foo Bar\n12") == _normalise_furniture("CHAPTER 1 Foo Bar")
    assert _normalise_furniture("7") == ""
    assert _normalise_furniture("- 7 -") == ""


def test_running_header_spanning_lines_is_removed():
    """Regression (real book: 'C++ Concurrency in Action'): a running head that
    arrives as several lines, in a block that also carries the folio, must be
    removed.  Whole-line matching alone leaves it in every page."""
    blocks = _folio_blocks(6)
    cleaned, info = cleanup_text(_folio_text(6), CleanupConfig(), blocks=blocks, page_height=665.0)
    assert "CHAPTER 1" not in cleaned
    assert "Foo Bar" not in cleaned
    assert cleaned.count("Body paragraph number") == 6
    assert "remove_headers_footers" in " ".join(info["applied"])
    assert "chapter # foo bar" in info["detected_headers"]


def test_html_single_line_header_still_removed():
    """The one-line case must keep working after the multi-line fix."""
    from src.pdf.extractor import PageBlock

    blocks = [PageBlock(0, p, f"{p}\nTHE TEST BOOK\n", (20.0, 25.9, 580.0, 35.0)) for p in range(1, 5)]
    text = "\n".join(l for p in range(1, 5) for l in (str(p), "THE TEST BOOK", f"Body {p}."))
    cleaned, info = cleanup_text(text, CleanupConfig(), blocks=blocks, page_height=665.0)
    assert "THE TEST BOOK" not in cleaned
    assert "Body 1." in cleaned


def test_legitimate_heading_near_margin_is_kept():
    """A real section heading that never recurs must not be treated as furniture."""
    from src.pdf.extractor import PageBlock

    blocks = [
        PageBlock(0, 1, "1.2 Why concurrency matters\n", (60.0, 90.0, 580.0, 100.0)),
        PageBlock(1, 1, "Body\n", (60.0, 110.0, 580.0, 300.0)),
    ]
    text = "1.2 Why concurrency matters\n\nBody"
    cleaned, _ = cleanup_text(text, CleanupConfig(), blocks=blocks, page_height=665.0)
    assert "1.2 Why concurrency matters" in cleaned


def test_known_header_removal():
    text = "My Book Footer\nBody text"
    cleaned, _ = cleanup_text(text, CleanupConfig(known_headers=["My Book Footer"]))
    assert "My Book Footer" not in cleaned


def test_optional_toc_filter_off_by_default():
    text = "Introduction .......... 5\nBody"
    cleaned, info = cleanup_text(text, CleanupConfig())
    assert "Introduction .......... 5" in cleaned
    assert "strip_toc" not in info["applied"]

    cleaned2, info2 = cleanup_text(text, CleanupConfig(remove_toc=True))
    assert "Introduction .......... 5" not in cleaned2
    assert "strip_toc" in info2["applied"]
