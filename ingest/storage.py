# ingest/storage.py
#
# Supabase persistence layer for Indux 5.0 ingestion.
#
# Responsibility:
#   1. Accept chunks + embeddings produced by pdf_ingestor and embedder.
#   2. Upsert rows into the `manual_chunks` Supabase table.
#   3. Report success/failure clearly; surface database errors as StorageError.
#
# Environment variables required:
#   SUPABASE_URL   : Your project's REST endpoint, e.g. https://xxx.supabase.co
#   SUPABASE_KEY   : Service-role key (NOT the anon key — needs INSERT access)
#
# Table: public.manual_chunks  (see ingest/schema.sql for full DDL)
#   Columns written by this module:
#     id            TEXT PRIMARY KEY  — "{doc_id}_{chunk_index:05d}"
#     content       TEXT              — chunk text (brain.py reads this)
#     manual_title  TEXT              — doc_id passed to ingest_pdf()
#     page_number   INTEGER           — 1-based page number
#     section       TEXT              — chunk_type ("text" / "troubleshooting_row" / "safety")
#     chunk_index   INTEGER           — 0-based position within the document
#     embedding     VECTOR(3072)      — gemini-embedding-001 output
#     bbox_x0/y0/x1/y1  REAL         — bounding box (null when PyMuPDF unavailable)
#     ingested_at   TIMESTAMPTZ       — set by DB DEFAULT now()
#
# Design decisions:
#   - Column names match what ai/brain.py reads: content, manual_title,
#     page_number, section, id.  Both modules must agree on these names.
#   - upsert on_conflict="id" makes re-ingestion idempotent.
#   - Rows are upserted in configurable batches (default 100).

from __future__ import annotations

import os
import logging
from typing import List, Optional

from .pdf_ingestor import Chunk, BoundingBox
from dotenv import load_dotenv
from pathlib import Path

# Load from ingest/.env regardless of the working directory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TABLE_NAME = "manual_chunks"
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
    table         : Target table name (default: "manual_chunks").

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

    # Safe diagnostic: log the REST endpoint that will be used (no credentials).
    import urllib.parse as _urlparse
    _parsed = _urlparse.urlparse(url)
    logger.info(
        "Supabase target: %s://%s/rest/v1/%s",
        _parsed.scheme, _parsed.netloc, table,
    )

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
                .upsert(rows, on_conflict="id")
                .execute()
            )
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            hint = ""
            if "PGRST205" in msg or "schema cache" in msg:
                hint = (
                    "\n\nThe table does not exist yet.  Run the SQL in "
                    "ingest/schema.sql in your Supabase project's SQL Editor:\n"
                    "  Supabase Dashboard → SQL Editor → New query → paste "
                    "ingest/schema.sql → Run"
                )
            raise StorageError(
                f"Database upsert failed (rows {batch_start}–{batch_start + len(rows)}): {exc}"
                f"{hint}\n"
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
    """
    Convert a Chunk + embedding to a flat dict for the manual_chunks upsert.

    Column names match what ai/brain.py reads:
      id           ← chunk.chunk_id  ("{doc_id}_{chunk_index:05d}")
      content      ← chunk.text
      manual_title ← chunk.doc_id
      page_number  ← chunk.page_number
      section      ← chunk.chunk_type  ("text" / "troubleshooting_row" / "safety")
    """
    bbox: Optional[BoundingBox] = chunk.bbox
    return {
        "id":           chunk.chunk_id,
        "content":      chunk.text,
        "manual_title": chunk.doc_id,
        "page_number":  chunk.page_number,
        "section":      chunk.chunk_type,
        "chunk_index":  chunk.chunk_index,
        "embedding":    embedding,
        "bbox_x0":      bbox.x0 if bbox else None,
        "bbox_y0":      bbox.y0 if bbox else None,
        "bbox_x1":      bbox.x1 if bbox else None,
        "bbox_y1":      bbox.y1 if bbox else None,
    }
