-- ingest/schema.sql
--
-- Supabase schema for Indux 5.0 ingestion pipeline.
--
-- Run this ONCE in your Supabase project's SQL Editor before running ingestion.
-- Dashboard → SQL Editor → New query → paste → Run
--
-- Table: public.document_chunks
--   Stores text chunks extracted from PDF manuals, together with their
--   384-dimensional sentence-transformer embeddings and positional metadata.
--
-- Design:
--   - chunk_id is the natural primary key: "{doc_id}_{chunk_index:05d}"
--   - upsert on chunk_id makes re-ingestion idempotent (safe to re-run)
--   - pgvector VECTOR(384) matches all-MiniLM-L6-v2 output dimension
--   - ivfflat index enables fast approximate cosine-similarity search
--     (add more lists if the table grows beyond ~1 M rows)

-- Step 1: enable the pgvector extension (only needed once per Supabase project)
CREATE EXTENSION IF NOT EXISTS vector;

-- Step 2: create the table
CREATE TABLE IF NOT EXISTS public.document_chunks (
    chunk_id      TEXT        PRIMARY KEY,
    doc_id        TEXT        NOT NULL,
    page_number   INTEGER     NOT NULL,
    chunk_index   INTEGER     NOT NULL,
    chunk_type    TEXT        NOT NULL DEFAULT 'text',
    text          TEXT        NOT NULL,
    embedding     VECTOR(384),          -- all-MiniLM-L6-v2: 384 dimensions
    bbox_x0       REAL,
    bbox_y0       REAL,
    bbox_x1       REAL,
    bbox_y1       REAL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Step 3: index for fast cosine-similarity search (pgvector ivfflat)
--   lists=100 is appropriate for up to ~1 M rows.
--   Build AFTER the first bulk load for best performance; it can be created
--   before the first insert without errors — it just starts with an empty index.
CREATE INDEX IF NOT EXISTS chunks_embedding_cosine_idx
    ON public.document_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Step 4: index on doc_id for fast "fetch all chunks for a document" queries
CREATE INDEX IF NOT EXISTS chunks_doc_id_idx
    ON public.document_chunks (doc_id);

-- -------------------------------------------------------------------------
-- Verification query (run after ingestion to confirm rows landed):
--
--   SELECT doc_id, count(*) AS chunks
--   FROM public.document_chunks
--   GROUP BY doc_id
--   ORDER BY chunks DESC;
--
-- Expected for Compressed-Air-Manual-9th-edition.pdf:
--   ~473 rows for whatever SHA-256 hash or --doc-id you passed.
-- -------------------------------------------------------------------------
