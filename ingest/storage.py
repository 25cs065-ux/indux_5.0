# ingest/storage.py
#
# Supabase persistence layer for Indux 5.0 ingestion.
#
# Responsibility:
#   1. Accept chunks + embeddings produced by pdf_ingestor and embedder.
#   2. Upsert rows into the `document_chunks` Supabase table.
#   3. Report success/failure clearly; surface database errors as StorageError.
#
# Environment variables required (see README.md):
#   SUPABASE_URL   : Your project's REST endpoint, e.g. https://xxx.supabase.co
#   SUPABASE_KEY   : Service-role key (NOT the anon key — needs INSERT access)
#
# Supabase table schema required:
#
#   CREATE TABLE document_chunks (
#     chunk_id      TEXT PRIMARY KEY,
#     doc_id        TEXT NOT NULL,
#     page_number   INTEGER NOT NULL,
#     chunk_index   INTEGER NOT NULL,
#     chunk_type    TEXT NOT NULL DEFAULT 'text',
#     text          TEXT NOT NULL,
#     embedding     VECTOR(384),   -- matches all-MiniLM-L6-v2 output dim
#     bbox_x0       REAL,
#     bbox_y0       REAL,
#     bbox_x1       REAL,
#     bbox_y1       REAL,
#     ingested_at   TIMESTAMPTZ DEFAULT now()
#   );
#
#   -- Enable pgvector extension first:
#   CREATE EXTENSION IF NOT EXISTS vector;
#
# Design decisions:
#   - upsert (on_conflict="chunk_id") is used so re-running ingestion on the
#     same document is idempotent — existing rows are updated, not duplicated.
#   - Rows are upserted in configurable batches (default 100) to avoid hitting
#     Supabase's request size limits on large documents.
#   - The storage layer is intentionally thin; it does not embed or chunk —
#     those concerns live in embedder.py and pdf_ingestor.py respectively.

from __future__ import annotations

import os
import logging
from typing import List, Optional

from .pdf_ingestor import Chunk, BoundingBox

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TABLE_NAME = "document_chunks"
DEFAULT_BATCH_SIZE = 100          # rows per upsert call


# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class StorageError(Exception):
    """
    Raised when the database operation fails.
    The message describes the cause in plain language.
    """


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def save_chunks(
    chunks: List[Chunk],
    embeddings: List[List[float]],
    *,
    supabase_url: Optional[str] = None,
    supabase_key: Optional[str] = None,
    batch_size: int = DEFAULT_BATCH_SIZE,
    table: str = TABLE_NAME,
) -> int:
    """
    Upsert *chunks* with their *embeddings* into Supabase.

    Parameters
    ----------
    chunks        : Chunk objects from ingest_pdf().
    embeddings    : Embedding vectors from embed_chunks(); must align 1:1 with
                    *chunks*.
    supabase_url  : Override for the SUPABASE_URL env var.
    supabase_key  : Override for the SUPABASE_KEY env var.
    batch_size    : Rows per upsert call.
    table         : Target table name (default: "document_chunks").

    Returns
    -------
    Total number of rows upserted.

    Raises
    ------
    StorageError : If env vars are missing, the client cannot connect, or any
                   upsert call fails.
    ValueError   : If chunks and embeddings have different lengths.
    """
    if len(chunks) != len(embeddings):
        raise ValueError(
            f"chunks and embeddings must have the same length, "
            f"got {len(chunks)} chunks and {len(embeddings)} embeddings."
        )

    if not chunks:
        logger.info("save_chunks called with 0 chunks — nothing to do.")
        return 0

    # --- Resolve credentials -----------------------------------------------
    url = supabase_url or os.getenv("SUPABASE_URL", "")
    key = supabase_key or os.getenv("SUPABASE_KEY", "")

    if not url:
        raise StorageError(
            "SUPABASE_URL is not set.  "
            "Export it before running ingestion:\n"
            "  $env:SUPABASE_URL = 'https://your-project.supabase.co'"
        )
    if not key:
        raise StorageError(
            "SUPABASE_KEY is not set.  "
            "Export the service-role key before running ingestion:\n"
            "  $env:SUPABASE_KEY = 'eyJ...'"
        )

    # --- Connect -----------------------------------------------------------
    client = _get_client(url, key)

    # --- Upsert in batches -------------------------------------------------
    total_upserted = 0

    for batch_start in range(0, len(chunks), batch_size):
        batch_chunks = chunks[batch_start : batch_start + batch_size]
        batch_embeddings = embeddings[batch_start : batch_start + batch_size]

        rows = [
            _chunk_to_row(chunk, emb)
            for chunk, emb in zip(batch_chunks, batch_embeddings)
        ]

        logger.info(
            "Upserting rows %d–%d into '%s' …",
            batch_start + 1,
            batch_start + len(rows),
            table,
        )

        try:
            response = (
                client.table(table)
                .upsert(rows, on_conflict="chunk_id")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            raise StorageError(
                f"Database upsert failed (rows {batch_start}–{batch_start + len(rows)}): {exc}\n"
                "Check that SUPABASE_URL and SUPABASE_KEY are correct and the "
                f"'{table}' table exists with the required schema."
            ) from exc

        # supabase-py v2 raises on HTTP errors; if we get here, it succeeded.
        total_upserted += len(rows)

    logger.info("Saved %d rows to '%s'.", total_upserted, table)
    return total_upserted


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_client(url: str, key: str) -> object:
    """
    Create and return a Supabase client.

    Raises StorageError if the supabase package is not installed.
    """
    try:
        from supabase import create_client  # type: ignore
    except ImportError as exc:
        raise StorageError(
            "The supabase package is required for database storage.\n"
            "Install it with:  py -m pip install supabase"
        ) from exc

    try:
        return create_client(url, key)
    except Exception as exc:  # noqa: BLE001
        raise StorageError(
            f"Could not create Supabase client: {exc}\n"
            "Verify that SUPABASE_URL is a valid URL "
            "(e.g. https://yourproject.supabase.co)."
        ) from exc


def _chunk_to_row(chunk: Chunk, embedding: List[float]) -> dict:
    """Convert a Chunk + embedding to a flat dict for Supabase upsert."""
    bbox: Optional[BoundingBox] = chunk.bbox
    return {
        "chunk_id":    chunk.chunk_id,
        "doc_id":      chunk.doc_id,
        "page_number": chunk.page_number,
        "chunk_index": chunk.chunk_index,
        "chunk_type":  chunk.chunk_type,
        "text":        chunk.text,
        "embedding":   embedding,
        "bbox_x0":     bbox.x0 if bbox else None,
        "bbox_y0":     bbox.y0 if bbox else None,
        "bbox_x1":     bbox.x1 if bbox else None,
        "bbox_y1":     bbox.y1 if bbox else None,
    }
