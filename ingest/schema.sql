-- ingest/schema.sql
--
-- Fresh Supabase setup for Indux 5.0.
--
-- HOW TO RUN:
--   1. Open your Supabase project: https://supabase.com/dashboard
--   2. Click "SQL Editor" in the left sidebar
--   3. Click "New query"
--   4. Paste this entire file and click "Run"
--   5. You should see "Success. No rows returned." for each statement.
--
-- What this creates:
--   public.manual_chunks       — table for PDF chunk text + embeddings
--   public.match_manual_chunks — RPC function for vector similarity search
--
-- Safe for a FRESH database with no data.
-- If the table already exists with wrong columns, it is dropped and recreated.

-- ============================================================================
-- Step 1: Enable pgvector extension
-- Required for the VECTOR column type and similarity operators.
-- Only needs to run once per Supabase project; safe to re-run.
-- ============================================================================
CREATE EXTENSION IF NOT EXISTS vector;

-- ============================================================================
-- Step 2: Drop and recreate the table (fresh setup — no data to preserve)
--
-- We drop first to avoid PGRST204 errors caused by any previously created
-- table that is missing columns (e.g. bbox_x0 / bbox_y0 / bbox_x1 / bbox_y1).
--
-- Column source of truth:
--   ingest/storage.py  _chunk_to_row()  — writes these columns
--   ai/brain.py        search_chunks()  — reads these columns
--
--   id            TEXT  — "{doc_id}_{chunk_index:05d}"  (primary key)
--   content       TEXT  — chunk text        brain: c.get("content")
--   manual_title  TEXT  — doc_id            brain: c.get("manual_title")
--   page_number   INT   — 1-based page      brain: c.get("page_number")
--   section       TEXT  — chunk_type        brain: c.get("section")
--   chunk_index   INT   — 0-based position  (storage only)
--   embedding     VECTOR(3072)  — gemini-embedding-001 output
--   bbox_x0       REAL  — bounding box from PyMuPDF (NULL when unavailable)
--   bbox_y0       REAL
--   bbox_x1       REAL
--   bbox_y1       REAL
--   ingested_at   TIMESTAMPTZ  — set automatically by the database
-- ============================================================================
DROP TABLE IF EXISTS public.manual_chunks CASCADE;

CREATE TABLE public.manual_chunks (
    id            TEXT        PRIMARY KEY,
    content       TEXT        NOT NULL,
    manual_title  TEXT        NOT NULL,
    page_number   INTEGER     NOT NULL,
    section       TEXT        NOT NULL DEFAULT 'text',
    chunk_index   INTEGER     NOT NULL,
    embedding     VECTOR(3072),
    bbox_x0       REAL,
    bbox_y0       REAL,
    bbox_x1       REAL,
    bbox_y1       REAL,
    ingested_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- ============================================================================
-- Step 3: Indexes
-- ============================================================================

-- Cosine-similarity approximate nearest-neighbour index (pgvector ivfflat).
-- lists=100 is appropriate for up to ~1 million rows.
-- Build time is fast on an empty table; the index fills as rows are inserted.
CREATE INDEX manual_chunks_embedding_idx
    ON public.manual_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Fast lookup when filtering chunks by document.
CREATE INDEX manual_chunks_manual_title_idx
    ON public.manual_chunks (manual_title);

-- ============================================================================
-- Step 4: match_manual_chunks RPC function
--
-- Called by ai/brain.py as:
--   supabase.rpc("match_manual_chunks", {
--       "query_embedding": <list of 3072 floats>,
--       "match_count": <int>
--   }).execute()
--
-- brain.py then reads from each returned row:
--   item.get("id")
--   item.get("content")
--   item.get("manual_title")
--   item.get("page_number")
--   item.get("section")
--   item.get("distance")   <- filtered at <= 0.65 (cosine distance)
-- ============================================================================
CREATE OR REPLACE FUNCTION public.match_manual_chunks(
    query_embedding VECTOR(3072),
    match_count     INT DEFAULT 5
)
RETURNS TABLE (
    id            TEXT,
    content       TEXT,
    manual_title  TEXT,
    page_number   INTEGER,
    section       TEXT,
    distance      FLOAT
)
LANGUAGE SQL STABLE
AS $$
    SELECT
        id,
        content,
        manual_title,
        page_number,
        section,
        (embedding <=> query_embedding)::FLOAT AS distance
    FROM public.manual_chunks
    WHERE embedding IS NOT NULL
    ORDER BY embedding <=> query_embedding
    LIMIT match_count;
$$;

-- ============================================================================
-- Verification queries — run these AFTER ingestion to confirm everything works
--
-- 1. Check row count per manual:
--    SELECT manual_title, count(*) AS chunks
--    FROM public.manual_chunks
--    GROUP BY manual_title
--    ORDER BY chunks DESC;
--
-- 2. Confirm the RPC function works (returns 0 rows on empty table):
--    SELECT * FROM match_manual_chunks(
--        array_fill(0.0::float, ARRAY[3072])::vector,
--        3
--    );
--
-- 3. Confirm all columns exist:
--    SELECT column_name, data_type
--    FROM information_schema.columns
--    WHERE table_schema = 'public'
--      AND table_name   = 'manual_chunks'
--    ORDER BY ordinal_position;
-- ============================================================================
