# PDF to Audiobook Generator

Turn a technical PDF textbook into a single combined MP3 audiobook.

```bash
./run.sh book.pdf book_manifest.json
```

One manifest, one command, fully local. PyMuPDF extracts the text, the cleanup
stage prepares narration, Kokoro-82M synthesizes speech, and FFmpeg encodes
MP3s and combines them into `audiobooks/complete_audiobook.mp3`. No cloud, no
paid APIs.

## Generate the manifest

The manifest is the only book-specific file. This repo ships a Claude skill for
creating it.

```bash
# 1. Inspect the PDF with the skill in this repo
.claude/skills/pdf-audiobook-manifest/SKILL.md

# 2. Paste the resulting JSON next to the PDF

# 3. Run it
./run.sh book.pdf book_manifest.json
```

Or generate a starter template and fill in the page ranges yourself:

```bash
.venv/bin/python audiobook.py --pdf book.pdf --generate-template book_manifest.json
./run.sh book.pdf book_manifest.json --validate-only
```

The manifest is authoritative. Page numbers are physical PDF pages, not printed
page numbers. The runtime never guesses boundaries or reorders content.

## Supported books

Text-extractable technical PDFs with a clear structure: preface, chapters,
appendices, references, glossary, index.

Good fits:

- computer science and software engineering textbooks
- operating systems, concurrency, distributed systems, networking
- programming languages and compilers
- algorithms and data structures
- systems books with numbered chapters and appendices

The repo includes a real manifest for *Operating Systems: Three Easy Pieces*,
643 physical pages, text-extractable, with front matter, 50 chapters, and an
index.

Scanned pages are reported but not OCR'd. Unusual numbering belongs in
`book.notes`.

## Run it

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install ffmpeg          # ffmpeg + ffprobe on PATH

./run.sh book.pdf book_manifest.json
```

By default one command:

- validates the manifest and PDF
- extracts, cleans, and synthesizes every included section
- builds `audiobooks/complete_audiobook.mp3`
- writes the run-state `manifest.json` and `report.json`

Output goes to `output/<sanitized book title>/`. TTS engine, voice, speed,
audio format, and combination all come from the manifest.

## Pipeline

```text
Validate → Extract → Clean → Speech prep → Chunk → Kokoro TTS → MP3 per
section → combine → report
```

Stages are cached by content hash. Re-running only does the work that is
actually needed.

## Audio output

```text
output/<Book_Title>/
  sections/<id>/<id>.mp3
  audiobooks/complete_audiobook.mp3
  manifest.json
  report.json
  logs/app.log
```

Run `./cleanup_output.sh` to reduce each book folder to the section MP3s, the
combined audiobook, and the metadata files.

## Rebuild only the combined file

```bash
./run.sh book.pdf book_manifest.json --combine-only
```

Skips extraction, cleaning, and synthesis. Only concatenates existing section
MP3s. Safe to re-run.

## Resume and retry

```bash
./run.sh book.pdf book_manifest.json --retry-failed   # redo failures only
./run.sh book.pdf book_manifest.json --force          # rebuild everything
```

Partial runs:

```bash
./run.sh book.pdf book_manifest.json --validate-only
./run.sh book.pdf book_manifest.json --extract-only
./run.sh book.pdf book_manifest.json --clean-only
./run.sh book.pdf book_manifest.json --no-combine
./run.sh book.pdf book_manifest.json --section chapter_01 --section chapter_02
```

## Clean up the output

```bash
./cleanup_output.sh            # prune all output/* folders
./cleanup_output.sh --dry-run  # preview first
```

Also removes the repo's Python caches (`.pytest_cache`, `src/*/__pycache__`),
never the `.venv` install tree.

## Requirements

- Python 3.10–3.12
- FFmpeg and ffprobe on PATH
- PyTorch and Kokoro for real speech; `--engine mock` and the tests run without them

Full setup, including GPU notes, is in [docs/INSTALL.md](docs/INSTALL.md).

## Manifest

Versioned JSON. Minimal example:

```json
{
  "schema_version": "1.0",
  "book": {
    "title": "Book Title",
    "source_pdf": "book.pdf",
    "language": "en",
    "page_index_base": 1,
    "notes": "optional notes"
  },
  "settings": {
    "tts_engine": "kokoro",
    "voice": "af_heart",
    "speed": 1.0,
    "audio_format": "mp3",
    "combine_into_single_audiobook": true,
    "keep_intermediate_files": true,
    "inter_section_pause_ms": 0,
    "code_block_policy": "read",
    "pronunciation_file": null
  },
  "sections": [
    {
      "id": "chapter_01",
      "title": "Chapter 1",
      "type": "chapter",
      "start_page": 37,
      "end_page": 38,
      "include": true
    }
  ]
}
```

### Settings table

| Setting | Default | Meaning |
|---------|---------|---------|
| `tts_engine` | `kokoro` | `kokoro` or `mock` |
| `voice` | `af_heart` | Kokoro voice id |
| `speed` | `1.0` | Speaking rate multiplier |
| `audio_format` | `mp3` | Output container |
| `combine_into_single_audiobook` | `true` | Also build the combined file |
| `keep_intermediate_files` | `true` | Keep chunks and stage JSONs |
| `inter_section_pause_ms` | `0` | Silence between sections when combining |
| `code_block_policy` | `read` | `read`, `announce`, or `skip` |
| `pronunciation_file` | `null` | Optional pronunciation rules file |

### Section table

| Field | Meaning |
|-------|---------|
| `id` | Unique slug; drives output filenames |
| `title` | Human-readable title |
| `type` | Section kind, e.g. `preface`, `chapter`, `appendix` |
| `start_page` | Inclusive first physical PDF page |
| `end_page` | Inclusive last physical PDF page |
| `include` | `false` skips the section |
| `allow_overlap` | Documents an intentional overlap |

Supported types are descriptive, not restrictive: `preface`, `foreword`,
`acknowledgments`, `introduction`, `chapter`, `section`, `appendix`,
`bibliography`, `references`, `resources`, `glossary`, `index`, or any custom
string.

## Limitations

- `code_block_policy` is a no-op on plain PDFs.
- Scanned pages are reported but not OCR'd.
- The manifest must use physical PDF page indices.
- The first Kokoro run downloads the model weights from Hugging Face.

For measured results, see [docs/VERIFICATION.md](docs/VERIFICATION.md). For the
full manifest contract, see [docs/MANIFEST.md](docs/MANIFEST.md).

## Layout

```text
audiobook.py                          CLI entry point
run.sh                                main runner
cleanup_output.sh                     prune output/* to audio + metadata
usage.md                              short usage guide
.claude/skills/pdf-audiobook-manifest/SKILL.md
                                      Claude skill for manifest creation
docs/MANIFEST.md                      manifest schema and rules
docs/INSTALL.md                       GPU and Kokoro setup
docs/VERIFICATION.md                  measured results
docs/pronunciation.example.json       example pronunciation rules file
src/manifest/schema.py                manifest dataclasses, validation, template
src/pdf/extractor.py                  PyMuPDF extraction
src/text/cleanup.py                   conservative cleanup
src/speech/preprocess.py              narration text preparation
src/tts/base.py                       TTS adapter interface
src/tts/kokoro_engine.py              Kokoro-82M backend
src/tts/mock.py                       silent TTS for tests
src/audio/ffmpeg.py                   MP3 encoding, concat, probing
src/pipeline/runner.py                orchestrator
src/pipeline/state.py                 run state, hashes, report
tests/                                pytest suite
```

## License

MIT. See [LICENSE](LICENSE).
