#!/usr/bin/env bash
# Clean up every book output in output/*. Keep only the audio that can be played.
#
# Per book folder, keeps:
#   - one MP3 per section  (sections/<id>/<id>.mp3)
#   - the full audiobook  (audiobooks/complete_audiobook.mp3)
#   - run metadata        (manifest.json, report.json)
#
# Per book folder, removes:
#   - per-section raw/cleaned/speech text (.txt)
#   - per-section stage JSONs        (extraction.json, cleanup.json, speech.json)
#   - per-section audio chunks       (sections/<id>/chunks/)
#   - logs                          (logs/)
#   - empty section dirs that remain
#
# Also removes the repo's own Python caches:
#   .pytest_cache/ and ./src,./tests **/__pycache__/
# (never the .venv install tree)
#
# Safe / idempotent: re-running after a clean does nothing.
# Pass --dry-run to preview what would be deleted.
#
# Run from the project root.
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

DRY=false
for arg in "$@"; do
  case "$arg" in
    --dry-run) DRY=true ;;
    *) echo "unknown option: $arg" >&2; exit 2 ;;
  esac
done

OUTPUT_DIR="output"
if [[ ! -d "$OUTPUT_DIR" ]]; then
  echo "nothing to clean: $OUTPUT_DIR not found" >&2
  exit 0
fi

COUNT_FILES=0
COUNT_DIRS=0
BYTES=0

removed() {
  local path="$1"
  if [[ ! -e "$path" ]]; then
    return
  fi
  local size
  size=$(du -bs "$path" 2>/dev/null | cut -f1)
  if [[ -n "$size" && "$size" != "0" ]]; then
    BYTES=$((BYTES + size))
  fi
  if [[ "$DRY" == true ]]; then
    printf "  [DRY-RUN] would remove: %s\n" "$path"
  else
    rm -rf "$path"
    printf "  removed: %s\n" "$path"
  fi
  COUNT_FILES=$((COUNT_FILES + 1))
}

# ---- per-book cleanup -------------------------------------------------
books=()
for book_dir in "$OUTPUT_DIR"/*/; do
  [[ -d "$book_dir" ]] || continue
  books+=("$book_dir")
done

if [[ ${#books[@]} -eq 0 ]]; then
  echo "nothing to clean: no book folders under $OUTPUT_DIR"
  echo ""
  echo "Project caches skipped (handled last)."
  exit 0
fi

for book_dir in "${books[@]}"; do
  bd="${book_dir%/}"
  book_name="$(basename "$bd")"
  echo ""
  echo "==> Cleaning book: $book_name ($bd)"

  echo "   Cleaning sections (keep MP3s, remove .txt / *.json / chunks)"
  for sec_dir in "$bd/sections"/*/; do
    [[ -d "$sec_dir" ]] || continue
    for txt in "$sec_dir"/*.txt; do
      [[ -f "$txt" ]] || continue
      removed "$txt"
    done
    for j in "$sec_dir"/*.json; do
      [[ -f "$j" ]] || continue
      removed "$j"
    done
    chunks="$sec_dir/chunks"
    if [[ -d "$chunks" ]]; then
      removed "$chunks"
    fi
  done

  echo "   Cleaning book-level text/JSON/logs (keep manifest.json, report.json)"
  for f in "$bd"/*; do
    [[ -f "$f" ]] || continue
    case "$(basename "$f")" in
      manifest.json|report.json) ;;
      *) removed "$f" ;;
    esac
  done
  logs="$bd/logs"
  if [[ -d "$logs" ]]; then
    removed "$logs"
  fi

  echo "   Removing empty section dirs (if any)"
  for sec_dir in "$bd/sections"/*/; do
    [[ -d "$sec_dir" ]] || continue
    if [[ -z "$(ls -A "$sec_dir" 2>/dev/null)" ]]; then
      removed "$sec_dir"
      COUNT_DIRS=$((COUNT_DIRS + 1))
    fi
  done
done

# ---- project caches (run once, not per book) --------------------------
echo ""
echo "==> Cleaning project-level caches and test artifacts (Python __pycache__, pytest cache)"
if [[ -d ".pytest_cache" ]]; then
  removed ".pytest_cache"
fi
find ./src ./tests -type d -name '__pycache__' -print0 2>/dev/null | while IFS= read -r -d '' d; do
  removed "$d"
done

# Summary
if [[ "$DRY" == true ]]; then
  echo ""
  echo "==> DRY-RUN: nothing was deleted."
else
  echo ""
  echo "==> Cleaned."
fi
if [[ "$BYTES" -gt 0 ]]; then
  echo "Removed $COUNT_FILES file/dir entries, $COUNT_DIRS empty sections, $((BYTES/1024/1024)) MB reclaimed."
else
  echo "Nothing to remove (already clean)."
fi
