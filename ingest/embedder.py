# ingest/embedder.py
#
# Batch embedding generation for Indux 5.0.
#
# Responsibility:
#   1. Accept a list of Chunk objects.
#   2. Extract their text, call the Google Gemini embedding API in batches,
#      and return 3072-dimensional float vectors aligned 1:1 with the chunks.
#
# Design decisions:
#   - Uses google-genai SDK with model "gemini-embedding-001" (3072 dims) to
#     match the brain module in ai/brain.py exactly.  Both ingest and retrieval
#     must use the same model so similarity search returns meaningful scores.
#   - GEMINI_API_KEY env var is required (loaded from ingest/.env via dotenv).
#   - Chunks are sent one at a time because the Gemini embedding API does not
#     support batch inputs in a single call the way sentence-transformers does.
#     batch_size is accepted for API compatibility but is not used.
#   - The module never writes embeddings to disk; the caller decides persistence.
#   - If google-genai is unavailable, a clear EmbeddingError is raised with
#     installation instructions.

from __future__ import annotations

import os
import logging
from pathlib import Path
from typing import List

from dotenv import load_dotenv

from .pdf_ingestor import Chunk

# Load from ingest/.env regardless of the working directory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Model name must match ai/brain.py exactly.
GEMINI_EMBED_MODEL = "gemini-embedding-001"

# Output dimension of gemini-embedding-001.
GEMINI_EMBED_DIM = 3072

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

class EmbeddingError(Exception):
    """
    Raised when embedding generation fails.
    The message describes the cause in plain language.
    """


def embed_chunks(
    chunks: List[Chunk],
    *,
    model_name: str | None = None,
    batch_size: int = 32,           # kept for API compatibility; not used
) -> List[List[float]]:
    """
    Generate 3072-dimensional Gemini embeddings for every chunk.

    Parameters
    ----------
    chunks     : List of Chunk objects whose ``.text`` fields will be embedded.
    model_name : Gemini embedding model name.
                 Defaults to the GEMINI_EMBED_MODEL env var, then
                 "gemini-embedding-001".
    batch_size : Accepted for API compatibility but ignored — the Gemini
                 embedding API is called once per text.

    Returns
    -------
    A list of float lists, one per chunk, each with length 3072.

    Raises
    ------
    EmbeddingError : If google-genai is not installed, GEMINI_API_KEY is
                     missing, or the API call fails.
    ValueError     : If *chunks* is empty.
    """
    if not chunks:
        raise ValueError("embed_chunks requires at least one chunk; got empty list.")

    resolved_model = (
        model_name
        or os.getenv("GEMINI_EMBED_MODEL", GEMINI_EMBED_MODEL)
    )

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise EmbeddingError(
            "GEMINI_API_KEY is not set.  "
            "Add it to ingest/.env or export it before running ingestion:\n"
            "  $env:GEMINI_API_KEY = 'AIza...'"
        )

    client = _get_genai_client(api_key)

    logger.info(
        "Embedding %d chunks with Gemini model '%s' …",
        len(chunks),
        resolved_model,
    )

    embeddings: List[List[float]] = []
    for i, chunk in enumerate(chunks):
        try:
            response = client.models.embed_content(
                model=resolved_model,
                contents=chunk.text,
            )
            values = response.embeddings[0].values
            embeddings.append(list(values))
        except Exception as exc:  # noqa: BLE001
            raise EmbeddingError(
                f"Gemini embedding failed on chunk {i} "
                f"(chunk_id={chunk.chunk_id!r}): {exc}"
            ) from exc

        if (i + 1) % 50 == 0:
            logger.info("  … embedded %d / %d chunks", i + 1, len(chunks))

    logger.info(
        "Embedding complete. %d vectors, dimension %d.",
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )
    return embeddings


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _get_genai_client(api_key: str) -> object:
    """
    Create and return a google.genai.Client.

    Raises EmbeddingError if google-genai is not installed.
    """
    try:
        from google import genai  # type: ignore
    except ImportError as exc:
        raise EmbeddingError(
            "google-genai is required for Gemini embedding.\n"
            "Install it with:  py -m pip install google-genai"
        ) from exc

    return genai.Client(api_key=api_key)
