# PDF to Audiobook Generator

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)
[![Python: 3.10 | 3.11 | 3.12](https://img.shields.io/badge/python-3.10%20%7C%203.11%20%7C%203.12-blue)](https://www.python.org/)
[![Tests: Passing](https://img.shields.io/badge/tests-87%20passed-brightgreen)](tests/)
[![TTS Engine: Kokoro-82M](https://img.shields.io/badge/TTS-Kokoro--82M-orange)](https://github.com/hexgrad/kokoro)
[![Contributions Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](CONTRIBUTING.md)

A deterministic, fully local pipeline that converts PDF textbooks, novels, and non-fiction books into chapterized MP3 audiobooks and combined full-length audiobooks.

```bash
./run.sh book.pdf book_manifest.json
```

One manifest, one command, fully local. PyMuPDF extracts the text, a conservative cleanup stage prepares narration, Kokoro-82M synthesizes natural speech, and FFmpeg encodes MP3s and concatenates them into `audiobooks/complete_audiobook.mp3`. No cloud services, no telemetry, no paid APIs.

---

## Key Features

- **100% Local and Private:** Runs entirely on your own machine. Zero network calls for synthesis, zero telemetry, and no paid API keys.
- **Fast Neural Synthesis:** Sustains ~21x faster than real-time synthesis on consumer GPUs (e.g. NVIDIA RTX 2050 4 GB). Synthesizes over 21 hours of audio in under an hour.
- **Authoritative Manifest Architecture:** Start and end pages are explicitly mapped to physical PDF pages. The runtime never guesses boundaries, never skips chapters unexpectedly, and never reorders content.
- **Universal Genre Support:** Built to withstand dense technical textbooks (stripping multi-line running headers, folios, and code artifacts) while voicing novels and self-help prose with natural cadence.
- **Resumable and Checkpointed:** Every pipeline stage is cached by content hash. If interrupted, re-running executes only uncompleted chunks without duplicate synthesis.
- **Clean Audio Assembly:** Produces individual high-quality MP3s per section as well as a single combined audiobook with configurable pauses between sections.

---

## Tested Books Showcase

This pipeline has been tested and verified across public domain classics, open-access literature, and freely licensed educational textbooks:

### Public Domain Fiction & Classics
- *The Great Gatsby* — F. Scott Fitzgerald
- *The Adventures of Sherlock Holmes* — Arthur Conan Doyle
- *Frankenstein* — Mary Shelley
- *Pride and Prejudice* — Jane Austen
- *The Time Machine* — H.G. Wells
- *Alice's Adventures in Wonderland* — Lewis Carroll

### Public Domain Philosophy & Essays
- *Meditations* — Marcus Aurelius
- *The Art of War* — Sun Tzu
- *Autobiography of Benjamin Franklin* — Benjamin Franklin
- *Self-Reliance and Other Essays* — Ralph Waldo Emerson
- *The Prince* — Niccolo Machiavelli

### Open-Access & Freely Licensed Textbooks
- *Operating Systems: Three Easy Pieces (OSTEP)* — Remzi & Andrea Arpaci-Dusseau (Open-access educational textbook; verified manifest included in repo)
- *Structure and Interpretation of Computer Programs (SICP)* — Harold Abelson & Gerald Jay Sussman (Creative Commons CC-BY-SA)
- *The Rust Programming Language* — Steve Klabnik & Carol Nichols (Open documentation / CC-BY-NC-SA)
- *Automate the Boring Stuff with Python* — Al Sweigart (Creative Commons CC-BY-NC-SA)

---

## Performance & Hardware Benchmarks

All metrics below were measured on actual hardware during a full end-to-end benchmark run (see [docs/VERIFICATION.md](docs/VERIFICATION.md)):

| Metric | Measured Value |
|---|---|
| GPU Tested | NVIDIA GeForce RTX 2050 (4096 MiB VRAM) |
| Peak VRAM Allocated | 1060 MiB |
| Peak Total GPU Memory Used | 2133 MiB (comfortably fits 4 GB cards) |
| Real-Time Factor (RTF) | 0.045 to 0.047 (~21x faster than real-time) |
| Benchmark Workload | Full technical textbook pilot (18 sections) |
| Pages Narrated | 495 physical pages |
| Audio Produced | 21.81 hours (1308.5 minutes) across 18 MP3s |
| Total Synthesis Time | 56.9 minutes (3413 seconds) |

---

## Quick Start

### 1. Requirements

- Linux (Ubuntu 22.04+ recommended)
- Python 3.10 to 3.12
- FFmpeg and ffprobe on `PATH`
- NVIDIA GPU with CUDA drivers (optional; `--engine mock` and test suite run without GPU)

### 2. Installation

```bash
git clone https://github.com/your-username/audiobook-generator.git
cd audiobook-generator

python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
sudo apt-get install ffmpeg          # ensure ffmpeg and ffprobe are on PATH
```

### 3. Run the Pipeline

```bash
./run.sh book.pdf book_manifest.json
```

By default, this command:
1. Validates the manifest and PDF structure.
2. Extracts raw text with physical page provenance.
3. Cleans running headers, footers, and formatting artifacts.
4. Prepares narration text and splits into sentence-bounded chunks.
5. Synthesizes audio using Kokoro-82M.
6. Encodes section MP3s and builds `audiobooks/complete_audiobook.mp3`.
7. Generates run state and processing report (`manifest.json` and `report.json`).

Output is placed in `output/<sanitized_book_title>/`.

---

## Generate the Manifest

The manifest is the only book-specific configuration file required.

### Option A: Using the Included Claude Skill

This repository includes a Claude skill designed to inspect PDFs and generate verified manifests:

```bash
# 1. Inspect the PDF with the skill in this repo
.claude/skills/pdf-audiobook-manifest/SKILL.md

# 2. Save the resulting JSON next to your PDF (e.g., book_manifest.json)

# 3. Run the pipeline
./run.sh book.pdf book_manifest.json
```

### Option B: Starter Template

Generate a starter template and fill in physical PDF page boundaries manually:

```bash
.venv/bin/python audiobook.py --pdf book.pdf --generate-template book_manifest.json
./run.sh book.pdf book_manifest.json --validate-only
```

---

## Supported Books & Formats

Any text-extractable PDF with structured sections (chapters, parts, introductions).

While engineered with the rigorous parsing needed to handle complex technical textbooks, **the pipeline works even better on non-technical books and novels**:

- **Novels & Literary Fiction:** Pure narrative prose flows straight into Kokoro with no formatting hurdles. You get natural sentence pacing, character dialogue cadence, and audiobook-grade quality right out of the box.
- **Self-Help, Business & Non-Fiction:** Clean chapter layouts make creating the manifest effortless. Bullet points, intros, and takeaways are converted into smooth conversational narration.
- **Technical & Engineering Textbooks:** Built-in cleanup strips running headers, multi-line folios, and footers, and lets you exclude indexes or reference lists cleanly via the manifest.

### Ideal Fits

- **Novels & Fiction:** classics, science fiction, fantasy, historical fiction
- **Self-Help & Non-Fiction:** personal growth, business, psychology, philosophy, biographies
- **Technical Textbooks:** computer science, software engineering, systems, algorithms, networking

The repo includes a complete verified manifest for *Operating Systems: Three Easy Pieces* (643 physical pages, 50 chapters).

Scanned pages are reported in `report.json` but not OCR'd. Unusual numbering belongs in `book.notes`.

---

## Pipeline Architecture

```text
Validate -> Extract -> Clean -> Speech Prep -> Chunk -> Kokoro TTS -> Section MP3 -> Combine -> Report
```

Every stage is cached by content hash. Re-running executes only what is strictly necessary.

---

## Audio Output Structure

```text
output/<Book_Title>/
  sections/<id>/
    raw.txt                            # raw extracted text
    cleaned.txt                        # normalized text
    speech.txt                         # narration-ready text
    chunks/                            # intermediate WAV chunks
    <id>.mp3                           # final section MP3
  audiobooks/
    complete_audiobook.mp3             # full combined audiobook
  manifest.json                        # run state with hashes
  report.json                          # processing metrics and durations
  logs/app.log                         # execution log
```

Run `./cleanup_output.sh` to prune temporary chunk files and stage texts while retaining the final MP3s, combined audiobook, and metadata.

---

## CLI Options & Workflow Control

### Rebuild Only the Combined Audiobook

If section MP3s already exist, rebuild the master audiobook without re-synthesizing:

```bash
./run.sh book.pdf book_manifest.json --combine-only
```

### Resuming and Retrying

```bash
./run.sh book.pdf book_manifest.json --retry-failed   # retry only failed sections
./run.sh book.pdf book_manifest.json --force          # rebuild all stages from scratch
```

### Partial Stages

```bash
./run.sh book.pdf book_manifest.json --validate-only   # check manifest + PDF then exit
./run.sh book.pdf book_manifest.json --extract-only    # stop after raw text extraction
./run.sh book.pdf book_manifest.json --clean-only      # stop after cleaning (no audio)
./run.sh book.pdf book_manifest.json --no-combine      # synthesize sections without combining
./run.sh book.pdf book_manifest.json --section chapter_01 --section chapter_02
```

### Output Cleanup

```bash
./cleanup_output.sh            # prune all output/* folders to audio + metadata
./cleanup_output.sh --dry-run  # preview pruned files first
```

---

## Manifest Specification

The manifest is versioned JSON. Minimal example:

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

### Settings Reference

| Setting | Default | Description |
|---|---|---|
| `tts_engine` | `kokoro` | Engine identifier (`kokoro` or `mock`) |
| `voice` | `af_heart` | Kokoro voice model id |
| `speed` | `1.0` | Narration speed multiplier |
| `audio_format` | `mp3` | Output audio format container |
| `combine_into_single_audiobook` | `true` | Whether to concatenate into a master audiobook |
| `keep_intermediate_files` | `true` | Retain raw texts and chunk WAVs |
| `inter_section_pause_ms` | `0` | Silence duration in milliseconds between sections |
| `code_block_policy` | `read` | `read`, `announce`, or `skip` |
| `pronunciation_file` | `null` | Path to pronunciation replacement rules JSON |

### Section Reference

| Field | Description |
|---|---|
| `id` | Unique alphanumeric slug used for filenames |
| `title` | Human-readable title for metadata and logging |
| `type` | Section type (`chapter`, `preface`, `appendix`, etc.) |
| `start_page` | Inclusive 1-based physical PDF start page |
| `end_page` | Inclusive 1-based physical PDF end page |
| `include` | Boolean flag; `false` skips synthesis while documenting range |
| `allow_overlap` | Explicit declaration for intentional page overlaps |

---

## Limitations

- **Plain PDF Code Blocks:** `code_block_policy` operates on markdown backticks and fences; plain PDF text contains neither unless monospace detection is implemented.
- **Scanned Documents:** Scanned pages are reported in `report.json` but not OCR'd. Use an OCR'd PDF source.
- **Page Numbering:** The manifest strictly expects physical PDF page indices, not printed pagination.
- **Model Download:** The initial Kokoro run downloads model weights (~330 MB) from Hugging Face.

For full schema details, see [docs/MANIFEST.md](docs/MANIFEST.md). For hardware setup, see [docs/INSTALL.md](docs/INSTALL.md).

---

## Project Layout

```text
audiobook.py                          CLI entry point
run.sh                                main runner script
cleanup_output.sh                     prune output/* to audio + metadata
pyproject.toml                        package metadata and build config
usage.md                              concise CLI usage guide
CONTRIBUTING.md                       contribution and development guide
CODE_OF_CONDUCT.md                    community guidelines
.claude/skills/pdf-audiobook-manifest/SKILL.md
                                      Claude skill for manifest generation
docs/MANIFEST.md                      manifest schema and rules
docs/INSTALL.md                       GPU and Kokoro setup
docs/VERIFICATION.md                  measured benchmarks and verification log
docs/pronunciation.example.json       example pronunciation rules file
src/manifest/schema.py                manifest dataclasses and validation
src/pdf/extractor.py                  PyMuPDF extraction with page provenance
src/text/cleanup.py                   conservative text normalization
src/speech/preprocess.py              narration text preparation
src/tts/base.py                       TTS adapter interface
src/tts/kokoro_engine.py              Kokoro-82M backend
src/tts/mock.py                       mock TTS backend for testing
src/audio/ffmpeg.py                   MP3 encoding, concatenation, and probing
src/pipeline/runner.py                pipeline orchestrator
src/pipeline/state.py                 run state, hashing, and report generation
tests/                                automated pytest test suite
```

---

## Contributing

Contributions are welcome. Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct, development setup, test suite, and how to submit pull requests and curated book manifests.

---

## License

This project is licensed under the MIT License. See [LICENSE](LICENSE) for details.
