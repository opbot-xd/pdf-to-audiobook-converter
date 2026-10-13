# PDF → Audiobook Generator

Turn a technical PDF textbook into a single combined MP3 audiobook, driven by a
**user-supplied JSON manifest** that describes the book’s structure.

This repo is the runtime. Manifest creation is separate: inspect the PDF with
the Claude skill in this repo, paste the resulting JSON, then run **one
command**.

```bash
./run.sh book.pdf book_manifest.json
```

Everything else is local: PyMuPDF for extraction, Kokoro-82M for neural TTS,
FFmpeg for encoding and concatenation. No paid APIs, no cloud services.

```text
Validate → Extract → Clean → Speech prep → Chunk → Kokoro TTS → MP3 per
section → combine → report
```

The manifest is authoritative. The tool never guesses chapter boundaries, never
silently skips sections, and never reorders content.

## The workflow

1. **Inspect the PDF with the Claude skill.**

   Open the skill `pdf-audiobook-manifest` from this repo and give it the PDF.
   It inspects the book structure and produces a verified manifest JSON using
   one-based physical PDF page indices. That is the only step that depends on
   Claude.

2. **Paste the manifest next to the PDF.**

   Save the JSON from the skill as e.g. `book_manifest.json` in the project
   root, or anywhere else you like. The manifest is the only file the runtime
   reads for structure, pages, and settings.

3. **Run one command.**

   ```bash
   ./run.sh path/to/book.pdf path/to/book_manifest.json
   ```

   That single command validates, extracts, cleans, synthesizes every included
   section, and builds the combined audiobook.

No manifest yet? The skill is the intended path. If you ever need a starting
template manually, generate one and validate it before full synthesis:

```bash
.venv/bin/python audiobook.py --pdf book.pdf --generate-template book_manifest.json
./run.sh book.pdf book_manifest.json --validate-only
```

## Quick start

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install ffmpeg          # ffmpeg + ffprobe on PATH

./run.sh book.pdf book_manifest.json
```

See [usage.md](usage.md) for the full workflow and CLI flags,
[docs/MANIFEST.md](docs/MANIFEST.md) for the manifest contract, and
[docs/INSTALL.md](docs/INSTALL.md) for GPU and Kokoro setup.

## What `./run.sh` actually needs from you

Only two things:

- the book PDF
- the manifest JSON

Everything else is derived. The output folder defaults to
`output/<sanitized book title>/`, taken from `book.title`. TTS engine, voice,
speed, audio format, and whether to combine into a single audiobook all come
from the manifest and can be overridden with flags.

By default, one command does this:

- validates the manifest and PDF
- extracts, cleans, and synthesizes every included section
- builds `audiobooks/complete_audiobook.mp3`
- writes the run-state `manifest.json` and the final `report.json`

## The manifest

A manifest is a normal JSON file. The shape is stable and versioned:

```json
{
  "schema_version": "1.0",
  "book": {
    "title": "Book Title",
    "source_pdf": "book.pdf",
    "language": "en",
    "page_index_base": 1,
    "notes": "optional notes about numbering, offsets, omissions, etc."
  },
  "settings": {
    "tts_engine": "kokoro",
    "voice": "af_heart",
    "speed": 1.0,
    "audio_format": "mp3",
    "combine_into_single_audiobook": true,
    "keep_intermediate_files": true
  },
  "sections": [
    {
      "id": "chapter_01",
      "title": "Chapter 1 — Actual Title",
      "type": "chapter",
      "start_page": 37,
      "end_page": 38,
      "include": true
    }
  ]
}
```

Important rules:

- `start_page` and `end_page` are **inclusive physical PDF page indices**,
  starting at 1 for the first page in the file.
- Never paste printed page numbers into the manifest unless they honestly equal
  the physical index.
- Section `id` values must be unique, lowercase, filesystem-safe ASCII using
  letters, digits, and underscores.
- `include: false` preserves a section in the manifest without narrating it.

The skill in this repo produces manifests that already follow this contract. If
you write manifests by hand, the schema doc is the reference.

## Output layout

```text
output/<Book_Title>/
  sections/<id>/
    raw.txt            # untouched extraction
    cleaned.txt        # conservative cleanup
    speech.txt         # narration-ready text
    chunks/            # TTS input chunks
    <id>.mp3           # final section audio
  audiobooks/
    complete_audiobook.mp3
  manifest.json        # run state: status + hashes per section
  report.json          # final processing report
  logs/app.log
