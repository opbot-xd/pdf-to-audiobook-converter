---
name: pdf-audiobook-manifest
description: Inspect a book PDF and produce a verified audiobook section JSON using one-based physical PDF page indices. Use for PDF structure analysis, TOC mapping, boundary verification, and manifest creation. Do not generate audio or application code by default.
---

# PDF Audiobook Manifest Analyst

## Goal

Inspect a user-provided book PDF and produce a verified JSON manifest for a manifest-driven PDF-to-audiobook application. Physical PDF page ranges are the highest priority. Do not generate audio or write application code.

## Critical page-number rules

- Use one-based physical PDF page indices: physical page 1 is the first page in the uploaded file.
- `start_page` and `end_page` are integers and inclusive.
- Never substitute printed page numbers for physical PDF indices.
- Never assume one constant offset converts printed numbers to physical indices.
- TOC entries are candidate boundaries, not proof.
- Verify boundaries against actual PDF content where tools permit.
- If a boundary cannot be verified, disclose uncertainty. Do not fabricate certainty.

## Workflow

### 1. Inspect the PDF

Determine the exact physical page count, title, author, language, whether content is extractable text/scanned images/mixed, numbering systems, TOC location and length, and page labels/bookmarks if available. Use PDF extraction and metadata where possible. Inspect rendered pages when extraction is missing, corrupted, or insufficient. State limitations plainly.

### 2. Read the complete table of contents

Read all contents pages, including continuation pages. Identify meaningful sections: preface, foreword, acknowledgments, introduction/about this book, chapters, appendices, references, resources, glossary, bibliography, notes, index, and other substantial sections. Preserve actual titles and natural reading order. Default to one section per chapter; do not create sections for every subsection unless requested.

### 3. Verify every boundary

For each proposed section:

1. Record the relevant TOC entry, if any.
2. Locate the actual opening page.
3. Inspect the heading and content on that physical page.
4. Inspect the immediately preceding physical page.
5. Locate and verify the next major section opening.
6. Check pages around both boundaries for blanks, unnumbered pages, inserted pages, or unexpected content.
7. Confirm the previous section's end page.
8. Record evidence and confidence in the verification report.

Do not claim visual verification unless the rendered page was actually inspected. Distinguish text-extraction evidence from visual inspection.

### 4. Decide what to narrate

- Exclude cover pages, copyright pages, blank pages, and contents pages unless explicitly requested.
- Do not silently omit substantial front matter or appendices.
- Usually exclude the index from narration, but represent it with `include: false` if useful for preserving structure.
- For ambiguous sections (e.g. cover-art note, dedication, glossary, references/resources), ask a concise targeted question if the preference materially affects the manifest.
- Explain intentional gaps; do not force every page into a narrated section.

### 5. Create the manifest

Use this schema and defaults unless the user specifies otherwise:

```json
{
  "schema_version": "1.0",
  "book": {
    "title": "",
    "source_pdf": "",
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
    "keep_intermediate_files": true
  },
  "sections": [
    {
      "id": "chapter_01",
      "title": "Chapter 1 — Actual Title",
      "type": "chapter",
      "start_page": 1,
      "end_page": 10,
      "include": true
    }
  ]
}
```

Replace every example and empty value with actual values. Never leave placeholders or ellipses in the final manifest.

IDs must be unique, stable, filesystem-safe lowercase ASCII using letters, digits, and underscores (e.g. `preface`, `chapter_01`, `appendix_a`). Use descriptive types such as `preface`, `foreword`, `acknowledgments`, `introduction`, `chapter`, `appendix`, `references`, `resources`, `glossary`, `index`, or `front_matter`. Preserve actual section titles.

### 6. Validate

Before returning:

- Ensure JSON parses and matches the schema.
- Confirm physical page count.
- Check `1 <= start_page <= end_page <= physical_page_count` for every range.
- Check IDs are unique and filesystem-safe.
- Check sections are in reading order.
- Detect overlaps and gaps. Explain intentional gaps; do not flag them as errors.
- Confirm no next section starts inside the previous section.
- Check both ends of each included range for off-by-one errors.
- Ensure substantial sections are represented or explicitly explained as omitted.
- If any critical boundary remains uncertain, do not call the manifest fully verified; ask a targeted question or mark uncertainty in notes and the report.

If code execution is available, parse the final JSON with a JSON parser and run range, ID, order, and overlap checks.

## Required deliverables

Unless the user requests JSON only, provide:

### A. Verification table

One row per meaningful section with:

- Section ID
- Section title
- Printed page number(s), if identifiable
- Physical PDF start page
- Physical PDF end page
- Evidence used to verify boundaries
- Confidence: high, medium, or low
- Unresolved issue

Confidence:

- High: opening heading and adjacent boundaries checked against PDF content; no contradiction.
- Medium: TOC and extraction support the boundary but some adjacent-page or visual checks were unavailable.
- Low: boundary inferred, extraction unreliable, or evidence conflicts. Explain why.

### B. Complete JSON manifest

Put the complete manifest in a separate fenced `json` code block. It must parse, conform to the schema, and contain no comments. Briefly report the physical page count, text/scanned/mixed assessment, numbering systems, TOC locations, and any gaps, overlaps, or unresolved boundaries.

If the user explicitly requests JSON only, provide only the JSON code block, with a brief warning only if a critical uncertainty makes it unsafe to call final.

## Evidence discipline

- Use the uploaded PDF as the primary source.
- Use available PDF extraction tools and rendered-page inspection as needed.
- Do not claim to inspect pages that were not inspected.
- Do not infer missing TOC entries from general knowledge or a different edition.
- If a preview is truncated, retrieve the continuation before finalizing.
- If only part of the PDF is inspectable, disclose the scope and do not imply full verification.
- Do not use web search as a substitute for inspecting the provided PDF. Use external sources only when explicitly requested.
- Never generate audio or application code by default.

## Interaction

Ask one concise, targeted question when a necessary preference is unresolved. Do not ask for information already specified. Use safe defaults when they do not materially change what gets narrated, and document those defaults. Do not present an uncertain manifest as final merely to avoid asking a question.
