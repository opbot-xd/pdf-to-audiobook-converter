# Verification log

Everything below was executed in the actual build environment, not estimated.

## Environment

| Item | Value |
|------|-------|
| OS | Linux (Ubuntu, kernel 6.x) |
| Python | 3.12.3 |
| FFmpeg / ffprobe | 6.1.1-3ubuntu5 |
| PyMuPDF | 1.28.2 |
| NumPy | 1.26.4 |
| PyTorch | 2.14.1+cu130 |
| Kokoro | 0.9.4 (`hexgrad/Kokoro-82M`) |
| GPU | NVIDIA GeForce RTX 2050, 4096 MiB, driver 580.178.04 |
| CUDA available | `True` — `torch.cuda.get_device_name(0) == "NVIDIA GeForce RTX 2050"` |

## Automated tests

```
$ pytest -q
87 passed
```

Covers manifest parsing/validation, inclusive one-based ranges, out-of-range
and overlapping sections, intentional gaps, section ordering, extraction and
empty pages, header/footer removal (including multi-line running heads that
carry the folio), numbered lists and equations, hyphenation, technical symbols
and code blocks, TTS chunking, cache invalidation (config *and* logic version),
resume, failure recovery, audio ordering and concatenation.

TTS is mocked, so these tests require no GPU and no model download.

## Kokoro backend

Raw API sanity check:

```
pipeline loaded in 29.3s
synthesized 3.55s audio in 4.50s
```

Through this project's adapter (`src/tts/kokoro_engine.py`):

```
$ python -c "...KokoroTTS().synthesize(text, out, voice='af_heart', speed=1.0)"
chunks: 1 total 5.72s
mp3 playable: True duration 5.784
```

### GPU memory and speed (measured on the RTX 2050, 4 GB)

Measured while synthesizing 55 s of speech in 2 chunks:

| Metric | Value |
|--------|-------|
| `torch.cuda.max_memory_allocated()` | **1060 MiB** |
| Peak total GPU memory used (system + process, `nvidia-smi`) | **2133 MiB** of 4096 MiB |
| Wall time | 8.5 s for 55 s of audio |
| Real-time factor | 0.15 |

That short run was dominated by model load/warmup. Measured again on a real
chapter (chapter 1 of *C++ Concurrency in Action*, 14 pages):

| Metric | Value |
|--------|-------|
| Audio produced | 2488 s (41.5 min) |
| Synthesis wall time | 118 s |
| **Real-time factor** | **0.047** |

So Kokoro-82M comfortably fits the 4 GB VRAM budget *with margin* on this
machine, and sustains ~21× faster than real time. The adapter still falls back
to CPU on CUDA OOM (`_generate_with_retry`), so the claim is not load-bearing.

## End-to-end CLI run (real Kokoro, GPU)

Full book — *C++ Concurrency in Action, 2nd Edition*, 18 included sections,
495 narrated pages:

```
$ .venv/bin/python audiobook.py \
    --pdf "C++ Concurrency in Action, 2nd Edition.pdf" \
    --manifest concurrency_manifest.json --output-dir output

Manifest OK: 20 sections, PDF has 530 pages.
```

Per-section audio produced (all 18 `audio_ready`, none empty or unreadable):

| Section | Duration | Section | Duration |
|---------|----------|---------|----------|
| preface | 2.9 min | chapter_08 | 141.4 min |
| acknowledgments | 2.2 min | chapter_09 | 67.8 min |
| about_this_book | 8.1 min | chapter_10 | 43.6 min |
| chapter_01 | 41.5 min | appendix_a | 71.5 min |
| chapter_02 | 52.8 min | appendix_b | 3.5 min |
| chapter_03 | 100.6 min | appendix_c | 29.1 min |
| chapter_04 | 105.7 min | appendix_d | 298.1 min |
| chapter_05 | 128.1 min | resources | 4.1 min |
| chapter_06 | 87.0 min | | |
| chapter_07 | 120.5 min | | |

**Total: 21.81 h of audio (1308.5 min) across 18 section MP3s.**

Every section MP3 was validated with `ffprobe` (non-zero duration, no
corrupt files). The `sections/` tree is 5.0 GB including the retained WAV
chunks.

