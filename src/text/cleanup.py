from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

logger = logging.getLogger(__name__)

# Bump when cleanup *logic* changes so cached cleaned.txt is invalidated even
# though the CleanupConfig itself is unchanged.
CLEANUP_VERSION = "2"

# ---- Patterns ---------------------------------------------------------------

STANDALONE_PAGE_NUMBER_RE = re.compile(r"^\s*[-–—]?\s*\d{1,4}\s*[-–—]?\s*$")
PAGE_OF_RE = re.compile(r"^\s*(page\s+)?\d{1,4}\s*(/|of)\s*\d{1,4}\s*$", re.IGNORECASE)

# Hyphen at end of line followed by lowercase continuation (very likely a
# wrapped word).  We require the next char to be a lower-case letter so we do
# not join things like "Fig. 3-" or "non-\nGaussian" too aggressively.
HYPHEN_LINE_END_RE = re.compile(r"([A-Za-z])-\s*\n\s*([a-z])")

# Reflowable paragraph enders: sentence terminators, list markers, etc.
SENTENCE_END_RE = re.compile(r"[.!?:;\"'\)\]]\s*$")
LIST_MARKER_RE = re.compile(r"^\s*(?:[-*•▪◦‣·]|\(?\d+[.)]|[a-zA-Z][.)])\s+")
HEADING_HINT_RE = re.compile(
    r"^\s*(?:chapter|section|part|appendix|figure|table|listing|example|theorem|lemma|definition|algorithm|"
    r"equation|eq\.?|ref\.?)\b",
    re.IGNORECASE,
)
CODE_HINT_RE = re.compile(
    r"(?:^|\s)(?:def |class |import |from |return |function |public |private |void |int |float |"
    r"printf|console\.log|#include|;\s*$|\{|\}|=>)",
)


@dataclass
class CleanupConfig:
    """Configuration for :func:`cleanup_text`.

    All destructive behaviour is opt-in; by default cleanup only normalises
    whitespace, repairs obvious hyphenation and removes page furniture that
    recurs across pages.
    """

    known_headers: List[str] = field(default_factory=list)
    known_footers: List[str] = field(default_factory=list)
    remove_toc: bool = False
    remove_bibliography: bool = False
    remove_index: bool = False
    remove_footnotes: bool = False
    repair_hyphenation: bool = True
    join_wrapped_lines: bool = True
    remove_page_numbers: bool = True
    remove_running_headers: bool = True
    # fraction of page height considered the header/footer margin band
    margin_ratio: float = 0.12
    # a header/footer must appear on at least this fraction of pages
    recurrence_threshold: float = 0.5
    # never treat a margin block longer than this as page furniture
    max_furniture_chars: int = 120


# ---- Basic normalisation ---------------------------------------------------


FENCE_RE = re.compile(r"^\s*```")


def _has_internal_spacing(line: str) -> bool:
    """True when a line carries deliberate whitespace (indentation or columns).

    A single wide gap is ambiguous and may just be extraction noise, so we
    require either leading indentation or *two* column-aligned gaps.
    """
    if line.startswith(("  ", "\t")):
        return True
    gaps = re.findall(r"(?<=\S)( {2,})(?=\S)", line)
    return len(gaps) >= 2


def _split_fenced(text: str) -> List[Tuple[bool, str]]:
    """Split text into ``(is_code, segment)`` parts around ``` fences."""
    segments: List[Tuple[bool, str]] = []
    current: List[str] = []
    in_code = False
    for line in text.split("\n"):
        if FENCE_RE.match(line):
            if current:
                segments.append((in_code, "\n".join(current)))
                current = []
            in_code = not in_code
            current.append(line)
            continue
        current.append(line)
    if current:
        segments.append((in_code, "\n".join(current)))
    return segments


