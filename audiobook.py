#!/usr/bin/env python3
"""Manifest-driven PDF-to-audiobook generator.

Examples
--------
Validate a manifest without doing any work::

    python audiobook.py --pdf book.pdf --manifest book_manifest.json --validate-only

Generate everything and combine::

    python audiobook.py --pdf book.pdf --manifest book_manifest.json --output-dir output

Extract text only (no audio)::

    python audiobook.py --pdf book.pdf --manifest book_manifest.json --extract-only

Retry only the sections that failed previously::

    python audiobook.py --pdf book.pdf --manifest book_manifest.json --retry-failed

Rebuild the complete audiobook from existing section files::

    python audiobook.py --pdf book.pdf --manifest book_manifest.json --combine-only
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

# Make `src` importable when run as a script.
sys.path.insert(0, str(Path(__file__).resolve().parent))

from src.manifest import generate_template_manifest, load_manifest, validate_manifest  # noqa: E402
from src.pipeline.runner import PipelineRunner, RunConfig  # noqa: E402
from src.utils.logging_config import setup_logging  # noqa: E402

logger = logging.getLogger("audiobook")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="audiobook.py",
        description="Convert a PDF textbook into MP3 audiobooks using a JSON manifest.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    p.add_argument("--pdf", type=Path, help="Path to the source PDF.")
    p.add_argument("--manifest", type=Path, help="Path to the JSON manifest.")
    p.add_argument("--output-dir", type=Path, default=Path("output"), help="Output directory.")

    p.add_argument("--validate-only", action="store_true", help="Validate the manifest and PDF, then exit.")
    p.add_argument("--generate-template", type=Path, metavar="PATH",
                   help="Write a manifest template to PATH and exit.")
    p.add_argument("--extract-only", action="store_true", help="Extract raw text only (no cleaning/audio).")
    p.add_argument("--clean-only", action="store_true", help="Extract and clean text (no audio).")
    p.add_argument("--preview-cleaned", action="store_true",
                   help="Print the cleaned text for the selected section(s) and exit.")

    p.add_argument("--section", action="append", dest="sections", metavar="ID",
                   help="Process only this section id (repeatable).")
    p.add_argument("--retry-failed", action="store_true", help="Only process sections currently marked failed.")
    p.add_argument("--force", action="store_true", help="Ignore caches and regenerate everything.")

    p.add_argument("--engine", choices=["kokoro", "mock"], help="Override the manifest TTS engine.")
    p.add_argument("--voice", help="Override the manifest voice.")
    p.add_argument("--speed", type=float, help="Override the manifest speech speed.")

    p.add_argument("--combine", dest="combine", action="store_true", default=None,
                   help="Force full-book concatenation.")
    p.add_argument("--no-combine", dest="combine", action="store_false",
                   help="Disable full-book concatenation.")
    p.add_argument("--combine-only", action="store_true",
                   help="Combine existing section audio without regenerating it.")

    p.add_argument("--max-chunks", type=int, default=None,
                   help="Smoke-test limit: use at most N audio chunks per section.")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"], help="Console log level.")
    return p


def _print_report(report: dict) -> None:
    totals = report["totals"]
    print("\n=== Processing report ===")
    print(f"Book:      {report['book_title']}")
    print(f"Output:    {report['output_dir']}")
    print(f"Sections:  {totals['sections']} total, {totals['completed']} completed, "
          f"{totals['failed']} failed, {totals['skipped']} skipped")
    if report.get("complete_audiobook"):
        print(f"Audiobook: {report['complete_audiobook']}")
    print("\nPer section:")
    for s in report["sections"]:
        pages = f"{s['pages'][0]}-{s['pages'][1]}"
        status = s["status"]
        extra = ""
        if s.get("duration_seconds"):
            extra = f", {s['duration_seconds']:.1f}s"
        if s.get("error"):
            extra += f", error: {s['error']}"
        print(f"  - {s['id']:<20} pages {pages:<10} {status}{extra}")
    if report.get("extraction_warnings"):
        print("\nWarnings:")
        for w in report["extraction_warnings"]:
            print(f"  ! {w}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    if args.generate_template:
        out = generate_template_manifest(args.generate_template, args.pdf)
        print(f"Wrote manifest template to {out}")
        print("Edit it so that start_page/end_page match the physical PDF pages, then re-run with --manifest.")
        return 0

    if not args.pdf or not args.manifest:
        print("error: --pdf and --manifest are required (unless --generate-template is used)", file=sys.stderr)
        return 2

    # Validate + load manifest first so we can place logs in the book dir.
    manifest = load_manifest(args.manifest)
    from src.utils.files import safe_filename

    book_dir = args.output_dir / safe_filename(manifest.book.title or "book")
    setup_logging(book_dir / "logs", getattr(logging, args.log_level))

    try:
        import pymupdf as fitz
    except ImportError:  # pragma: no cover
        import fitz  # type: ignore

    if not args.pdf.exists():
        print(f"error: PDF not found: {args.pdf}", file=sys.stderr)
        return 2
    doc = fitz.open(args.pdf)
    try:
        page_count = doc.page_count
    finally:
        doc.close()

    errors, warnings = validate_manifest(manifest, page_count)
    for w in warnings:
        logger.warning(w)
    if errors:
        print("Manifest validation failed:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        return 1
    print(f"Manifest OK: {len(manifest.sections)} sections, PDF has {page_count} pages.")
    if args.validate_only:
        return 0

    stop_after = None
    if args.extract_only:
        stop_after = "extract"
    elif args.clean_only or args.preview_cleaned:
        stop_after = "clean"

    config = RunConfig(
        pdf_path=args.pdf,
        manifest_path=args.manifest,
        output_dir=args.output_dir,
        only_sections=args.sections,
        retry_failed=args.retry_failed,
        stop_after=stop_after,
        combine=args.combine,
        force=args.force,
        max_chunks_per_section=args.max_chunks,
        # Overrides are applied in memory; the manifest file is left untouched.
        tts_engine=args.engine,
        voice=args.voice,
        speed=args.speed,
    )

    runner = PipelineRunner(config)

    if args.preview_cleaned:
        runner.prepare()
        for section in manifest.sections:
            if not section.include:
                continue
            if args.sections and section.id not in args.sections:
                continue
            runner._process_section(section, max_stage=1)
            cleaned = runner._section_dir(section) / "cleaned.txt"
            print(f"\n----- {section.id} (cleaned preview) -----")
            print(cleaned.read_text(encoding="utf-8")[:4000])
        return 0

    if args.combine_only:
        runner.prepare()
        try:
            path = runner.combine_audiobook()
            print(f"Combined audiobook: {path}")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 1

    report = runner.run()
    _print_report(report)
    return 1 if report["totals"]["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
