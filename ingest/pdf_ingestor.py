# ingest/pdf_ingestor.py
#
# Core PDF ingestion module for Indux 5.0.
#
# Responsibility:
#   1. Validate an uploaded PDF file (exists, correct format, not empty).
#   2. Extract text page-by-page using PyMuPDF (fitz) for bounding-box metadata,
#      falling back to pypdf for compatibility where fitz is unavailable.
#   3. Detect troubleshooting tables and keep each row (problem/cause/remedy) as
#      its own atomic chunk wherever feasible.
#   4. Split the extracted text into overlapping chunks.
#   5. Attach stable document IDs, page numbers, chunk IDs, bounding-box
#      positions, and chunk_type to every chunk.
#   6. Return a structured result that the AI retrieval system can consume.
#
# Design decisions:
#   - PyMuPDF (pymupdf/fitz) is the primary extractor because it exposes per-word
#     bounding boxes, which are stored as positional metadata on each chunk.  This
#     lets the highlight helper (Round 2) draw precise highlights on PDF pages.
#   - pypdf is kept as a fallback so the module still works in environments where
#     PyMuPDF cannot be installed.
#   - Troubleshooting tables are identified heuristically: sections whose heading
#     contains "troubleshoot", "fault", "error code", "problem", "cause", or
#     "remedy" are parsed row-by-row so the problem + cause + remedy context is
#     never split across different chunks.
#   - Scanned image-only PDFs will yield empty text; the result reports this
#     clearly rather than silently returning empty chunks.
#   - No OCR is included (out of scope for this task).
#   - No database writes are done here; see storage.py.

from __future__ import annotations

import io
import os
import re
import hashlib
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

# ---------------------------------------------------------------------------
# Optional PyMuPDF import (preferred extractor)
# ---------------------------------------------------------------------------

try:
    import pymupdf as fitz          # pymupdf >= 1.24 recommends this alias
    _HAVE_FITZ = True
except ImportError:
    try:
        import fitz                  # older pymupdf still uses fitz
        _HAVE_FITZ = True
    except ImportError:
        _HAVE_FITZ = False

# ---------------------------------------------------------------------------
# Required pypdf import (fallback extractor + PDF writer used in tests)
# ---------------------------------------------------------------------------

try:
    from pypdf import PdfReader
    from pypdf.errors import PdfReadError
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "pypdf is required for PDF ingestion.\n"
        "Install it with:  py -m pip install pypdf"
    ) from exc


# ---------------------------------------------------------------------------
# Public data types
# ---------------------------------------------------------------------------

