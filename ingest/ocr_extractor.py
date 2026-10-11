# ingest/ocr_extractor.py
#
# Local OCR extraction for Indux 5.0.
#
# Responsibility:
#   Extract text from image-only (scanned) PDF pages using Tesseract OCR.
#   Returns the same list-of-(page_number, text, bbox) tuples that
#   pdf_ingestor._extract_with_fitz / _extract_with_pypdf return, so the
#   existing chunking and metadata pipeline is reused unchanged.
#
# Design decisions:
#   - Uses PyMuPDF to render each page to a Pillow Image at 300 DPI
#     (the sweet spot for Tesseract accuracy on printed manuals).
#   - Uses pytesseract (Tesseract wrapper) for the actual OCR step.
#   - bbox is always None — Tesseract word-level boxes are not aggregated
#     here because the Round 2 highlight helper can fall back gracefully.
#   - The Tesseract executable path is read from the TESSERACT_CMD env var
#     (or the known Windows default), making it portable without editing code.
#   - No network calls, no API keys, no database writes.
#   - Import errors for pytesseract / Pillow produce an OcrError with
#     clear installation instructions.

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Public exception
# ---------------------------------------------------------------------------

class OcrError(Exception):
    """
    Raised when OCR extraction cannot proceed.
    The message describes the cause in plain language.
    """


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# DPI used when rasterising PDF pages before OCR.
# 300 is the standard recommendation for Tesseract on printed text.
OCR_DPI: int = 300

# Language(s) passed to Tesseract.  "eng" covers all Atlas Copco manuals.
OCR_LANG: str = "eng"

# Known default Tesseract path on Windows (UB-Mannheim installer).
_DEFAULT_TESSERACT_WIN = r"C:\Program Files\Tesseract-OCR\tesseract.exe"


# ---------------------------------------------------------------------------
# Public function
# ---------------------------------------------------------------------------

def ocr_pdf_pages(
    raw_bytes: bytes,
    *,
    dpi: int = OCR_DPI,
    lang: str = OCR_LANG,
    tesseract_cmd: Optional[str] = None,
) -> tuple[list[tuple[int, str, None]], int]:
    """
    OCR all pages of a PDF given its raw bytes.

    Parameters
    ----------
    raw_bytes      : Raw PDF file content.
    dpi            : Rasterisation resolution (default 300).
    lang           : Tesseract language code(s), e.g. "eng" or "eng+deu".
    tesseract_cmd  : Path to the tesseract executable.
                     Falls back to the TESSERACT_CMD env var, then the
                     Windows default path, then the system PATH.

    Returns
    -------
    (page_data, total_pages) where page_data is a list of
    (1-based page number, OCR text, None) tuples — the same shape that
    _extract_with_fitz and _extract_with_pypdf return, so the existing
    chunking pipeline can consume it without modification.

    Raises
    ------
    OcrError : If pytesseract, Pillow, or PyMuPDF are not installed, or if
               Tesseract is not found / fails to run.
    """
    _configure_tesseract(tesseract_cmd)

    try:
        import pytesseract  # type: ignore
    except ImportError as exc:
        raise OcrError(
            "pytesseract is required for OCR extraction.\n"
            "Install it with:  py -m pip install pytesseract"
        ) from exc

    try:
        from PIL import Image  # noqa: F401 — imported to verify Pillow is present
    except ImportError as exc:
        raise OcrError(
            "Pillow is required for OCR extraction.\n"
            "Install it with:  py -m pip install Pillow"
        ) from exc

    try:
        import pymupdf as fitz  # type: ignore
    except ImportError:
        try:
            import fitz  # type: ignore  # noqa: F401
        except ImportError as exc:
            raise OcrError(
                "PyMuPDF (pymupdf) is required for page rasterisation.\n"
                "Install it with:  py -m pip install pymupdf"
            ) from exc

    try:
        doc = fitz.open(stream=raw_bytes, filetype="pdf")
    except Exception as exc:
        raise OcrError(
            f"Could not open PDF for OCR rasterisation: {exc}"
        ) from exc

    total_pages = len(doc)
    if total_pages == 0:
        doc.close()
        raise OcrError("PDF contains no pages.")

    matrix = fitz.Matrix(dpi / 72, dpi / 72)  # scale factor for 72 dpi → target dpi

    page_data: list[tuple[int, str, None]] = []

    for i in range(total_pages):
        page_number = i + 1
        page = doc[i]
        try:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            # Convert PyMuPDF Pixmap to a Pillow Image via raw RGB bytes.
            from PIL import Image as PILImage
            img = PILImage.frombytes("RGB", (pix.width, pix.height), pix.samples)
            text: str = pytesseract.image_to_string(img, lang=lang)
            text = text.strip()
        except Exception as exc:  # noqa: BLE001
            logger.warning("OCR failed on page %d: %s", page_number, exc)
            text = ""

        page_data.append((page_number, text, None))
        logger.debug("OCR page %d/%d: %d chars", page_number, total_pages, len(text))

    doc.close()
    logger.info(
        "OCR complete: %d pages, %d with text.",
        total_pages,
        sum(1 for _, t, _ in page_data if t),
    )
    return page_data, total_pages


# ---------------------------------------------------------------------------
# Internal helper
# ---------------------------------------------------------------------------

def _configure_tesseract(tesseract_cmd: Optional[str]) -> None:
    """
    Set pytesseract.pytesseract.tesseract_cmd to the correct executable path.

    Priority order:
    1. Explicit argument (tesseract_cmd parameter)
    2. TESSERACT_CMD environment variable
    3. Known Windows default (C:\\Program Files\\Tesseract-OCR\\tesseract.exe)
    4. Leave as-is (uses system PATH — works on Linux/macOS and if added to PATH)
    """
    cmd = (
        tesseract_cmd
        or os.getenv("TESSERACT_CMD")
        or (_DEFAULT_TESSERACT_WIN if Path(_DEFAULT_TESSERACT_WIN).exists() else None)
    )
    if cmd:
        try:
            import pytesseract as _pt  # type: ignore
            _pt.pytesseract.tesseract_cmd = cmd
        except ImportError:
            pass  # ImportError will be raised in the caller
