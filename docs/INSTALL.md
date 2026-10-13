# Installation

## Requirements

| Component | Notes |
|-----------|-------|
| Python    | 3.10 – 3.12 (tested on 3.12.3) |
| FFmpeg    | `ffmpeg` **and** `ffprobe` on `PATH` (tested with 6.1.1) |
| PyMuPDF   | Installed from `requirements.txt` (tested with 1.28.2) |
| PyTorch   | Required only for the real Kokoro backend |
| Kokoro    | `pip install kokoro` (the `hexgrad/Kokoro-82M` inference package) |
| GPU       | Optional. Kokoro runs on CPU; an NVIDIA RTX 2050 (4 GB) is enough |

No paid API or cloud service is required at any point.

## 1. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
python -m pip install --upgrade pip
```

## 2. Install the core dependencies

```bash
pip install -r requirements.txt
```

Or install just what the non-TTS pipeline needs:

```bash
pip install pymupdf "numpy<2" soundfile pytest
```

## 3. Install FFmpeg

```bash
# Debian/Ubuntu
sudo apt-get install ffmpeg
# macOS
brew install ffmpeg
# Windows (winget)
winget install Gyan.FFmpeg
```

Verify:

```bash
ffmpeg -version | head -1
ffprobe -version | head -1
```

## 4. (Optional) Install the Kokoro backend

```bash
pip install torch kokoro
```

Notes:

* PyTorch from PyPI ships CUDA-enabled wheels on Linux/Windows x86-64. If your
  driver is too old, install the matching wheel from
  <https://pytorch.org/get-started/locally/> instead.
* The first Kokoro run downloads the ~330 MB `hexgrad/Kokoro-82M` weights into
  the Hugging Face cache (`~/.cache/huggingface`).
* Kokoro-82M weights are Apache-2.0 licensed; see
  <https://huggingface.co/hexgrad/Kokoro-82M>.

Verify the backend independently:

```bash
python -c "
from kokoro import KPipeline
import numpy as np, soundfile as sf
p = KPipeline(lang_code='a')
audio = np.concatenate([np.asarray(a) for _, _, a in p('Hello world.', voice='af_heart', speed=1.0, split_pattern=r'\n+')])
sf.write('/tmp/kokoro_check.wav', audio, 24000)
print('wrote /tmp/kokoro_check.wav', len(audio) / 24000, 'seconds')
"
```

## 5. Verify the installation

```bash
pytest -q
```

The test suite mocks TTS, so it needs no GPU and no model download. Only the
`kokoro` package/weights are optional.

To exercise the full pipeline without the GPU, run any manifest with the silent
mock engine:

```bash
python audiobook.py --pdf book.pdf --manifest book_manifest.json \
  --output-dir output --engine mock
```

## GPU / VRAM notes

Kokoro-82M is small (82 M parameters). Inference is sequential and chunked, so
VRAM use stays bounded regardless of book length. A 4 GB RTX 2050 is
comfortable; the adapter still falls back to CPU if a CUDA OOM occurs (see
`src/tts/kokoro_engine.py::_generate_with_retry`).

Measured on an RTX 2050 (4096 MiB) while synthesizing 55 s of speech:

| Metric | Value |
|--------|-------|
| `torch.cuda.max_memory_allocated()` | 1060 MiB |
| Peak total GPU memory used (`nvidia-smi`) | 2133 MiB |
| Real-time factor | 0.15 (55 s audio in 8.5 s) |

Reproduce with `docs/VERIFICATION.md`.

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `ffmpeg: command not found` | Install FFmpeg (step 3). |
| `KokoroUnavailableError: The 'kokoro' package is not installed` | `pip install kokoro torch`, or run with `--engine mock`. |
| `CUDA out of memory` | Handled automatically (falls back to CPU). Close other GPU apps to stay on GPU. |
| Garbled/empty extraction for a page range | The PDF pages are probably scanned images. Check `report.json` → `extraction_warnings`. |
