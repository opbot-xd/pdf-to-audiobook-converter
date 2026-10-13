from __future__ import annotations

import hashlib
import re
from pathlib import Path
SAFE_CHARS_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_filename(name: str) -> str:
    name = name.strip().replace(" ", "_")
    name = SAFE_CHARS_RE.sub("_", name)
    # collapse multiple underscores
    name = re.sub(r"_+", "_", name)
    return name[:100]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def compute_text_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="replace")).hexdigest()
