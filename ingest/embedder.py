# ingest/embedder.py
#
# Batch embedding generation for Indux 5.0.
#
# Responsibility:
#   1. Accept a list of Chunk objects.
#   2. Call the Google Gemini embedding API (one request per chunk) and return
#      3072-dimensional float vectors aligned 1:1 with the chunks.
#
# Safety additions (all backward-compatible):
#   Rate limiting  — enforces a minimum inter-request delay (default: 0.7 s,
#                    ≈ 85 RPM, safely below the Gemini free-tier 100 RPM cap).
#                    Configurable via GEMINI_EMBED_RPM env var or embed_chunks()
#                    keyword argument.
#   Retry/backoff  — retries on 429 (rate-limit) and 5xx (transient) errors
#                    with capped exponential back-off and Retry-After parsing.
#                    Fails clearly after GEMINI_EMBED_MAX_RETRIES (default 4).
#   Checkpoints    — after each successful embedding the vector is appended to
#                    a local JSONL file in ingest/output/.checkpoints/.  On the
#                    next run the checkpoint is loaded and matching chunks are
#                    skipped, so a partial run can resume from where it failed.
#                    Checkpoints are keyed by (doc_id, model, embedding_dim).
#                    API keys are never stored in checkpoint files.
#
# Design decisions (unchanged from original):
#   - Uses google-genai SDK with model "gemini-embedding-001" (3072 dims) to
#     match ai/brain.py exactly.  Both ingest and retrieval must use the same
#     model so similarity search returns meaningful scores.
#   - GEMINI_API_KEY env var is required (loaded from ingest/.env via dotenv).
#   - batch_size is accepted for API compatibility but is not used; the Gemini
#     embedding API is called once per text.
#   - The module never writes final embeddings to a Supabase table; the caller
#     decides persistence (see storage.py).

from __future__ import annotations

import json
import logging
import os
import re
import time
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv

from .pdf_ingestor import Chunk

# Load from ingest/.env regardless of the working directory.
load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration constants
# ---------------------------------------------------------------------------

# Model name and output dimension — must match ai/brain.py exactly.
GEMINI_EMBED_MODEL = "gemini-embedding-001"
GEMINI_EMBED_DIM   = 3072

# Default inter-request delay (seconds).  60 / 0.7 ≈ 85 RPM, safely below
# the Gemini free-tier 100 RPM cap.
DEFAULT_EMBED_DELAY_S: float = 0.7

# Maximum retries for a single chunk before giving up.
DEFAULT_MAX_RETRIES: int = 4

# Back-off base multiplier (seconds): wait = BASE * 2^attempt (capped).
_BACKOFF_BASE_S: float = 2.0
_BACKOFF_CAP_S: float  = 60.0

# Directory for checkpoint files (relative to this module's parent directory).
_CHECKPOINT_DIR = Path(__file__).resolve().parent / "output" / ".checkpoints"

# ---------------------------------------------------------------------------
# Public types
# ---------------------------------------------------------------------------

class EmbeddingError(Exception):
    """
    Raised when embedding generation fails.
    The message describes the cause in plain language.
    """

# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def embed_chunks(
    chunks: List[Chunk],
    *,
    model_name: Optional[str] = None,
    batch_size: int = 32,           # kept for API compatibility; not used
    delay_s: Optional[float] = None,
    max_retries: Optional[int] = None,
    checkpoint: bool = True,
) -> List[List[float]]:
    """
    Generate 3072-dimensional Gemini embeddings for every chunk.

    Parameters
    ----------
    chunks      : List of Chunk objects whose ``.text`` fields will be embedded.
    model_name  : Gemini embedding model name.
                  Defaults to the GEMINI_EMBED_MODEL env var, then
                  "gemini-embedding-001".
    batch_size  : Accepted for API compatibility but ignored.
    delay_s     : Minimum seconds between API requests.
                  Defaults to the GEMINI_EMBED_DELAY_S env var, then 0.7 s.
                  Set to 0.0 to disable throttling (not recommended on free tier).
    max_retries : Maximum retries per chunk on 429 / 5xx errors.
                  Defaults to the GEMINI_EMBED_MAX_RETRIES env var, then 4.
    checkpoint  : If True (default), save each embedding to a local JSONL
                  checkpoint and skip already-embedded chunks on resume.
                  Set to False to disable checkpoint I/O entirely.

    Returns
    -------
    A list of float lists, one per chunk, each with length 3072.

    Raises
    ------
    EmbeddingError : If google-genai is not installed, GEMINI_API_KEY is
                     missing, the API call fails after all retries, or the
                     checkpoint file is corrupt.
    ValueError     : If *chunks* is empty.
    """
    if not chunks:
        raise ValueError("embed_chunks requires at least one chunk; got empty list.")

    resolved_model = model_name or os.getenv("GEMINI_EMBED_MODEL", GEMINI_EMBED_MODEL)
    resolved_delay  = _resolve_delay(delay_s)
    resolved_retries = _resolve_retries(max_retries)

    api_key = os.getenv("GEMINI_API_KEY", "")
    if not api_key:
        raise EmbeddingError(
            "GEMINI_API_KEY is not set.  "
            "Add it to ingest/.env or export it before running ingestion:\n"
            "  $env:GEMINI_API_KEY = 'AIza...'"
        )

    client = _get_genai_client(api_key)

    # --- Determine doc_id for the checkpoint key ----------------------------
    # All chunks in a single embed_chunks() call must share the same doc_id.
    doc_ids = {c.doc_id for c in chunks}
    doc_id = doc_ids.pop() if len(doc_ids) == 1 else "_multi_"

    # --- Load existing checkpoint -------------------------------------------
    ckpt: Optional[_Checkpoint] = None
    if checkpoint:
        ckpt = _Checkpoint.load(
            doc_id=doc_id,
            model=resolved_model,
            dim=GEMINI_EMBED_DIM,
        )

    logger.info(
        "Embedding %d chunks with Gemini model '%s' "
        "(delay=%.2fs, max_retries=%d, checkpoint=%s) ...",
        len(chunks), resolved_model, resolved_delay, resolved_retries,
        "on" if ckpt is not None else "off",
    )

    embeddings: List[List[float]] = [None] * len(chunks)  # type: ignore[list-item]
    last_request_time: float = 0.0
    skipped = 0

    for i, chunk in enumerate(chunks):
        # --- Resume: use cached vector if available -------------------------
        if ckpt is not None:
            cached = ckpt.get(chunk.chunk_id)
            if cached is not None:
                embeddings[i] = cached
                skipped += 1
                continue

        # --- Rate-limit: enforce minimum inter-request delay ----------------
        if resolved_delay > 0:
            elapsed = time.monotonic() - last_request_time
            wait = resolved_delay - elapsed
            if wait > 0:
                time.sleep(wait)

        # --- Call API with retry/backoff ------------------------------------
        values = _embed_one(
            client=client,
            text=chunk.text,
            model=resolved_model,
            chunk_id=chunk.chunk_id,
            chunk_index=i,
            max_retries=resolved_retries,
        )
        last_request_time = time.monotonic()

        embeddings[i] = values

        # --- Persist to checkpoint immediately ------------------------------
        if ckpt is not None:
            ckpt.put(chunk.chunk_id, values)
            ckpt.flush()

        if (i + 1) % 50 == 0:
            logger.info("  ... embedded %d / %d chunks", i + 1, len(chunks))

    if skipped:
        logger.info("  Resumed from checkpoint: %d chunks skipped.", skipped)

    logger.info(
        "Embedding complete. %d vectors, dimension %d.",
        len(embeddings),
        len(embeddings[0]) if embeddings else 0,
    )

    # Clean up checkpoint file on full success.
    if ckpt is not None:
        ckpt.delete()

    return embeddings


# ---------------------------------------------------------------------------
# Internal: single-chunk API call with retry / backoff
# ---------------------------------------------------------------------------

