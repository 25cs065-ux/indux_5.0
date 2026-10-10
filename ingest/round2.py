# ingest/round2.py
#
# Round 2 additions for Indux 5.0 ingestion pipeline.
#
# Features:
#   1. save_page_images()  — render PDF pages to PNG using PyMuPDF
#   2. describe_pages()    — optional Gemini visual page description
#   3. tag_safety_chunks() — tag chunks containing safety-critical language
#   4. highlight_pdf()     — annotate a PDF page with bbox highlights
#
# All Round 2 features are **optional** — basic ingestion (pdf_ingestor.py +
# embedder.py + storage.py) continues to work without them.
#
# Environment variables:
#   GEMINI_API_KEY  : Google AI Studio key for Gemini (required by describe_pages)
#   GEMINI_MODEL    : Model name (default: gemini-1.5-flash)
#   GEMINI_RPM      : Requests per minute rate limit (default: 15)

from __future__ import annotations

import base64
import logging
import os
import re
import time
from pathlib import Path
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Safety keyword configuration
# ---------------------------------------------------------------------------

# Patterns that mark a chunk as safety-critical.
_SAFETY_PATTERNS = re.compile(
    r"\b("
    r"danger|warning|caution|hazard|risk|safety|emergency|"
    r"lockout|tagout|LOTO|PPE|protective equipment|"
    r"electric shock|electrocution|explosion|fire|"
    r"toxic|poison|asphyxia|asphyxiation|"
    r"do not operate|shut down immediately|stop the machine|"
    r"high voltage|high pressure|hot surface|burn|scald|"
    r"eye protection|hard hat|safety boot|glove|"
    r"first aid|evacuation|fire exit|extinguisher"
    r")\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# 1. Page-image export
# ---------------------------------------------------------------------------

class ImageExportError(Exception):
    """Raised when page-image export fails."""


def save_page_images(
    pdf_path: str | os.PathLike,
    output_dir: str | os.PathLike,
    *,
    dpi: int = 150,
    page_numbers: Optional[List[int]] = None,
    fmt: str = "png",
) -> List[Path]:
    """
    Render PDF pages to images and save them to *output_dir*.

    Parameters
    ----------
    pdf_path     : Path to the source PDF.
    output_dir   : Directory to write images into (created if missing).
    dpi          : Render resolution in dots per inch (default 150).
    page_numbers : 1-based list of pages to render.  If None, all pages.
    fmt          : Image format: "png" (default) or "jpg".

    Returns
    -------
    List of Paths to the written image files, in page order.

    Raises
    ------
    ImageExportError : If PyMuPDF is unavailable or the PDF cannot be opened.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError as exc:
            raise ImageExportError(
                "PyMuPDF is required for page-image export.\n"
                "Install it with:  py -m pip install pymupdf"
            ) from exc

    pdf_path = Path(pdf_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    try:
        doc = fitz.open(str(pdf_path))
    except Exception as exc:
        raise ImageExportError(f"Cannot open '{pdf_path}': {exc}") from exc

    total = len(doc)
    if page_numbers is None:
        page_numbers = list(range(1, total + 1))

    mat = fitz.Matrix(dpi / 72, dpi / 72)  # 72 dpi is PDF native
    written: List[Path] = []

    for pn in page_numbers:
        if not (1 <= pn <= total):
            logger.warning("Page %d out of range (1–%d) — skipped.", pn, total)
            continue
        page = doc[pn - 1]
        clip = page.get_pixmap(matrix=mat)
        stem = f"{pdf_path.stem}_p{pn:04d}.{fmt}"
        out_path = output_dir / stem
        if fmt == "png":
            clip.save(str(out_path))
        else:
            clip.save(str(out_path), jpg_quality=85)
        written.append(out_path)
        logger.debug("Saved page %d → %s", pn, out_path)

    doc.close()
    logger.info("Saved %d page image(s) to '%s'.", len(written), output_dir)
    return written


# ---------------------------------------------------------------------------
# 2. Gemini visual page description
# ---------------------------------------------------------------------------

class GeminiError(Exception):
    """Raised when the Gemini API call fails."""


def describe_pages(
    image_paths: List[Path],
    *,
    api_key: Optional[str] = None,
    model: Optional[str] = None,
    rpm: int = 0,
    prompt: str = (
        "Describe the content of this machine manual page briefly. "
        "Focus on any diagrams, tables, or safety warnings."
    ),
    max_retries: int = 3,
) -> Dict[Path, str]:
    """
    Generate text descriptions for page images using Google Gemini.

    This is OPTIONAL — basic ingestion works without calling this function.

    Parameters
    ----------
    image_paths : Paths returned by save_page_images().
    api_key     : Google AI Studio API key.
                  Defaults to the GEMINI_API_KEY env var.
    model       : Gemini model name (default: "gemini-1.5-flash").
                  Can be set via GEMINI_MODEL env var.
    rpm         : Maximum requests per minute.  0 means use the GEMINI_RPM
                  env var (default 15 if unset).  Set >0 to enforce delays.
    prompt      : Instruction given to Gemini for each image.
    max_retries : Retries on rate-limit / transient errors (429, 503).

    Returns
    -------
    Dict mapping each Path → description string.
    Pages that could not be described are mapped to an empty string.

    Raises
    ------
    GeminiError : If the API key is missing or unavailable.
    """
    resolved_key = api_key or os.getenv("GEMINI_API_KEY", "")
    if not resolved_key:
        raise GeminiError(
            "GEMINI_API_KEY is not set.  "
            "Export it before calling describe_pages:\n"
            "  $env:GEMINI_API_KEY = 'AIza...'"
        )

    resolved_model = model or os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
    resolved_rpm = rpm or int(os.getenv("GEMINI_RPM", "15"))
    delay = 60.0 / resolved_rpm if resolved_rpm > 0 else 0.0

    try:
        import google.generativeai as genai  # type: ignore
    except ImportError as exc:
        raise GeminiError(
            "google-generativeai is required for Gemini descriptions.\n"
            "Install it with:  py -m pip install google-generativeai"
        ) from exc

    genai.configure(api_key=resolved_key)
    gemini = genai.GenerativeModel(resolved_model)

    results: Dict[Path, str] = {}
    last_request_time = 0.0

    for image_path in image_paths:
        # Rate-limit: wait if needed before next request.
        elapsed = time.monotonic() - last_request_time
        if elapsed < delay:
            time.sleep(delay - elapsed)

        image_data = image_path.read_bytes()
        mime = "image/png" if image_path.suffix.lower() == ".png" else "image/jpeg"
        b64 = base64.b64encode(image_data).decode()

        for attempt in range(1, max_retries + 1):
            try:
                response = gemini.generate_content(
                    [
                        {"mime_type": mime, "data": b64},
                        prompt,
                    ]
                )
                results[image_path] = response.text or ""
                last_request_time = time.monotonic()
                logger.debug("Described '%s'.", image_path.name)
                break
            except Exception as exc:  # noqa: BLE001
                msg = str(exc)
                is_rate_limit = "429" in msg or "quota" in msg.lower() or "503" in msg
                if is_rate_limit and attempt < max_retries:
                    wait = delay * (2 ** attempt)
                    logger.warning(
                        "Rate limit / server error for '%s' (attempt %d/%d). "
                        "Retrying in %.1fs …",
                        image_path.name, attempt, max_retries, wait,
                    )
                    time.sleep(wait)
                else:
                    logger.error("Failed to describe '%s': %s", image_path.name, exc)
                    results[image_path] = ""
                    break

    return results


# ---------------------------------------------------------------------------
# 3. Safety chunk tagging
# ---------------------------------------------------------------------------

def tag_safety_chunks(chunks: list) -> list:
    """
    Return a new list of chunks with ``chunk_type`` set to ``"safety"`` where
    the text matches one or more safety-critical keywords.

    Non-safety chunks are returned unchanged (same objects, no copy needed).
    Safety chunks are shallow-replaced with an updated dataclass instance.

    Parameters
    ----------
    chunks : List of Chunk objects from ingest_pdf().

    Returns
    -------
    List of Chunk objects with safety-tagged items updated.
    """
    import dataclasses
    from .pdf_ingestor import Chunk

    result: list[Chunk] = []
    for chunk in chunks:
        if _SAFETY_PATTERNS.search(chunk.text):
            result.append(dataclasses.replace(chunk, chunk_type="safety"))
        else:
            result.append(chunk)
    return result


# ---------------------------------------------------------------------------
# 4. PDF highlight helper
# ---------------------------------------------------------------------------

class HighlightError(Exception):
    """Raised when a highlight annotation cannot be applied."""


def highlight_pdf(
    source_pdf: str | os.PathLike,
    output_pdf: str | os.PathLike,
    *,
    page_number: int,
    bbox: Optional[object] = None,
    color: tuple[float, float, float] = (1.0, 0.9, 0.0),  # yellow
    refer_text: bool = True,
) -> Path:
    """
    Add a highlight annotation to a copy of *source_pdf* at the given
    bounding box on *page_number*.

    If *bbox* is None (or coordinates are zero), the entire page is highlighted
    and a "Refer to page N" note is added — this is the fallback for chunks
    that were ingested without bounding-box metadata.

    Parameters
    ----------
    source_pdf  : Original PDF file path.
    output_pdf  : Where to write the annotated copy.
    page_number : 1-based page to annotate.
    bbox        : ``BoundingBox`` instance (from chunk.bbox) or None.
    color       : RGB tuple in 0.0–1.0 range (default: yellow).
    refer_text  : If True, add a text annotation saying "Refer to page N".

    Returns
    -------
    Path to the written output PDF.

    Raises
    ------
    HighlightError : If PyMuPDF is unavailable or the PDF cannot be annotated.
    """
    try:
        import pymupdf as fitz
    except ImportError:
        try:
            import fitz
        except ImportError as exc:
            raise HighlightError(
                "PyMuPDF is required for PDF highlighting.\n"
                "Install it with:  py -m pip install pymupdf"
            ) from exc

    source_pdf = Path(source_pdf)
    output_pdf = Path(output_pdf)

    try:
        doc = fitz.open(str(source_pdf))
    except Exception as exc:
        raise HighlightError(f"Cannot open '{source_pdf}': {exc}") from exc

    total = len(doc)
    if not (1 <= page_number <= total):
        doc.close()
        raise HighlightError(
            f"page_number {page_number} is out of range (1–{total})."
        )

    page = doc[page_number - 1]

    # Determine the rectangle to highlight.
    if bbox is not None and (bbox.x1 - bbox.x0 > 0) and (bbox.y1 - bbox.y0 > 0):  # type: ignore[union-attr]
        rect = fitz.Rect(bbox.x0, bbox.y0, bbox.x1, bbox.y1)  # type: ignore[union-attr]
        full_page_fallback = False
    else:
        # Fall back to the full page text area.
        rect = page.rect
        full_page_fallback = True
        logger.warning(
            "No bounding box for page %d — highlighting entire page.", page_number
        )

    # Add a highlight annotation.
    try:
        annot = page.add_highlight_annot(rect)
        annot.set_colors(stroke=color)
        annot.set_opacity(0.4)
        annot.update()
    except Exception as exc:
        doc.close()
        raise HighlightError(f"Failed to add highlight annotation: {exc}") from exc

    # Optionally add a text note.
    if refer_text or full_page_fallback:
        note_text = f"Refer to page {page_number}."
        if full_page_fallback:
            note_text += " (Full-page fallback — no bbox stored.)"
        try:
            # Place a small sticky note in the top-right corner.
            note_rect = fitz.Rect(rect.x1 - 20, rect.y0, rect.x1, rect.y0 + 20)
            note_annot = page.add_text_annot(note_rect.tl, note_text)
            note_annot.update()
        except Exception:  # noqa: BLE001 — note is cosmetic; don't fail
            pass

    try:
        doc.save(str(output_pdf))
    except Exception as exc:
        doc.close()
        raise HighlightError(f"Failed to save annotated PDF to '{output_pdf}': {exc}") from exc

    doc.close()
    logger.info("Highlighted page %d → '%s'.", page_number, output_pdf)
    return output_pdf
