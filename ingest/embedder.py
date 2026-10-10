# ingest/embedder.py
#
# Batch embedding generation for Indux 5.0.
#
# Responsibility:
#   1. Accept a list of Chunk objects.
#   2. Extract their text, generate embeddings in batches using
#      sentence-transformers (local, free, no API key required).
#   3. Return embeddings as a list of float lists aligned 1:1 with the chunks.
#
# Design decisions:
#   - sentence-transformers with the "all-MiniLM-L6-v2" model (384-dim) is
#     used by default because it is small (~22 MB), fast on CPU, and gives
#     good semantic retrieval quality for technical documents.
#   - The model name is configurable via the EMBED_MODEL environment variable
#     so teams can switch to a larger model without touching this file.
#   - Batch size is configurable; default 32 is a safe choice for low-RAM
#     environments (free-tier cloud runners, laptops).
#   - The module never writes embeddings to disk — the caller (storage.py or
#     run_ingest.py) decides where to persist them.
#   - If sentence-transformers is unavailable, a clear ImportError is raised
#     with installation instructions.

from __future__ import annotations

import os
import logging
from typing import List

from .pdf_ingestor import Chunk

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default model: small, fast, good semantic quality.
DEFAULT_MODEL = "all-MiniLM-L6-v2"

# Batch size for encode() calls.  Increase on machines with more RAM / VRAM.
DEFAULT_BATCH_SIZE = 32

# ---------------------------------------------------------------------------
# Module-level model cache — loaded once per process
# ---------------------------------------------------------------------------

_model_cache: dict[str, object] = {}


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
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> List[List[float]]:
    """
    Generate embeddings for every chunk in *chunks*.

    Parameters
    ----------
    chunks     : List of Chunk objects whose ``.text`` fields will be embedded.
    model_name : sentence-transformers model name or path.
                 Defaults to the EMBED_MODEL env var, then "all-MiniLM-L6-v2".
    batch_size : Number of texts per encode() call.

    Returns
    -------
    A list of float lists, one per chunk, in the same order as *chunks*.
    Each inner list has length equal to the model's embedding dimension.

    Raises
    ------
    EmbeddingError : If sentence-transformers is not installed or encoding fails.
    ValueError     : If *chunks* is empty.
    """
    if not chunks:
        raise ValueError("embed_chunks requires at least one chunk; got empty list.")

    resolved_model = model_name or os.getenv("EMBED_MODEL", DEFAULT_MODEL)

    model = _load_model(resolved_model)

    texts = [chunk.text for chunk in chunks]

    logger.info(
        "Embedding %d chunks with model '%s' (batch_size=%d) …",
        len(texts),
        resolved_model,
        batch_size,
    )

    try:
        vectors = model.encode(  # type: ignore[union-attr]
            texts,
            batch_size=batch_size,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingError(
            f"Embedding generation failed: {exc}\n"
            "Check that sentence-transformers and torch are installed and the model"
            f" '{resolved_model}' is available."
        ) from exc

    # Convert numpy arrays to plain Python float lists for JSON-serialisability.
    return [v.tolist() for v in vectors]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _load_model(model_name: str) -> object:
    """
    Load (or return a cached) SentenceTransformer model.

    Raises EmbeddingError if sentence-transformers is not installed.
    """
    if model_name in _model_cache:
        return _model_cache[model_name]

    try:
        from sentence_transformers import SentenceTransformer  # type: ignore
    except ImportError as exc:
        raise EmbeddingError(
            "sentence-transformers is required for embedding generation.\n"
            "Install it with:  py -m pip install sentence-transformers"
        ) from exc

    logger.info("Loading embedding model '%s' …", model_name)
    try:
        model = SentenceTransformer(model_name)
    except Exception as exc:  # noqa: BLE001
        raise EmbeddingError(
            f"Failed to load embedding model '{model_name}': {exc}"
        ) from exc

    _model_cache[model_name] = model
    return model
