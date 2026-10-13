#!/usr/bin/env bash
# Main runner for this audiobook pipeline.
#
# Usage:
#   ./run.sh <book.pdf> <manifest.json> [options]
#
# The only required inputs are the PDF and the JSON manifest. Everything else
# is derived: the output folder is named after the book title (sanitized),
# the TTS engine / voice / speed come from the manifest, and combining into a
# single audiobook defaults to on (from the manifest).
#
# Options:
#   --output-dir DIR          override output directory
#   --engine kokoro|mock      override TTS engine
#   --voice NAME              override voice
#   --speed N                 override speed
#   --no-combine             do not build the combined audiobook
#   --combine-only           ONLY rebuild the combined audiofile from existing
#                              section MP3s (no synthesis, no extraction)
#   --validate-only          validate manifest + PDF, then exit
#   --extract-only           stop after raw text extraction
#   --clean-only             stop after cleaning (no audio)
#   --section ID             process only this section (repeatable)
#   --retry-failed           only redo sections marked failed
#   --force                  ignore caches and regenerate everything
#   --max-chunks N           smoke-test limit on chunks per section
#   --log-level LEVEL        DEBUG|INFO|WARNING|ERROR (default INFO)
#
# Examples:
#   ./run.sh book.pdf book.json
#   ./run.sh book.pdf book.json --combine-only
#   ./run.sh book.pdf book.json --engine mock --no-combine --validate-only
#
# Safe and idempotent: re-running with the same inputs only does work that is
# actually needed (content-hash caching). Use --combine-only to rebuild the
# final audiobook without re-synthesizing sections.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

PY="${SCRIPT_DIR}/.venv/bin/python"

if [[ ! -f "$PY" ]]; then
  echo "error: Python entry point not found: $PY" >&2
  echo "Expected layout: .venv/bin/python inside this project." >&2
  echo "Create it with:  python3 -m venv .venv && .venv/bin/pip install -r requirements.txt" >&2
  exit 2
fi

# Verify PYTHONPATH behavior without adding to PATH: rely on audiobook.py's own
# `sys.path.insert(0, str(Path(__file__).resolve().parent))`.
CLI="audiobook.py"

usage() {
  cat <<'USAGEEOF'
Usage:
  ./run.sh <book.pdf> <manifest.json> [options]

The only required inputs are the PDF and the JSON manifest. Everything else
is derived: the output folder is named after the book title (sanitized),
the TTS engine / voice / speed come from the manifest, and combining into a
single audiobook defaults to on (from the manifest).

Options:
  --output-dir DIR          override output directory
  --engine kokoro|mock      override TTS engine
  --voice NAME              override voice
  --speed N                 override speed
  --no-combine             do not build the combined audiobook
  --combine-only           ONLY rebuild the combined audiofile from existing
                             section MP3s (no synthesis, no extraction)
  --validate-only          validate manifest + PDF, then exit
  --extract-only           stop after raw text extraction
  --clean-only             stop after cleaning (no audio)
  --section ID             process only this section (repeatable)
  --retry-failed           only redo sections marked failed
  --force                  ignore caches and regenerate everything
  --max-chunks N           smoke-test limit on chunks per section
  --log-level LEVEL        DEBUG|INFO|WARNING|ERROR (default INFO)

Examples:
  ./run.sh book.pdf book.json
  ./run.sh book.pdf book.json --combine-only
  ./run.sh book.pdf book.json --engine mock --no-combine --validate-only

Safe and idempotent: re-running with the same inputs only does work that is
actually needed (content-hash caching). Use --combine-only to rebuild the
final audiobook without re-synthesizing sections.

Run from the project root. PDF and manifest are positional and required.
USAGEEOF
  exit 0
}

POSITIONAL=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -h|--help) usage ;;
    --output-dir|--engine|--voice|--speed|--max-chunks|--log-level)
      POSITIONAL+=("$1" "$2"); shift 2 ;;
    --no-combine|--combine-only|--validate-only|--extract-only|--clean-only|--retry-failed|--force)
      POSITIONAL+=("$1"); shift ;;
    --section)
      POSITIONAL+=("--section" "$2"); shift 2 ;;
    *)
      # Anything that looks like a flag but isn't handled above still goes
      # through as a positional so the CLI can report it.
      if [[ "$1" == --* ]]; then
        POSITIONAL+=("$1")
        shift
      else
        POSITIONAL+=("$1")
        shift
      fi ;;
  esac
done

set -- "${POSITIONAL[@]}"

PDF=""
MANIFEST=""
EXTRA_ARGS=()

while [[ $# -gt 0 ]]; do
  case "$1" in
    --output-dir|--engine|--voice|--speed|--max-chunks|--log-level)
      EXTRA_ARGS+=("$1" "$2"); shift 2 ;;
    --section)
      EXTRA_ARGS+=("--section" "$2"); shift 2 ;;
    --no-combine|--combine-only|--validate-only|--extract-only|--clean-only|--retry-failed|--force)
      EXTRA_ARGS+=("$1"); shift ;;
    -*)
      echo "error: unrecognized option $1" >&2
      exit 2 ;;
    *)
      if [[ -z "$PDF" ]]; then
        PDF="$1"
      elif [[ -z "$MANIFEST" ]]; then
        MANIFEST="$1"
      else
        echo "error: unexpected positional argument $1" >&2
        exit 2
      fi
      shift ;;
  esac
done

if [[ -z "$PDF" ]]; then
  echo "error: missing book PDF. Usage: ./run.sh <book.pdf> <manifest.json> [options]" >&2
  exit 2
fi
if [[ -z "$MANIFEST" ]]; then
  echo "error: missing manifest JSON. Usage: ./run.sh <book.pdf> <manifest.json> [options]" >&2
  exit 2
fi
if [[ ! -f "$PDF" ]]; then
  echo "error: PDF not found: $PDF" >&2
  exit 2
fi
if [[ ! -f "$MANIFEST" ]]; then
  echo "error: manifest not found: $MANIFEST" >&2
  exit 2
fi

# Default output dir = output/<sanitized book title>
if [[ " ${EXTRA_ARGS[*]} " != *" --output-dir "* ]]; then
  # Derive the sanitized book title from the manifest so the default output
  # dir is deterministic; do it via a temp Python snippet so the shell string
  # is not mangled by quoting rules.
  py_title_script=$(mktemp)
  cat > "$py_title_script" <<'PYEOF'
import json
from pathlib import Path
import re
import sys
manifest_path = Path(sys.argv[1])
m = json.load(open(manifest_path))
title = m.get("book", {}).get("title") or "audiobook"
s = re.sub(r"[^A-Za-z0-9 _-]", "_", title or "")
print(re.sub(r"\s+", "_", s).strip(" _"))
PYEOF
  TITLE=$("$PY" "$py_title_script" "$MANIFEST")
  rm -f "$py_title_script"
  EXTRA_ARGS+=("--output-dir" "output/$TITLE")
fi

exec "$PY" "$CLI" \
  --pdf "$PDF" \
  --manifest "$MANIFEST" \
  "${EXTRA_ARGS[@]}"
