# Manifest reference

The JSON manifest is the **authoritative** description of book structure. The
tool never invents, guesses or silently reorders page boundaries.

## Skeleton

```json
{
  "schema_version": "1.0",
  "book": {
    "title": "Example Technical Book",
    "source_pdf": "book.pdf",
    "language": "en",
    "page_index_base": 1,
    "notes": ""
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
      "id": "preface",
      "title": "Preface",
      "type": "preface",
      "start_page": 5,
      "end_page": 12,
      "include": true
    }
  ]
}
```

## `book`

| Field | Type | Meaning |
|-------|------|---------|
| `title` | string | Display name; also names the output folder (sanitised). |
| `source_pdf` | string | Informational path to the PDF. |
| `language` | string | BCP-47-ish language tag (informational). |
| `page_index_base` | `0` or `1` | Base for page numbers. Default `1`. |
| `notes` | string | Free text. |

## `settings`

| Field | Default | Meaning |
|-------|---------|---------|
| `tts_engine` | `"kokoro"` | `kokoro` or `mock` (mock = silence, for testing). |
| `voice` | `"af_heart"` | Kokoro voice id, e.g. `af_heart`, `am_adam`, `bf_alice`. |
| `speed` | `1.0` | Speaking rate multiplier. |
| `audio_format` | `"mp3"` | Output audio container. |
| `combine_into_single_audiobook` | `true` | Also build `audiobooks/complete_audiobook.mp3`. |
| `keep_intermediate_files` | `true` | Keep `chunks/` and the stage JSON files. |
| `inter_section_pause_ms` | `0` | Optional silence inserted **between sections** when combining. |
| `code_block_policy` | `"read"` | `read`, `announce` or `skip` for code blocks. |
| `pronunciation_file` | `null` | Optional pronunciation rules JSON file, resolved relative to the manifest. |
| `cleanup` | `{}` | Optional cleanup overrides, see below. |

Unknown keys are preserved on load, so future per-section options are
forward-compatible.

### `settings.cleanup`

Optional overrides for [`CleanupConfig`](../src/text/cleanup.py). Everything is
conservative by default; nothing here is required.

```json
"cleanup": {
  "known_headers": ["THE PRAGMATIC PROGRAMMER"],
  "known_footers": ["Copyright 2024"],
  "remove_toc": false,
  "remove_bibliography": false,
  "remove_index": false,
  "remove_footnotes": false,
  "remove_page_numbers": true,
  "remove_running_headers": true,
  "repair_hyphenation": true,
  "join_wrapped_lines": true
}
```

| Key | Default | Meaning |
|-----|---------|---------|
| `known_headers` / `known_footers` | `[]` | Exact strings to always strip. |
| `remove_toc` | `false` | Drop dotted table-of-contents lines. |
| `remove_bibliography` / `remove_index` | `false` | Drop a clearly-marked trailing section. |
| `remove_footnotes` | `false` | Drop `*`/`†`/`‡` footnote blocks. |
| `remove_page_numbers` | `true` | Drop lines that are *only* a page number. |
| `remove_running_headers` | `true` | Auto-detect headers/footers recurring across pages. |
| `repair_hyphenation` | `true` | Rejoin words split as `hyphen-` + newline. |
| `join_wrapped_lines` | `true` | Reflow wrapped prose, keeping code/lists/tables. |

Changing any of these invalidates the `cleanup` cache key for every section, so
the next run re-cleans automatically.

## `sections`

| Field | Required | Meaning |
|-------|----------|---------|
| `id` | yes | Unique slug. Drives output filenames. |
| `title` | no | Human-readable title. |
| `type` | no | `preface`, `foreword`, `introduction`, `chapter`, `section`, `appendix`, `bibliography`, `index`, … or any custom string. |
| `start_page` | yes | Inclusive first physical page. |
| `end_page` | yes | Inclusive last physical page. |
| `include` | no | `false` skips the section entirely (default `true`). |
| `allow_overlap` | no | `true` documents an intentional overlap so it is reported as a warning instead of an error. |
| `settings` | no | Reserved for future per-section overrides. |

### Rules enforced

* Page numbers are **physical PDF page indices**, not printed page numbers.
* `start_page` and `end_page` are **inclusive**.
* Both must be integers ≥ 1 (with `page_index_base: 1`).
* `start_page` must not exceed `end_page`.
* Both must be within the PDF's page count.
* Section order is preserved exactly as authored.
* Gaps between sections are allowed.
* Overlapping ranges are reported. By default they are an **error**; add
  `"allow_overlap": true` to the section(s) involved to downgrade it to a
  documented warning. Pages are never silently duplicated or discarded.

## Generating a starting point

If you have no manifest yet:

```bash
python audiobook.py --pdf book.pdf --generate-template book_manifest.json
```

This writes a template with placeholder ranges. **You must edit the ranges** to
match the real PDF pages; the tool never guesses them.