def _embed_one(
    *,
    client: object,
    text: str,
    model: str,
    chunk_id: str,
    chunk_index: int,
    max_retries: int,
) -> List[float]:
    """
    Call the Gemini embedding API for one text, retrying on transient errors.

    Retries on HTTP 429 (rate limit) and 5xx (server error).
    Respects the ``Retry-After`` header when present in the error message.
    Raises EmbeddingError after *max_retries* failed attempts.
    """
    for attempt in range(1, max_retries + 2):  # attempt 1..max_retries+1
        try:
            response = client.models.embed_content(  # type: ignore[attr-defined]
                model=model,
                contents=text,
            )
            values = list(response.embeddings[0].values)
            return values
        except Exception as exc:  # noqa: BLE001
            msg = str(exc)
            is_retryable = _is_retryable_error(msg)

            if not is_retryable or attempt > max_retries:
                raise EmbeddingError(
                    f"Gemini embedding failed on chunk {chunk_index} "
                    f"(chunk_id={chunk_id!r}) after {attempt} attempt(s): {exc}"
                ) from exc

            wait = _backoff_delay(msg, attempt)
            logger.warning(
                "Retryable error on chunk %d (chunk_id=%r, attempt %d/%d). "
                "Waiting %.1fs before retry: %s",
                chunk_index, chunk_id, attempt, max_retries, wait, msg,
            )
            time.sleep(wait)

    # Unreachable, but satisfies type checkers.
    raise EmbeddingError(f"Embedding failed for chunk_id={chunk_id!r}")  # pragma: no cover


def _is_retryable_error(msg: str) -> bool:
    """Return True for 429, 5xx, connection-reset, and other transient errors."""
    lower = msg.lower()
    return bool(
        re.search(r"\b429\b", msg)
        or re.search(r"\b5[0-9]{2}\b", msg)
        or "quota" in lower
        or re.search(r"rate[\s_\-]?limit", lower)
        or re.search(r"resource[\s_\-]?exhausted", lower)
        or re.search(r"service[\s_\-]?unavailable", lower)
        or re.search(r"internal[\s_\-]?server", lower)
        # Network-level transient errors (WinError 10054, connection reset, timeout)
        or "connection" in lower and "reset" in lower
        or "connection" in lower and "closed" in lower
        or "connectionreset" in lower
        or "winerror 10054" in lower
        or "winerror 10053" in lower
        or "connection aborted" in lower
        or "broken pipe" in lower
        or "timed out" in lower
        or re.search(r"winerror\s+\d+", lower)
    )


def _backoff_delay(error_msg: str, attempt: int) -> float:
    """
    Calculate the delay before the next retry.

    Checks for a ``Retry-After`` value in the error message first.
    Falls back to capped exponential back-off: BASE * 2^(attempt-1).
    """
    retry_after = _parse_retry_after(error_msg)
    if retry_after is not None:
        return min(retry_after, _BACKOFF_CAP_S)
    raw = _BACKOFF_BASE_S * (2 ** (attempt - 1))
    return min(raw, _BACKOFF_CAP_S)


def _parse_retry_after(msg: str) -> Optional[float]:
    """
    Extract a ``Retry-After`` value from an error message.

    Looks for patterns like:
      "Retry-After: 30"
      "retry_after=15"
      "retry after 10 seconds"
    Returns seconds as a float, or None if not found.
    """
    # Header-style: Retry-After: 30  or  retry-after=30
    m = re.search(r"retry.?after[=:\s]+([0-9]+(?:\.[0-9]+)?)", msg, re.IGNORECASE)
    if m:
        return float(m.group(1))
    return None


# ---------------------------------------------------------------------------
# Internal: configuration resolution
# ---------------------------------------------------------------------------

def _resolve_delay(delay_s: Optional[float]) -> float:
    if delay_s is not None:
        return max(0.0, delay_s)
    env_val = os.getenv("GEMINI_EMBED_DELAY_S")
    if env_val is not None:
        try:
            return max(0.0, float(env_val))
        except ValueError:
            pass
    return DEFAULT_EMBED_DELAY_S


def _resolve_retries(max_retries: Optional[int]) -> int:
    if max_retries is not None:
        return max(0, int(max_retries))
    env_val = os.getenv("GEMINI_EMBED_MAX_RETRIES")
    if env_val is not None:
        try:
            return max(0, int(env_val))
        except ValueError:
            pass
    return DEFAULT_MAX_RETRIES


# ---------------------------------------------------------------------------
# Internal: checkpoint
# ---------------------------------------------------------------------------

