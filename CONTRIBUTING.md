# Contributing to PDF to Audiobook Generator

Thank you for your interest in contributing. This project aims to provide a reliable, local-first pipeline for turning PDFs (textbooks, novels, and non-fiction) into high-quality audiobooks with zero paid APIs.

## Core Design Principles

When contributing code or manifests, keep these core principles in mind:

1. **Local-first and private:** The pipeline must remain fully functional offline without external API keys or telemetry.
2. **Authoritative manifest:** Page boundaries, chapter orders, and section IDs are explicitly defined in the manifest. The runtime never guesses boundaries or reorders chapters.
3. **Conservative text processing:** Extraction and cleanup should remove artifacts (headers, footers, page numbers) without altering sentences, dropping punctuation, or corrupting prose.
4. **Resumable and cached:** All intermediate stages (extraction, cleanup, speech prep, synthesis chunks) are content-hashed. Interrupted runs must resume seamlessly without redundant work.

## Development Setup

### Prerequisites

- Linux (Ubuntu 22.04+ recommended)
- Python 3.10 to 3.12
- FFmpeg and ffprobe on `PATH`
- NVIDIA GPU with CUDA drivers (optional, for real Kokoro TTS; CPU and mock engine work without GPU)

### Initial Setup

```bash
git clone https://github.com/opbot-xd/pdf-to-audiobook-converter.git
cd pdf-to-audiobook-converter

python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

To install the neural TTS dependencies:

```bash
pip install torch kokoro
```

### Running Tests

The test suite mocks TTS, requiring no GPU and no neural model download:

```bash
pytest -q
```

To run with verbose output or targeted test files:

```bash
pytest tests/test_cleanup.py -v
```

## Contributing Book Manifests

Curated manifests for open-access textbooks, public domain classics, and popular titles are welcome additions.

When submitting a manifest:
1. Verify all start and end page numbers correspond to **physical PDF page indices** (1-indexed), not printed page numbers.
2. Ensure section IDs are unique, lowercase alphanumeric slugs (`chapter_01`, `preface`, `appendix_a`).
3. Set `include: false` for front-matter blanks, tables of contents, or index sections that should not be narrated.
4. Validate the manifest against the schema using:
   ```bash
   ./run.sh path/to/book.pdf path/to/manifest.json --validate-only
   ```

## Pull Request Guidelines

1. **Keep changes focused:** Avoid mixing refactoring, feature work, and manifest additions in a single pull request.
2. **Preserve test coverage:** Add tests for new text cleaning heuristics, CLI arguments, or manifest schema extensions.
3. **Verify idempotency:** Ensure that running `./run.sh` with `--combine-only` or re-running on completed sections performs zero redundant synthesis.
4. **Documentation:** Update `README.md`, `usage.md`, or relevant documentation in `docs/` whenever flags or behaviors change.