Synthesis wall time for the 17 sections produced in this run was
**3413 s (56.9 min)** for 1267.1 min of audio → **real-time factor 0.045**,
consistent with the 0.047 measured for chapter 1 above.

The final step of a complete run is the concatenation into
`audiobooks/complete_audiobook.mp3`, which re-encodes the full 21.8 h of audio
and is consequently the longest single stage.

## Resume / cache verification

Measured on a small 3-section synthetic sample (used during development; the
sample PDF and manifest have since been removed from the repo). Re-running the
same command with no changes:

```
Sections:  3 total, 3 completed, 0 failed, 0 skipped
real 0m0.451s
```

0.45 s total, and PyTorch is never even imported (the TTS engine is built
lazily and no section needed synthesis). Cached chunks:

```
preface    cached chunks: 3
chapter_01 cached chunks: 7
appendix_a cached chunks: 2
```

Partial-run resume (`--section preface`, then a full run) synthesizes only the
missing sections and then builds the complete audiobook. On the real book the
same property holds: re-running after all sections are `audio_ready` performs
no synthesis and only redoes the final concatenation.

## CLI options exercised

| Command | Result |
|---------|--------|
| `--validate-only` | `Manifest OK: 20 sections, PDF has 530 pages.` exit 0 |
| `--generate-template` | wrote template, prompts for real ranges |
| `--extract-only` | `raw.txt` + `extraction.json` only; statuses `extracted` |
| `--clean-only` / `--preview-cleaned` | prints cleaned text |
| `--section preface` | 1 completed, combining skipped |
| `--retry-failed` | no-op when nothing failed |
| `--no-combine` / `--combine-only` | no combined file / combined from existing MP3s |
| `--engine mock` | full pipeline without GPU |
| overlap in manifest | reported, exit 1: `Overlapping ranges detected: preface(1-5) and chapter_01(4-8)` |

## Real-book fix (C++ Concurrency in Action, 530 pp)

The first pilot on a real book exposed a header-removal defect:

* The running head arrives as a **multi-line block that also carries the
  folio**: `"2\nCHAPTER 1\nHello, world of concurrency in C++!"`.
* Detection worked (the block sat in the top margin on 7 of 14 pages), but
  removal matched **whole single lines**, so the three-line head never matched
  the block-level key. The head survived in **7 of 14 pages**, interrupting
  paragraphs mid-sentence.

Fix (`src/text/cleanup.py`):

1. `_normalise_furniture` strips leading/trailing folio tokens, so
   `"2\nCHAPTER 1 Foo Bar"` and `"CHAPTER 1 Foo Bar"` collapse to one key.
2. `_remove_furniture_lines` matches **runs of consecutive lines** (longest
   first, up to 4) instead of single lines.

Result on the real book: `remove_headers_footers(7)`, header occurrences
7 → **0**, and the interrupted paragraph reflows correctly.
`CLEANUP_VERSION` / `SPEECH_VERSION` were added to the cache keys so a logic
change invalidates cached text instead of silently reusing stale output.

## Known limitations

* **`code_block_policy` is a no-op on plain PDFs.** `read`/`announce`/`skip`
  operate on Markdown code fences (```) and inline backticks. A PDF has
  neither: measured on chapter 1 of the real book, the cleaned text contains
  **0 fenced blocks and 0 backticks**, so `announce` removed nothing and code
  is narrated literally. Making this effective for PDFs needs font-based code
  detection (monospace span detection via `get_text("dict")`), which is not
  implemented.
* **Scanned pages.** Pages with no extractable text are reported in
  `report.json → extraction_warnings` (distinguishing empty pages from
  image-only pages) but are not OCR'd. Supply an OCR'd PDF or pre-process it.
* **Printed vs physical pages.** The manifest must use physical PDF page
  indices; the tool does not map printed page numbers to physical ones.
* **Tables.** ASCII/column-aligned tables are preserved as-is rather than
  converted to prose, which is the conservative choice but may read awkwardly.
* **First-run model download.** The first Kokoro call downloads the ~330 MB
  weights from Hugging Face. Set `HF_TOKEN` to avoid rate-limit warnings.
* **No OCR, no GPU requirement for tests.** Unit tests intentionally mock TTS.
