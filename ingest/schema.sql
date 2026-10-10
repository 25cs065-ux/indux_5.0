-- ingest/schema.sql
--
-- Supabase schema for Indux 5.0  --  updated to match ai/brain.py
--
-- Run this in your Supabase project SQL Editor
--   Dashboard -> SQL Editor -> New query -> paste -> Run
-- All statements use IF NOT EXISTS / OR REPLACE so they are safe to re-run.
--
-- Tables / objects created:
--   public.manual_chunks        -- ingested PDF chunks + embeddings
--   public.match_manual_chunks  -- RPC called by ai/brain.py for vector search
--
-- Required environment variables (ingest/.env):
--   SUPABASE_URL    : https://<project-ref>.supabase.co
--   SUPABASE_KEY    : service-role key (needs INSERT / UPDATE access)
--   GEMINI_API_KEY  : Google AI Studio key (used by embedder and brain)

-- ---------------------------------------------------------------------------
-- Step 1: pgvector extension (once per Supabase project)
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS vector;

-- ---------------------------------------------------------------------------
-- Step 2: main table
--
-- Column contract (must match both ingest/storage.py and ai/brain.py):
--   id           : "{doc_id}_{chunk_index:05d}" — natural primary key
--   content      : chunk text           — brain reads c.get("content")
--   manual_title : doc_id from ingest   — brain reads c.get("manual_title")
--   page_number  : 1-based page         — brain reads c.get("page_number")
--   section      : chunk_type value     — brain reads c.get("section")
--   chunk_index  : 0-based position within the document
--   embedding    : VECTOR(3072)         — gemini-embedding-001 dimension
--   bbox_*       : bounding-box coords from PyMuPDF (NULL when unavailable)
--   ingested_at  : set by DB DEFAULT now()
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.manual_chunks (
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

-- ---------------------------------------------------------------------------
-- Step 3: indexes
-- ---------------------------------------------------------------------------

-- Approximate nearest-neighbour (cosine) index.
-- lists=100 is suitable for up to ~1 M rows; increase for larger collections.
-- For best performance, build AFTER the first bulk load.
CREATE INDEX IF NOT EXISTS manual_chunks_embedding_idx
    ON public.manual_chunks
    USING ivfflat (embedding vector_cosine_ops)
    WITH (lists = 100);

-- Lookup by manual_title for document-scoped queries.
CREATE INDEX IF NOT EXISTS manual_chunks_manual_title_idx
    ON public.manual_chunks (manual_title);

-- ---------------------------------------------------------------------------
-- Step 4: match_manual_chunks RPC
--
-- Called by ai/brain.py:
--   supabase.rpc("match_manual_chunks", {
--       "query_embedding": <3072-float list>,
--       "match_count": <int>
--   }).execute()
--
-- Returns: id, content, manual_title, page_number, section, distance
-- brain.py filters results where distance <= 0.65 (cosine distance).
-- ---------------------------------------------------------------------------
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

-- ---------------------------------------------------------------------------
-- Verification queries (run after ingestion):
--
--   SELECT manual_title, count(*) AS chunks
--   FROM public.manual_chunks
--   GROUP BY manual_title
--   ORDER BY chunks DESC;
--
--   SELECT * FROM match_manual_chunks(
--       array_fill(0.0::float, ARRAY[3072])::vector, 3
--   );
-- ---------------------------------------------------------------------------
