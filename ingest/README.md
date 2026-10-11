# ingest/README.md

# Indux 5.0 — `ingest/` Module

> **Owner:** Devanshi (branch `devanshi`)

## What this module does

Turns PDF machine manuals and SOPs into searchable text chunks that the AI retrieval system can use to answer factory workers' questions.

### End-to-end pipeline

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
│  Extract text        │  ← page by page with PyMuPDF (bounding boxes)
│  (page-by-page)      │    falls back to pypdf if PyMuPDF unavailable
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Split into chunks   │  ← overlapping windows (configurable size/overlap)
│  Detect TS tables    │  ← troubleshooting rows kept as atomic chunks
│  Attach metadata     │  ← doc_id, page_number, chunk_id, bbox, chunk_type
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Batch embed         │  ← sentence-transformers (local, no API key)
└────────┬────────────┘
         │
         ▼
┌─────────────────────┐
│  Upsert to Supabase  │  ← idempotent (on_conflict=chunk_id)
└─────────────────────┘
```

---

## Files

| File | Purpose |
|---|---|
| `pdf_ingestor.py` | Core extraction + chunking logic |
| `embedder.py` | Batch embedding generation (sentence-transformers) |
| `storage.py` | Supabase persistence layer |
| `run_ingest.py` | **One-command CLI entry point** |
| `__init__.py` | Package entry point; re-exports the public API |
| `requirements.txt` | Python dependencies |
| `tests/test_pdf_ingestor.py` | Original 31-test suite |
| `tests/test_new_features.py` | 42 new tests for Round 1 additions |
| `README.md` | This file |

---

## Quick start

### 1. Install dependencies

```powershell
py -m pip install -r ingest/requirements.txt
```

> **First run note:** `sentence-transformers` downloads the `all-MiniLM-L6-v2`
> model (~22 MB) on first use. After that it's cached locally.

### 2. Set environment variables

```powershell
$env:SUPABASE_URL = "https://your-project-id.supabase.co"
$env:SUPABASE_KEY = "eyJhbGciOi..."    # service-role key (NOT anon)
```

Optional:
```powershell
$env:EMBED_MODEL  = "all-MiniLM-L6-v2"   # default; change to any HuggingFace model
```

### 3. Create the Supabase table (once)

Run this SQL in your Supabase project's **SQL Editor**:

```sql
-- Enable pgvector (only needed once per project)
CREATE EXTENSION IF NOT EXISTS vector;

-- Chunks table
CREATE TABLE IF NOT EXISTS document_chunks (
  chunk_id      TEXT PRIMARY KEY,
  doc_id        TEXT NOT NULL,
  page_number   INTEGER NOT NULL,
  chunk_index   INTEGER NOT NULL,
  chunk_type    TEXT NOT NULL DEFAULT 'text',
  text          TEXT NOT NULL,
  embedding     VECTOR(384),
  bbox_x0       REAL,
  bbox_y0       REAL,
  bbox_x1       REAL,
  bbox_y1       REAL,
  ingested_at   TIMESTAMPTZ DEFAULT now()
);

-- Optional: index for fast similarity search
CREATE INDEX IF NOT EXISTS chunks_embedding_idx
  ON document_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);
```

### 4. Run ingestion

```powershell
# Basic
py ingest/run_ingest.py path/to/manual.pdf

# With a human-readable doc ID
py ingest/run_ingest.py path/to/manual.pdf --doc-id boiler_manual_v3

# Dry run (extract + embed, skip DB write — useful for testing)
py ingest/run_ingest.py path/to/manual.pdf --dry-run

# Custom chunk size and overlap
py ingest/run_ingest.py path/to/manual.pdf --chunk-size 600 --overlap 100

# Verbose output
py ingest/run_ingest.py path/to/manual.pdf --dry-run --verbose
```

### 5. Run tests

```powershell
py -m pytest ingest/tests/ -v
```

Expected: **73 passed**.

---

## Public API

```python
from ingest import ingest_pdf, IngestResult, Chunk, BoundingBox, IngestError
from ingest.embedder import embed_chunks, EmbeddingError
from ingest.storage import save_chunks, StorageError

# 1. Extract and chunk
result: IngestResult = ingest_pdf(
    "path/to/manual.pdf",
    doc_id="boiler_manual_v3",   # optional; SHA-256 hash if omitted
    chunk_size=800,
    chunk_overlap=150,
)

# 2. Embed
embeddings = embed_chunks(result.chunks)   # list[list[float]], one per chunk

