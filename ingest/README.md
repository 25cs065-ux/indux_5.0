# ingest/README.md

# Indux 5.0 — `ingest/` Module

> **Owner:** Devanshi (branch `devanshi`)

## What this module does

This module is responsible for turning PDF machine manuals and SOPs into searchable text chunks that the AI retrieval system can use to answer factory workers' questions.

### Processing pipeline

```
Admin uploads PDF
      │
      ▼
┌─────────────────────┐
│  Validate file       │  ← exists? is PDF? not empty? not corrupt?
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Extract text        │  ← page by page, using pypdf
│  (page-by-page)      │
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Split into chunks   │  ← overlapping windows, configurable size
│  + attach metadata   │  ← doc_id + page_number on every chunk
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Return IngestResult │  ← caller stores chunks / sends to AI
└─────────────────────┘
```

---

## Files

| File | Purpose |
|---|---|
| `pdf_ingestor.py` | Core ingestion logic — the main module |
| `__init__.py` | Package entry point; re-exports the public API |
| `requirements.txt` | Python dependencies |
| `tests/test_pdf_ingestor.py` | Automated test suite (pytest) |
| `README.md` | This file |

---

## Public API

```python
from ingest import ingest_pdf, IngestResult, Chunk, IngestError

result: IngestResult = ingest_pdf(
    "path/to/manual.pdf",
    doc_id="boiler_manual_v3",   # optional; SHA-256 hash used if omitted
    chunk_size=800,              # max chars per chunk (default: 800)
    chunk_overlap=150,           # overlap between chunks (default: 150)
)

for chunk in result.chunks:
    print(chunk.page_number, chunk.text[:80])
```

### `IngestResult` fields

| Field | Type | Description |
|---|---|---|
| `doc_id` | `str` | Stable document identifier |
| `total_pages` | `int` | Number of pages in the PDF |
| `chunks` | `list[Chunk]` | Text chunks ready for embedding |
| `empty_pages` | `list[int]` | 1-based page numbers with no text |
| `scanned_warning` | `bool` | `True` when no text was found anywhere (likely scanned) |

### `Chunk` fields

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The chunk's text content |
| `doc_id` | `str` | Source document identifier |
| `page_number` | `int` | 1-based page where the chunk originates |
| `chunk_index` | `int` | 0-based position within the document |

### Errors raised

| Exception | When |
|---|---|
| `IngestError` | File missing, not a PDF, empty, corrupt, encrypted |
| `ValueError` | Invalid `chunk_size` or `chunk_overlap` parameters |

---

## Installation

```powershell
python -m pip install -r ingest/requirements.txt
```

---

## Running tests

```powershell
python -m pytest ingest/tests/ -v
```

---

## Integration with the rest of the project

The `ingest_pdf()` function is intentionally storage-agnostic. It returns a plain Python object (`IngestResult`) and never writes to a database directly.

**To integrate with the backend (`backend/`):**

```python
from ingest import ingest_pdf, IngestError

def handle_upload(file_path: str):
    try:
        result = ingest_pdf(file_path)
    except IngestError as e:
        return {"error": str(e)}, 400

    # TODO (backend teammate): store result.chunks in vector DB / search index
    # Each chunk has: text, doc_id, page_number, chunk_index
    for chunk in result.chunks:
        store_chunk(chunk)   # implement in backend/
```

**What the AI module (`ai/`) needs from each chunk:**

- `chunk.text` — the passage to embed and retrieve
- `chunk.doc_id` — for deduplication and source attribution
- `chunk.page_number` — so answers can cite "see page N"

---

## Known limitations

1. **Scanned PDFs** — image-only PDFs (where text is stored as pixels, not characters) will produce zero chunks and `scanned_warning = True`. OCR is not implemented; this is out of scope for the current task.
2. **Encrypted PDFs** — password-protected PDFs will raise `IngestError`.
3. **Complex layouts** — multi-column text or text in tables may be extracted in reading order that differs from visual order; this is a known limitation of pypdf's text extractor.

---

## What teammates still need to do

| Component | Team member | Required work |
|---|---|---|
| `backend/` | Backend teammate | Build the upload endpoint; call `ingest_pdf()`; store chunks |
| `ai/` | AI teammate | Embed chunks; implement semantic search; generate answers with page citations |
| `worker-app/` | Frontend teammate | Build the question UI |
| `admin-app/` | Admin teammate | Build the PDF upload UI |
