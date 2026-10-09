# ingest/pdf_ingestor.py
#
# Core PDF ingestion module for Indux 5.0.
#
# Responsibility:
#   1. Validate an uploaded PDF file (exists, correct format, not empty).
#   2. Extract text page-by-page using pypdf (lightweight, pure-Python).
#   3. Split the extracted text into overlapping chunks.
#   4. Attach source metadata (document ID + page number) to every chunk.
#   5. Return a structured result that the AI retrieval system can consume.
#
# Design decisions:
#   - pypdf is used instead of PyMuPDF/pdfminer because it is pure-Python,
#     has no C-extension build requirements, and handles the majority of
#     digitally-created PDFs that factory manuals use.
#   - Scanned image-only PDFs will yield empty text; the result reports this
#     clearly rather than silently returning empty chunks.
#   - No OCR is included (out of scope for this task).
#   - No database writes are done here; the caller (backend integration or
#     storage layer) decides what to do with the returned chunks.

from __future__ import annotations

import os
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pypdf is required for PDF ingestion.\n"
        "Install it with:  python -m pip install pypdf"
    ) from exc


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class Chunk:
    """
    A single piece of text extracted from a PDF, ready for embedding.

    Attributes
    ----------
    text        : The actual text content of this chunk.
    doc_id      : A stable identifier for the source document
                  (SHA-256 of the file content, or a caller-supplied name).
    page_number : 1-based page number where this chunk begins.
    chunk_index : 0-based position of this chunk within the document.
    """
    text: str
    doc_id: str
    page_number: int
    chunk_index: int


@dataclass
class IngestResult:
    """
    Everything returned from a successful ingestion run.

    Attributes
    ----------
    doc_id          : Stable document identifier (SHA-256 hash of file bytes).
    total_pages     : Number of pages in the PDF.
    chunks          : List of Chunk objects ready for embedding.
    empty_pages     : 1-based page numbers that contained no extractable text.
    scanned_warning : True when the entire PDF produced no text (likely scanned).
    """
    doc_id: str
    total_pages: int
    chunks: List[Chunk]
    empty_pages: List[int] = field(default_factory=list)
    scanned_warning: bool = False


class IngestError(Exception):
    """
    Raised when ingestion cannot proceed due to a file or format problem.
    The message describes the specific problem in plain language.
    """


# ---------------------------------------------------------------------------
# Configuration constants  (easy to change without touching logic)
# ---------------------------------------------------------------------------

# Maximum characters per chunk before it is split further.
CHUNK_SIZE: int = 800

# Number of characters that overlap between consecutive chunks.
# Overlap ensures that context at chunk boundaries is not lost.
CHUNK_OVERLAP: int = 150


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def ingest_pdf(
    pdf_path: str | os.PathLike,
    *,
    doc_id: Optional[str] = None,
    chunk_size: int = CHUNK_SIZE,
    chunk_overlap: int = CHUNK_OVERLAP,
) -> IngestResult:
    """
    Ingest a PDF file and return structured chunks with metadata.

    Parameters
    ----------
    pdf_path     : Path to the PDF file on disk.
    doc_id       : Optional caller-supplied document identifier.
                   If omitted, a SHA-256 hash of the file content is used.
    chunk_size   : Maximum number of characters per chunk.
    chunk_overlap: Characters of overlap between consecutive chunks.

    Returns
    -------
    IngestResult containing the chunks and metadata.

    Raises
    ------
    IngestError  : For missing files, wrong format, unreadable PDFs, or
                   empty files.
    ValueError   : If chunk_size or chunk_overlap are invalid.
    """
    # --- Validate parameters -----------------------------------------------
    if chunk_size < 1:
        raise ValueError(f"chunk_size must be at least 1, got {chunk_size}")
    if chunk_overlap < 0:
        raise ValueError(f"chunk_overlap must be non-negative, got {chunk_overlap}")
    if chunk_overlap >= chunk_size:
        raise ValueError(
            f"chunk_overlap ({chunk_overlap}) must be less than chunk_size ({chunk_size})"
        )

    pdf_path = Path(pdf_path)

    # --- Validate the file -------------------------------------------------
    if not pdf_path.exists():
        raise IngestError(f"File not found: {pdf_path}")

    if not pdf_path.is_file():
        raise IngestError(f"Path is not a file: {pdf_path}")

    if pdf_path.stat().st_size == 0:
        raise IngestError(f"File is empty (0 bytes): {pdf_path}")

    # Read raw bytes once — used for both the header check and the hash.
    raw_bytes = pdf_path.read_bytes()

    # PDFs must start with the %PDF- magic bytes.
    if not raw_bytes.startswith(b"%PDF-"):
        raise IngestError(
            f"File does not appear to be a valid PDF (missing %PDF- header): {pdf_path}"
        )

    # --- Compute stable document ID ----------------------------------------
    if doc_id is None:
        doc_id = hashlib.sha256(raw_bytes).hexdigest()

    # --- Parse the PDF -----------------------------------------------------
    try:
        import io
        reader = PdfReader(io.BytesIO(raw_bytes))
    except PdfReadError as exc:
        raise IngestError(f"Could not read PDF (file may be corrupt or encrypted): {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Unexpected error reading PDF: {exc}") from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise IngestError("PDF contains no pages.")

    # --- Extract text page by page -----------------------------------------
    # page_texts is a list of (1-based-page-number, text) tuples.
    page_texts: list[tuple[int, str]] = []
    empty_pages: list[int] = []

    for i, page in enumerate(reader.pages):
        page_number = i + 1  # convert to 1-based
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001  — malformed page; skip gracefully
            text = ""

        # Normalise whitespace: collapse runs of blank lines, strip edges.
        text = text.strip()

        if text:
            page_texts.append((page_number, text))
        else:
            empty_pages.append(page_number)

    # Detect scanned PDFs (no text extracted from any page).
    scanned_warning = len(page_texts) == 0

    # --- Split text into chunks --------------------------------------------
    chunks: list[Chunk] = []
    chunk_index = 0

    for page_number, text in page_texts:
        page_chunks = _split_text(text, chunk_size, chunk_overlap)
        for chunk_text in page_chunks:
            chunks.append(
                Chunk(
                    text=chunk_text,
                    doc_id=doc_id,
                    page_number=page_number,
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1

    return IngestResult(
        doc_id=doc_id,
        total_pages=total_pages,
        chunks=chunks,
        empty_pages=empty_pages,
        scanned_warning=scanned_warning,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _split_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    """
    Split *text* into a list of overlapping chunks.

    Each chunk is at most *chunk_size* characters long.
    Consecutive chunks share *chunk_overlap* characters so that sentences
    that fall at a boundary appear in both the preceding and following chunk.

    Example with chunk_size=10, overlap=3, text="ABCDEFGHIJKLMNOP":
        ["ABCDEFGHIJ", "HIJKLMNOP"]  (H-I-J are the overlap)
    """
    if not text:
        return []

    chunks: list[str] = []
    start = 0
    step = chunk_size - chunk_overlap  # how far we advance each iteration

    while start < len(text):
        end = start + chunk_size
        chunk = text[start:end].strip()
        if chunk:          # skip chunks that are only whitespace
            chunks.append(chunk)
        start += step

    return chunks