class _Checkpoint:
    """
    A JSONL file that records successfully computed embeddings for one
    (doc_id, model, dim) combination.

    Each line is a JSON object:
      {"chunk_id": "...", "embedding": [...]}

    Metadata (doc_id, model, dim) is stored in the first line as:
      {"_meta": true, "doc_id": "...", "model": "...", "dim": 3072}

    API keys are never stored.
    """

    def __init__(self, path: Path, doc_id: str, model: str, dim: int) -> None:
        self._path   = path
        self._doc_id = doc_id
        self._model  = model
        self._dim    = dim
        self._cache: dict[str, List[float]] = {}
        self._fh = None   # opened lazily on first put()

    # --- Factory methods ----------------------------------------------------

    @classmethod
    def load(cls, *, doc_id: str, model: str, dim: int) -> "_Checkpoint":
        """
        Load an existing checkpoint or create a new empty one.

        If the file exists but has a mismatched model or dim, the stale
        checkpoint is discarded (logged as a warning) and a fresh one is
        returned.
        """
        path = _checkpoint_path(doc_id, model)
        ckpt = cls(path=path, doc_id=doc_id, model=model, dim=dim)

        if not path.exists():
            logger.debug("No checkpoint found at '%s'.", path)
            return ckpt

        try:
            ckpt._load_from_file()
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "Discarding unreadable checkpoint '%s': %s", path, exc
            )
            ckpt._cache.clear()
            try:
                path.unlink()
            except OSError:
                pass

        return ckpt

    def _load_from_file(self) -> None:
        """Read and validate the checkpoint file into self._cache."""
        lines = self._path.read_text(encoding="utf-8").splitlines()
        if not lines:
            return

        # First line must be the metadata record.
        meta = json.loads(lines[0])
        if not meta.get("_meta"):
            raise ValueError("First line is not a metadata record.")

        saved_model = meta.get("model", "")
        saved_dim   = int(meta.get("dim", 0))

        if saved_model != self._model or saved_dim != self._dim:
            raise ValueError(
                f"Checkpoint model/dim mismatch: "
                f"saved=({saved_model!r}, {saved_dim}) "
                f"expected=({self._model!r}, {self._dim})"
            )

        loaded = 0
        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            cid = rec.get("chunk_id")
            emb = rec.get("embedding")
            if cid and isinstance(emb, list) and len(emb) == self._dim:
                self._cache[cid] = emb
                loaded += 1

        logger.info(
            "Loaded %d embeddings from checkpoint '%s'.", loaded, self._path
        )

    # --- Access methods -----------------------------------------------------

    def get(self, chunk_id: str) -> Optional[List[float]]:
        """Return a cached embedding or None."""
        return self._cache.get(chunk_id)

    def put(self, chunk_id: str, embedding: List[float]) -> None:
        """Add a newly computed embedding to the in-memory cache."""
        self._cache[chunk_id] = embedding
        # Stage for writing; flush() commits to disk.
        self._pending = getattr(self, "_pending", [])
        self._pending.append({"chunk_id": chunk_id, "embedding": embedding})

    def flush(self) -> None:
        """Append pending entries to the checkpoint file."""
        pending = getattr(self, "_pending", [])
        if not pending:
            return

        _CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)

        # Open in append mode; write metadata header only on first open.
        write_header = not self._path.exists()
        with self._path.open("a", encoding="utf-8") as fh:
            if write_header:
                meta = {
                    "_meta": True,
                    "doc_id": self._doc_id,
                    "model": self._model,
                    "dim": self._dim,
                    # Deliberately omit any API key or secret.
                }
                fh.write(json.dumps(meta, ensure_ascii=False) + "\n")
            for rec in pending:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")

        self._pending = []

    def delete(self) -> None:
        """Remove the checkpoint file after a successful full run."""
        if self._path.exists():
            try:
                self._path.unlink()
                logger.debug("Checkpoint '%s' deleted after successful run.", self._path)
            except OSError as exc:
                logger.warning("Could not delete checkpoint '%s': %s", self._path, exc)


# ---------------------------------------------------------------------------
# Internal: helpers
# ---------------------------------------------------------------------------

def _checkpoint_path(doc_id: str, model: str) -> Path:
    """Return the Path for a checkpoint file given doc_id and model name."""
    safe_doc = re.sub(r"[^A-Za-z0-9_\-]", "_", doc_id)[:60]
    safe_model = re.sub(r"[^A-Za-z0-9_\-]", "_", model)[:40]
    return _CHECKPOINT_DIR / f"{safe_doc}__{safe_model}.jsonl"


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