# 3. Save to Supabase
n_saved = save_chunks(result.chunks, embeddings)
```

### `IngestResult` fields

| Field | Type | Description |
|---|---|---|
| `doc_id` | `str` | Stable document identifier |
| `total_pages` | `int` | Number of pages in the PDF |
| `chunks` | `list[Chunk]` | Text chunks ready for embedding |
| `empty_pages` | `list[int]` | 1-based page numbers with no text |
| `scanned_warning` | `bool` | `True` when no text was found (likely scanned) |
| `extractor_used` | `str` | `"pymupdf"` or `"pypdf"` |

### `Chunk` fields

| Field | Type | Description |
|---|---|---|
| `text` | `str` | The chunk's text content |
| `doc_id` | `str` | Source document identifier |
| `page_number` | `int` | 1-based page where the chunk originates |
| `chunk_index` | `int` | 0-based position within the document |
| `chunk_id` | `str` | Unique ID: `"{doc_id}_{chunk_index:05d}"` |
| `bbox` | `BoundingBox \| None` | Text bounding box (PyMuPDF only) |
| `chunk_type` | `str` | `"text"` or `"troubleshooting_row"` |

### `BoundingBox` fields

All values in PDF points (1 pt = 1/72 inch):

| Field | Type | Description |
|---|---|---|
| `x0, y0` | `float` | Lower-left corner |
| `x1, y1` | `float` | Upper-right corner |

### Errors raised

| Exception | Module | When |
|---|---|---|
| `IngestError` | `pdf_ingestor` | File missing, not a PDF, empty, corrupt |
| `EmbeddingError` | `embedder` | sentence-transformers not installed, encode fails |
| `StorageError` | `storage` | Missing credentials, DB unreachable, upsert fails |
| `ValueError` | any | Invalid parameters |

---

## CLI exit codes

| Code | Meaning |
|---|---|
| 0 | Success |
| 1 | Ingestion error (bad file, scanned PDF) |
| 2 | Embedding error |
| 3 | Database / storage error |
| 4 | Unexpected / unknown error |

---

## Environment variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `SUPABASE_URL` | Yes (unless `--dry-run`) | — | Supabase project REST endpoint |
| `SUPABASE_KEY` | Yes (unless `--dry-run`) | — | Supabase **service-role** key |
| `EMBED_MODEL` | No | `all-MiniLM-L6-v2` | HuggingFace model for embeddings |

---

## Supabase schema reference

```sql
CREATE TABLE document_chunks (
  chunk_id      TEXT PRIMARY KEY,
  doc_id        TEXT NOT NULL,
  page_number   INTEGER NOT NULL,
  chunk_index   INTEGER NOT NULL,
  chunk_type    TEXT NOT NULL DEFAULT 'text',
  text          TEXT NOT NULL,
  embedding     VECTOR(384),
  bbox_x0       REAL,
  bbox_y0       REAL,
  bbox_x1       REAL,
  bbox_y1       REAL,
  ingested_at   TIMESTAMPTZ DEFAULT now()
);
```

> If you switch to a larger embedding model, update the `VECTOR(384)` dimension
> to match your model's output (e.g. `VECTOR(768)` for `all-mpnet-base-v2`).

---

## Integration with the rest of the project

The retrieval system in `ai/` should query the `document_chunks` table using
pgvector similarity search:

```sql
SELECT chunk_id, doc_id, page_number, chunk_type, text,
       1 - (embedding <=> $1::vector) AS similarity
FROM document_chunks
ORDER BY embedding <=> $1::vector
LIMIT 5;
```

Each chunk carries `page_number` so answers can cite **"See page N"**, and
`bbox_*` coordinates so a future highlight helper can draw boxes on the PDF.

---

## Known limitations

1. **Scanned PDFs** — image-only PDFs yield zero chunks and `scanned_warning = True`. OCR is out of scope.
2. **Encrypted PDFs** — password-protected PDFs raise `IngestError`.
3. **Complex table layouts** — PyMuPDF reads tables as prose; the troubleshooting-row detector works on text that follows a `Problem: / Cause: / Remedy:` pattern.
4. **Embedding model download** — `all-MiniLM-L6-v2` is downloaded on first run (~22 MB). Subsequent runs use the local cache.

---

## Remaining work (Round 2 + 3)

| Task | Owner | Status |
|---|---|---|
| Save manual pages as images for diagrams | Devanshi | Pending |
| Optional Gemini page-description stage | Devanshi | Pending |
| Safety-related chunk tagging | Devanshi | Pending |
| PDF highlight helper (bbox → highlight) | Devanshi | Pending |
| Admin app: PDF upload + progress UI | Devanshi | Pending |