```

After you run the cleanup script, each book folder becomes just:

- one MP3 per included section
- the combined audiobook
- `manifest.json` and `report.json`

## Rebuild only the combined audiobook

If all section MP3s already exist, you can rebuild just the single combined file
without any synthesis:

```bash
./run.sh book.pdf book_manifest.json --combine-only
```

`--combine-only` skips extraction, cleaning, and synthesis and only concatenates
the existing section MP3s. Re-running it is safe and idempotent.

## Resume, retry, and force

Work is cached by content hash, so re-running is a no-op for completed sections.

```bash
./run.sh book.pdf book_manifest.json --retry-failed   # redo failed sections only
./run.sh book.pdf book_manifest.json --force          # ignore caches and rebuild all
```

Useful partial-run flags:

```bash
./run.sh book.pdf book_manifest.json --validate-only   # check manifest + PDF, then exit
./run.sh book.pdf book_manifest.json --extract-only   # stop after raw text extraction
./run.sh book.pdf book_manifest.json --clean-only     # stop after cleaning (no audio)
./run.sh book.pdf book_manifest.json --no-combine     # do not build the combined file
./run.sh book.pdf book_manifest.json --section id1 --section id2
```

## Clean up the output

```bash
./cleanup_output.sh            # prune all output/* folders
./cleanup_output.sh --dry-run  # preview first
```

The cleanup script also removes the repo’s own Python caches
(`.pytest_cache` and `src/*/__pycache__`), but never the `.venv` install tree.

## Reproducing and testing

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pytest -q
```

The test suite mocks TTS, so it needs no GPU and no model download.

## Skill-first design

This repo splits the job in two on purpose:

- **Manifest creation** is the hard, book-specific part. That is where structure
  inspection, TOC mapping, and boundary verification happen. The Claude skill in
  `.claude/skills/pdf-audiobook-manifest/SKILL.md` is the documented way to do
  it for this pipeline.
- **Runtime synthesis** is the mechanical part. That is what `./run.sh` does.

That is why the runtime asks for only a PDF and a manifest, and why the skill
is part of the repo instead of living only in a chat session.

## Project layout

```text
audiobook.py                 CLI entry point
run.sh                       main runner: PDF + manifest in, audiobook out
cleanup_output.sh            prune output/* to audio + metadata
usage.md                     short usage guide
.claude/skills/pdf-audiobook-manifest/SKILL.md
                             Claude skill used to inspect PDFs and create manifests
docs/MANIFEST.md             manifest schema and rules
docs/INSTALL.md              GPU and Kokoro setup
docs/VERIFICATION.md         measured CLI and pipeline results
docs/pronunciation.example.json
                             example pronunciation rules file
src/manifest/schema.py       manifest dataclasses, validation, template
src/pdf/extractor.py         PyMuPDF extraction with page provenance
src/text/cleanup.py          conservative cleanup
src/speech/preprocess.py     narration text preparation
src/tts/base.py              TTS adapter interface
src/tts/kokoro_engine.py     Kokoro-82M backend
src/tts/mock.py              silent TTS for tests
src/audio/ffmpeg.py          MP3 encoding, concat, probing
src/pipeline/runner.py       orchestrator
src/pipeline/state.py        run state, hashes, report
tests/                       pytest suite
```

## License

MIT. See [LICENSE](LICENSE).
