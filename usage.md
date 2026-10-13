# Usage

Turn a PDF book into MP3s, driven by a JSON manifest that defines the sections.
Everything runs locally: PyMuPDF for extraction, Kokoro-82M for TTS, FFmpeg for
encoding. No cloud, no paid APIs.

## Setup

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install ffmpeg          # needs ffmpeg + ffprobe on PATH
pip install torch kokoro             # GPU backend (optional; --engine mock works without it)
```

## Run

The entry point is `./run.sh`. The only inputs you must provide are the PDF and
the manifest; everything else is derived from them.

```bash
./run.sh "C++ Concurrency in Action, 2nd Edition.pdf" concurrency_manifest.json
```

By default that:

- validates the manifest + PDF
- extracts, cleans and synthesizes every included section
- builds `audiobooks/complete_audiobook.mp3`
- writes `manifest.json` and `report.json`

The output folder defaults to `output/<sanitized book title>/`, taken from the
manifest's `book.title`. TTS engine, voice, speed, combine setting and so on all
come from the manifest and can be overridden with flags.

No manifest yet? Generate a template and fill in the page ranges yourself:

```bash
.venv/bin/python audiobook.py --pdf book.pdf --generate-template book_manifest.json
./run.sh book.pdf book_manifest.json --validate-only
```

Then run:

```bash
./run.sh book.pdf book_manifest.json --validate-only
```

The manifest is authoritative — the tool never guesses or reorders boundaries.
See [`docs/MANIFEST.md`](docs/MANIFEST.md) for its schema.

## Only rebuild the compiled audiobook

If all the section MP3s already exist (from a previous run or after cleanup), you
can rebuild just the single combined file without doing any synthesis:

```bash
./run.sh "C++ Concurrency in Action, 2nd Edition.pdf" concurrency_manifest.json --combine-only
```

`--combine-only` skips extraction, cleaning and synthesis and only concatenates
the existing section MP3s into `audiobooks/complete_audiobook.mp3`. It is also
what you use to fix a missing or stale combine after a clean, a crash or a manual
edit — re-running the same command is safe and idempotent.

## Output

```
output/<Book_Title>/
  sections/<id>/<id>.mp3        # one MP3 per section
  audiobooks/complete_audiobook.mp3
  manifest.json                 # per-section status + hashes
  report.json                   # final summary (durations, warnings)
  logs/app.log                  # (kept until you run cleanup_output.sh)
```

After you run `./cleanup_output.sh`, the `output/<Book_Title>/` folder becomes
just the section MP3s, the combined audiobook, `manifest.json` and `report.json`.

## Common flags

`run.sh` forwards these straight through to the pipeline; most of them override
the manifest in memory without touching the manifest file on disk.

| Flag | Purpose |
|------|---------|
| `--combine-only` | Only reassemble the compiled audiobook from existing section MP3s. |
| `--no-combine` | Do not build the combined audiobook at all. |
| `--validate-only` | Check manifest + PDF, then exit. |
| `--extract-only` | Stop after raw text extraction. |
| `--clean-only` / `--preview-cleaned` | Stop after cleaning (no audio). |
| `--section ID` | Process only this section (repeatable). |
| `--retry-failed` | Redo only sections marked `failed`. |
| `--force` | Ignore caches and regenerate everything. |
| `--engine {kokoro,mock}` | Override the manifest TTS engine. |
| `--voice NAME` / `--speed N` | Override the manifest voice / speed. |
| `--output-dir DIR` | Override the default `output/<title>/` folder. |
| `--max-chunks N` | Smoke-test limit on chunks per section. |
| `--log-level LEVEL` | `DEBUG`, `INFO`, `WARNING` or `ERROR` (default `INFO`). |

Run `./run.sh --help` for the full list and examples.

## Reruns

Work is cached by content hash, so re-running is a no-op for completed sections.
`--retry-failed` redoes only failures; `--force` rebuilds everything.

## Clean up the output

```bash
./cleanup_output.sh          # prune all output/* folders
./cleanup_output.sh --dry-run   # preview first
```

Keeps, per book folder: one MP3 per section, the combined audiobook, `manifest.json`
and `report.json`. Removes everything else: raw/cleaned/speech text, stage JSONs,
audio chunks, logs, and project-level Python caches (`.pytest_cache`, `src/*/__pycache__`).

## Verify

```bash
pytest -q
```

Tests mock TTS, so they need no GPU and no model download. See
[`docs/INSTALL.md`](docs/INSTALL.md) for GPU notes and
[`docs/VERIFICATION.md`](docs/VERIFICATION.md) for measured results.