def _normalise_prose_segment(seg: str) -> str:
    out: List[str] = []
    for line in seg.split("\n"):
        if _has_internal_spacing(line):
            # Preserve alignment (indented code, ASCII tables).
            out.append(line.rstrip())
        else:
            collapsed = re.sub(r"[ \t\f\v]+", " ", line).strip()
            out.append(collapsed)
    text = "\n".join(out)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip("\n")


def normalize_whitespace(text: str) -> str:
    """Collapse runs of spaces/tabs and excessive blank lines.

    Fenced code blocks keep their internal whitespace; other lines that carry
    deliberate spacing (indented code, tables) are only right-trimmed.
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    parts: List[str] = []
    for is_code, seg in _split_fenced(text):
        if is_code:
            seg = re.sub(r"[ \t]+$", "", seg, flags=re.MULTILINE)
            parts.append(re.sub(r"\n{3,}", "\n\n", seg).strip("\n"))
        else:
            parts.append(_normalise_prose_segment(seg))
    return "\n\n".join(p for p in parts if p.strip()).strip()


def repair_hyphenation(text: str) -> str:
    """Join words split across lines with a hyphen (conservatively)."""
    return HYPHEN_LINE_END_RE.sub(r"\1\2", text)


def _looks_like_page_number(line: str) -> bool:
    stripped = line.strip()
    if not stripped or len(stripped) > 8:
        return False
    if STANDALONE_PAGE_NUMBER_RE.match(stripped) or PAGE_OF_RE.match(stripped):
        # Reject things that are clearly list markers ("1.", "2)")
        if re.match(r"^\s*\d{1,4}[.)]\s*$", stripped):
            return False
        return True
    return False


def remove_standalone_page_numbers(text: str) -> str:
    """Remove lines that contain nothing but a page number.

    Only whole lines that are *only* a number (optionally wrapped in dashes or
    "Page N of M") are removed.  Numbers embedded in prose, numbered lists,
    equation numbers, code line numbers and references are preserved.
    """
    out: List[str] = []
    for line in text.splitlines():
        if _looks_like_page_number(line):
            continue
        out.append(line)
    return "\n".join(out)


# ---- Header / footer detection ---------------------------------------------


def detect_headers_footers(
    blocks: Sequence[Any],
    page_height: float,
    config: Optional[CleanupConfig] = None,
) -> Tuple[Set[str], Set[str]]:
    """Detect recurring header/footer text using block coordinates.

    ``blocks`` is a sequence of objects with ``text``, ``page_num`` and
    ``bbox`` attributes (see :class:`src.pdf.extractor.PageBlock`).  Returns
    ``(headers, footers)`` as sets of normalised strings.
    """
    if config is None:
        config = CleanupConfig()
    if not blocks or page_height <= 0:
        return set(), set()

    pages = sorted({getattr(b, "page_num", 0) for b in blocks})
    n_pages = max(1, len(pages))

    header_counts: Dict[str, Set[int]] = {}
    footer_counts: Dict[str, Set[int]] = {}

    for b in blocks:
        text = (getattr(b, "text", "") or "").strip()
        if not text or len(text) > config.max_furniture_chars:
            continue
        bbox = getattr(b, "bbox", None)
        if not bbox or len(bbox) < 4:
            continue
        y0, y1 = bbox[1], bbox[3]
        key = _normalise_furniture(text)
        if not key:
            continue
        if y1 <= page_height * config.margin_ratio:
            header_counts.setdefault(key, set()).add(b.page_num)
        elif y0 >= page_height * (1 - config.margin_ratio):
            footer_counts.setdefault(key, set()).add(b.page_num)

    def _recurring(counts: Dict[str, Set[int]]) -> Set[str]:
        threshold = max(2, int(n_pages * config.recurrence_threshold + 0.999))
        return {k for k, seen in counts.items() if len(seen) >= threshold}

    return _recurring(header_counts), _recurring(footer_counts)


def _normalise_furniture(text: str) -> str:
    """Normalise a candidate header/footer; page-number-only text maps to ''.

    A detected header *block* often contains the folio as well as the running
    title (``"12 CHAPTER 1 Foo"``), whereas the matching line in the extracted
    body text is just ``"CHAPTER 1 Foo"`` (the folio is a separate line that
    gets dropped as a standalone page number).  Folding digits to ``#`` is not
    enough on its own, so leading/trailing page-number tokens are stripped too
    and both sides collapse to one key.
    """
    text = re.sub(r"\s+", " ", text).strip()
    # Strip digits so "Chapter 3" and "Chapter 4" collapse, but keep the words.
    text = re.sub(r"\d+", "#", text)
    # Drop leading/trailing folio tokens ("# ", "# - ", "- # -", ...).
    text = re.sub(r"^(?:[#\u2013\u2014-]+\s*)+", "", text)
    text = re.sub(r"(?:\s*[#\u2013\u2014-]+)+$", "", text)
    text = text.strip()
    if text in {"", "#"}:
        return ""
    if HEADING_HINT_RE.match(text) and text.lower().startswith("chapter"):
        # running chapter titles are legitimate furniture
        return text.lower()
    return text.lower()


# ---- Optional content filters ----------------------------------------------


def _remove_furniture_lines(text: str, furniture: Set[str], max_span: int = 4) -> Tuple[str, int]:
    """Remove recurring header/footer blocks from ``text``.

    A detected furniture item is a *block* and may span several lines once it
    reaches the text stream (PyMuPDF emits ``"2\\nCHAPTER 1\\nHello, world"``
    as three lines).  So match runs of consecutive lines, longest first, rather
    than single lines.
    """
    lines = text.splitlines()
    kept: List[str] = []
    removed = 0
    i = 0
    while i < len(lines):
        matched_span = 0
        upper = min(max_span, len(lines) - i)
        for span in range(upper, 0, -1):
            chunk = lines[i : i + span]
            if not any(c.strip() for c in chunk):
                continue
            key = _normalise_furniture("\n".join(chunk))
            if key and key in furniture:
                matched_span = span
                break
        if matched_span:
            removed += 1
            i += matched_span
        else:
            kept.append(lines[i])
            i += 1
    if not removed:
        return text, 0
    return "\n".join(kept), removed


def strip_footnotes(text: str) -> str:
    """Remove blocks that look like footnotes (superscript markers + leading *)."""
    out = []
    for line in text.splitlines():
        if re.match(r"^\s*[*†‡]\s+\S", line) and len(line) < 200:
            continue
        out.append(line)
    return "\n".join(out)


def strip_bibliography(text: str) -> str:
    """Remove a trailing bibliography/references section, if clearly marked."""
    m = re.search(r"\n\s*(references|bibliography)\s*\n", text, re.IGNORECASE)
    if not m:
        return text
    return text[: m.start()].rstrip()


def strip_index(text: str) -> str:
    m = re.search(r"\n\s*index\s*\n", text, re.IGNORECASE)
    if not m:
        return text
    return text[: m.start()].rstrip()


def strip_toc(text: str) -> str:
    """Remove lines that look like table-of-contents entries."""
    out = []
    for line in text.splitlines():
        if re.search(r"\.{3,}\s*\d{1,4}\s*$", line):
            continue
        out.append(line)
    return "\n".join(out)


# ---- Paragraph reflow -------------------------------------------------------


def _is_paragraph_break(prev: str, cur: str) -> bool:
    if LIST_MARKER_RE.match(cur):
        return True
    if HEADING_HINT_RE.match(cur):
        return True
    if not prev.strip():
        return True
    return False


def join_wrapped_lines(paragraph: str) -> str:
    """Join single newlines inside a paragraph into spaces.

    Paragraphs are separated by blank lines, so this only reflows wrapped
    prose.  List items and headings keep their own line.
    """
    lines = [ln.rstrip() for ln in paragraph.split("\n")]
    out: List[str] = []
    for ln in lines:
        if not out:
            out.append(ln)
            continue
        prev = out[-1]
        if (
            prev.strip()
            and ln.strip()
            and not _is_paragraph_break(prev, ln)
            and not SENTENCE_END_RE.search(prev)
            and not LIST_MARKER_RE.match(ln)
        ):
            out[-1] = prev + " " + ln.strip()
        else:
            out.append(ln)
    return "\n".join(out)


def _looks_like_code(paragraph: str) -> bool:
    if paragraph.startswith("```") or paragraph.endswith("```"):
        return True
    lines = [l for l in paragraph.splitlines() if l.strip()]
    if len(lines) < 2:
        return False
    codey = sum(1 for l in lines if CODE_HINT_RE.search(l) or l.startswith(("    ", "\t")))
    return codey >= max(2, len(lines) // 2)


def _looks_tabular(paragraph: str) -> bool:
    """True when the paragraph holds column-aligned data we must not reflow."""
    return any(_has_internal_spacing(line) for line in paragraph.splitlines() if line.strip())


def reflow_paragraphs(text: str, config: Optional[CleanupConfig] = None) -> str:
    """Reflow wrapped lines while keeping code blocks and lists intact."""
    if config is None:
        config = CleanupConfig()
    parts = re.split(r"\n\s*\n", text)
    out: List[str] = []
    in_fence = False
    for part in parts:
        stripped = part.strip("\n")
        if not stripped.strip():
            continue
        is_fence = stripped.lstrip().startswith("```")
        if in_fence or is_fence:
            out.append(stripped)
            if stripped.count("```") % 2 == 1:
                in_fence = not in_fence
            continue
        if _looks_like_code(stripped) or _looks_tabular(stripped):
            out.append(stripped)
            continue
        out.append(join_wrapped_lines(stripped))
    return "\n\n".join(out)


# ---- Top level --------------------------------------------------------------


def cleanup_text(
    raw_text: str,
    config: Optional[CleanupConfig] = None,
    blocks: Optional[Sequence[Any]] = None,
    page_height: float = 0.0,
) -> Tuple[str, Dict[str, Any]]:
    """Clean extracted text and return ``(cleaned_text, info)``.

    ``info`` records what was applied so a run can be reproduced and audited.
    """
    if config is None:
        config = CleanupConfig()

    info: Dict[str, Any] = {"applied": []}
    text = raw_text

    headers: Set[str] = {_normalise_furniture(h) for h in config.known_headers}
    footers: Set[str] = {_normalise_furniture(f) for f in config.known_footers}
    headers.discard("")
    footers.discard("")

    if config.remove_running_headers and blocks and page_height > 0:
        det_h, det_f = detect_headers_footers(blocks, page_height, config)
        if det_h or det_f:
            info["detected_headers"] = sorted(det_h)
            info["detected_footers"] = sorted(det_f)
            info["applied"].append("detect_running_headers_footers")
        headers |= det_h
        footers |= det_f

    if headers or footers:
        text, removed = _remove_furniture_lines(text, headers | footers)
        if removed:
            info["applied"].append(f"remove_headers_footers({removed})")

    if config.remove_page_numbers:
        before = text
        text = remove_standalone_page_numbers(text)
        if text != before:
            info["applied"].append("remove_standalone_page_numbers")

    # Optional content filters run on line-structured text, before reflow.
    if config.remove_toc:
        text = strip_toc(text)
        info["applied"].append("strip_toc")
    if config.remove_footnotes:
        text = strip_footnotes(text)
        info["applied"].append("strip_footnotes")
    if config.remove_bibliography:
        text = strip_bibliography(text)
        info["applied"].append("strip_bibliography")
    if config.remove_index:
        text = strip_index(text)
        info["applied"].append("strip_index")

    if config.repair_hyphenation:
        before = text
        text = repair_hyphenation(text)
        if text != before:
            info["applied"].append("repair_hyphenation")

    if config.join_wrapped_lines:
        before = text
        text = reflow_paragraphs(text, config)
        if text != before:
            info["applied"].append("reflow_paragraphs")

    text = normalize_whitespace(text)
    return text, info
