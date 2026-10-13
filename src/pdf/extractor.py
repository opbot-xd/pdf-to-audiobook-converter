from __future__ import annotations

import logging
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

try:  # PyMuPDF >= 1.24 exposes the modern name
    import pymupdf as fitz
    fitz  # noqa: B018
    pymupdf = True
except ImportError:  # pragma: no cover - fallback for older PyMuPDF
    import fitz  # type: ignore

    pymupdf = False

logger = logging.getLogger(__name__)


@dataclass
class PageBlock:
    block_id: int
    page_num: int  # physical page number (1-based as in PDF)
    text: str
    bbox: Tuple[float, float, float, float]


@dataclass
class ExtractionResult:
    section_id: str
    raw_text: str
    blocks: List[PageBlock]
    warnings: List[str]
    page_range: Tuple[int, int]
    page_height: float = 0.0
    page_width: float = 0.0
    empty_pages: List[int] = field(default_factory=list)
    image_only_pages: List[int] = field(default_factory=list)
    metadata_path: Path | None = None

    def to_metadata(self) -> Dict[str, Any]:
        return {
            "section_id": self.section_id,
            "page_range": list(self.page_range),
            "page_height": self.page_height,
            "page_width": self.page_width,
            "empty_pages": self.empty_pages,
            "image_only_pages": self.image_only_pages,
            "blocks": [asdict(b) for b in self.blocks],
            "warnings": self.warnings,
        }


def extract_section_pages(
    pdf_path: Path,
    section_id: str,
    start_page: int,
    end_page: int,
    page_index_base: int = 1,
) -> ExtractionResult:
    """Extract inclusive pages [start_page, end_page] (1-based physical indices by default).
    PyMuPDF uses 0-based page numbers; convert accordingly.
    """
    pdf_path = Path(pdf_path)
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    doc = fitz.open(pdf_path)
    try:
        page_count = doc.page_count
        warnings: List[str] = []

        # Determine 0-based start/end. Assume start_page/end_page are 1-based physical indices.
        if page_index_base == 0:
            start = start_page
            end = end_page
        else:
            start = start_page - 1
            end = end_page - 1

        if start < 0:
            start = 0
            warnings.append("start_page adjusted to 0-based bounds")
        if end >= page_count:
            end = page_count - 1
            warnings.append("end_page adjusted to PDF bounds (truncated)")

        blocks: List[PageBlock] = []
        text_parts: List[str] = []
        heights: List[float] = []
        widths: List[float] = []
        empty_pages: List[int] = []
        image_only_pages: List[int] = []

        for i in range(start, end + 1):
            page = doc[i]
            page_num = i + 1  # 1-based physical
            rect = page.rect
            heights.append(float(rect.height))
            widths.append(float(rect.width))
            page_text = page.get_text("text") or ""
            # Check for empty/scanned-like: if no text and has images, note it
            if not page_text.strip():
                img_list = page.get_images(full=True)
                if img_list:
                    image_only_pages.append(page_num)
                    warnings.append(f"Page {page_num} appears empty of extractable text but contains images (possibly scanned)")
                else:
                    empty_pages.append(page_num)
                    warnings.append(f"Page {page_num} is empty (no text, no images detected)")
            # Also store blocks if available
            text_blocks = page.get_text("blocks")  # list of (x0,y0,x1,y1,text,block_no,...)
            for blk in text_blocks:
                b = PageBlock(
                    block_id=blk[5] if len(blk) > 5 else -1,
                    page_num=page_num,
                    text=blk[4] or "",
                    bbox=(blk[0], blk[1], blk[2], blk[3]),
                )
                blocks.append(b)
            if page_text:
                text_parts.append(page_text.rstrip() + "\n\n")

        raw_text = "".join(text_parts).strip()
        return ExtractionResult(
            section_id=section_id,
            raw_text=raw_text,
            blocks=blocks,
            warnings=warnings,
            page_range=(start_page, end_page),
            page_height=max(heights) if heights else 0.0,
            page_width=max(widths) if widths else 0.0,
            empty_pages=empty_pages,
            image_only_pages=image_only_pages,
        )
    finally:
        doc.close()