@dataclass
class BoundingBox:
    """
    Axis-aligned bounding rectangle of extracted text on a PDF page.

    All coordinates are in PDF user-space points (1 pt = 1/72 inch),
    measured from the bottom-left of the page (PyMuPDF convention).

    Attributes
    ----------
    x0, y0 : Lower-left corner of the box.
    x1, y1 : Upper-right corner of the box.
    """
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class Chunk:
    """
    A single piece of text extracted from a PDF, ready for embedding.

    Attributes
    ----------
    text         : The actual text content of this chunk.
    doc_id       : A stable identifier for the source document
                   (SHA-256 of the file content, or a caller-supplied name).
    page_number  : 1-based page number where this chunk originates.
    chunk_index  : 0-based position of this chunk within the document.
    chunk_id     : Unique string ID: "{doc_id}_{chunk_index:05d}".
    bbox         : Optional bounding box of the text on the page (PyMuPDF
                   only).  None when falling back to pypdf.
    chunk_type   : One of "text" | "troubleshooting_row".
    """
    text: str
    doc_id: str
    page_number: int
    chunk_index: int
    chunk_id: str = field(default="")
    bbox: Optional[BoundingBox] = field(default=None)
    chunk_type: str = field(default="text")

    def __post_init__(self) -> None:
        if not self.chunk_id:
            self.chunk_id = f"{self.doc_id}_{self.chunk_index:05d}"


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
    extractor_used  : "pymupdf" | "pypdf" depending on which backend ran.
    """
    doc_id: str
    total_pages: int
    chunks: List[Chunk]
    empty_pages: List[int] = field(default_factory=list)
    scanned_warning: bool = False
    extractor_used: str = field(default="pypdf")


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
CHUNK_OVERLAP: int = 150

# Heading keywords that indicate a troubleshooting section.
_TROUBLESHOOT_KEYWORDS = re.compile(
    r"\b(troubleshoot|fault|error\s*code|problem|cause|remedy|symptom|alarm)\b",
    re.IGNORECASE,
)

# Minimum word count for a page to be considered text-bearing (not just
# page numbers / headers).
_MIN_WORDS_PER_PAGE = 5


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
    IngestError  : For missing files, wrong format, unreadable PDFs, empty
                   files, or image-only (scanned) PDFs that produced no text
                   on *any* page.
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

    # --- Extract text and metadata page by page ----------------------------
    if _HAVE_FITZ:
        page_data, total_pages, extractor_used = _extract_with_fitz(raw_bytes)
    else:
        page_data, total_pages, extractor_used = _extract_with_pypdf(raw_bytes)

    # page_data: list of (page_number, text, bbox_or_None)
    empty_pages = [pn for pn, txt, _bbox in page_data if not txt.strip()]
    page_texts  = [(pn, txt, bbox) for pn, txt, bbox in page_data if txt.strip()]

    scanned_warning = len(page_texts) == 0

    # --- Build chunks -------------------------------------------------------
    chunks: list[Chunk] = []
    chunk_index = 0

    for page_number, text, page_bbox in page_texts:
        # Detect troubleshooting sections and extract rows first.
        ts_rows = _extract_troubleshooting_rows(text)
        if ts_rows:
            for row_text in ts_rows:
                chunks.append(
                    Chunk(
                        text=row_text,
                        doc_id=doc_id,
                        page_number=page_number,
                        chunk_index=chunk_index,
                        bbox=page_bbox,  # page-level bbox; row-level not available
                        chunk_type="troubleshooting_row",
                    )
                )
                chunk_index += 1
            # Also add a fallback regular split for any text outside the table.
            remaining = _remove_troubleshooting_rows(text)
            if remaining.strip():
                for chunk_text in _split_text(remaining, chunk_size, chunk_overlap):
                    chunks.append(
                        Chunk(
                            text=chunk_text,
                            doc_id=doc_id,
                            page_number=page_number,
                            chunk_index=chunk_index,
                            bbox=page_bbox,
                            chunk_type="text",
                        )
                    )
                    chunk_index += 1
        else:
            for chunk_text in _split_text(text, chunk_size, chunk_overlap):
                chunks.append(
                    Chunk(
                        text=chunk_text,
                        doc_id=doc_id,
                        page_number=page_number,
                        chunk_index=chunk_index,
                        bbox=page_bbox,
                        chunk_type="text",
                    )
                )
                chunk_index += 1

    return IngestResult(
        doc_id=doc_id,
        total_pages=total_pages,
        chunks=chunks,
        empty_pages=empty_pages,
        scanned_warning=scanned_warning,
        extractor_used=extractor_used,
    )


# ---------------------------------------------------------------------------
# Internal: PyMuPDF extraction
# ---------------------------------------------------------------------------

def _extract_with_fitz(
    raw_bytes: bytes,
) -> Tuple[list[tuple[int, str, Optional[BoundingBox]]], int, str]:
    """
    Extract text + bounding boxes using PyMuPDF.

    Returns a list of (1-based page number, page text, BoundingBox | None)
    tuples, plus total page count and the extractor name string.
    """
    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
    except Exception as exc:
        raise IngestError(
            f"Could not open PDF with PyMuPDF (file may be corrupt or encrypted): {exc}"
        ) from exc

    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise IngestError("PDF contains no pages.")

    results: list[tuple[int, str, Optional[BoundingBox]]] = []

    for i in range(total_pages):
        page_number = i + 1
        page = doc[i]
        try:
            # get_text("text") returns the full page text.
            text: str = page.get_text("text") or ""
            text = text.strip()

            # Compute an overall bounding box for the page's text blocks.
            bbox: Optional[BoundingBox] = None
            if text:
                blocks = page.get_text("blocks")  # (x0, y0, x1, y1, text, …)
                if blocks:
                    x0 = min(b[0] for b in blocks)
                    y0 = min(b[1] for b in blocks)
                    x1 = max(b[2] for b in blocks)
                    y1 = max(b[3] for b in blocks)
                    bbox = BoundingBox(x0=x0, y0=y0, x1=x1, y1=y1)
        except Exception:  # noqa: BLE001 — malformed page; skip gracefully
            text = ""
            bbox = None

        results.append((page_number, text, bbox))

    doc.close()
    return results, total_pages, "pymupdf"


# ---------------------------------------------------------------------------
# Internal: pypdf fallback extraction
# ---------------------------------------------------------------------------

def _extract_with_pypdf(
    raw_bytes: bytes,
) -> Tuple[list[tuple[int, str, Optional[BoundingBox]]], int, str]:
    """
    Extract text using pypdf (no bounding boxes).

    Returns a list of (1-based page number, page text, None) tuples, plus
    total page count and the extractor name string.
    """
    try:
        reader = PdfReader(io.BytesIO(raw_bytes))
    except PdfReadError as exc:
        raise IngestError(
            f"Could not read PDF (file may be corrupt or encrypted): {exc}"
        ) from exc
    except Exception as exc:  # noqa: BLE001
        raise IngestError(f"Unexpected error reading PDF: {exc}") from exc

    total_pages = len(reader.pages)
    if total_pages == 0:
        raise IngestError("PDF contains no pages.")

    results: list[tuple[int, str, Optional[BoundingBox]]] = []

    for i, page in enumerate(reader.pages):
        page_number = i + 1
        try:
            text = page.extract_text() or ""
        except Exception:  # noqa: BLE001
            text = ""
        results.append((page_number, text.strip(), None))

    return results, total_pages, "pypdf"


# ---------------------------------------------------------------------------
# Internal: troubleshooting table helpers
# ---------------------------------------------------------------------------

# Pattern that matches a common troubleshooting row header like:
#   "Problem:", "Cause:", "Remedy:", "Symptom:", "Action:", "Solution:"
# followed by content.  We look for at least two of these in a block.
_TS_LABEL = re.compile(
    r"(?i)^(problem|symptom|cause|remedy|action|solution|fault|error)\s*[:\-–—]",
    re.MULTILINE,
)

# Separator between rows (e.g. blank line or a line of dashes)
_TS_ROW_SEP = re.compile(r"\n{2,}|\n[-=_]{3,}\n")


def _extract_troubleshooting_rows(text: str) -> list[str]:
    """
    If *text* looks like a troubleshooting table, split it into individual
    rows where each row keeps the problem + cause + remedy together.

    Returns an empty list if the text does not look like a troubleshooting
    table (the caller should fall through to normal chunking).
    """
    # Require a troubleshooting keyword in the heading area (first 200 chars
    # or the whole text if shorter).
    if not _TROUBLESHOOT_KEYWORDS.search(text[:200] or text):
        return []

    # Count how many labelled rows (Problem: / Cause: / Remedy:) we can find.
    label_matches = _TS_LABEL.findall(text)
    if len(label_matches) < 2:
        return []

    # Split into candidate row blocks.
    raw_blocks = _TS_ROW_SEP.split(text)
    rows: list[str] = []
    for block in raw_blocks:
        block = block.strip()
        if block and _TS_LABEL.search(block):
            rows.append(block)

    # Only return rows if we found at least 2 — otherwise it is a false
    # positive and normal chunking is preferred.
    return rows if len(rows) >= 2 else []


def _remove_troubleshooting_rows(text: str) -> str:
    """
    Remove troubleshooting row blocks from *text*, leaving only the
    surrounding prose (headings, notes, etc.).
    """
    raw_blocks = _TS_ROW_SEP.split(text)
    non_ts: list[str] = []
    for block in raw_blocks:
        if block.strip() and not _TS_LABEL.search(block.strip()):
            non_ts.append(block.strip())
    return "\n\n".join(non_ts)


# ---------------------------------------------------------------------------
# Internal: text splitting helper
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
