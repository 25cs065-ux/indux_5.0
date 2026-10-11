#!/usr/bin/env python
# ingest/extract_local.py
#
# Local text extraction and chunking for Indux 5.0.
#
# Extracts text from PDF manuals, produces minimal useful chunks, and saves
# them to ingest/output/ as JSONL files.  Makes zero Gemini API calls and
# zero Supabase writes.
#
# Usage (from repository root):
#   py -m ingest.extract_local docs/manuals/GA15-26_Datasheet.pdf --doc-id GA15-26_Datasheet
#   py -m ingest.extract_local docs/manuals/Compressed_Air_Manual_9th_Ed.pdf --doc-id Compressed_Air_Manual
#
# Chunking settings:
#   --chunk-size 1200  (default) — large enough to keep spec table rows and
#                                   feature lists intact within one chunk.
#   --overlap 100      (default) — small overlap preserves sentence continuity
#                                   without duplicating spec data.
#
# Why 1200/100 instead of the default 800/150:
#   The two PDFs in scope are datasheet/brochure content with dense tables and
#   feature bullet lists.  At 800 chars the technical spec table for GA 22
#   (needed for Q13/Q14/Q15) gets split mid-row, losing the association between
#   model name, pressure, power, and noise values.  1200 chars keeps each
#   compressor model's full spec row together.  Overlap is reduced from 150 to
#   100 because these documents have no narrative paragraphs that need heavy
#   cross-chunk context — 100 chars is enough to bridge a heading to its table.
#
# Output fields (per chunk, written as JSONL):
#   doc_id       — stable identifier (--doc-id or SHA-256 of file bytes)
#   chunk_id     — "{doc_id}_{chunk_index:05d}"
#   chunk_index  — 0-based sequential position within the document
#   page_number  — 1-based source page
#   section      — "text" | "troubleshooting_row" | "safety"
#   text         — chunk content
#   bbox_x0/y0/x1/y1 — bounding box from PyMuPDF (null when unavailable)

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict
from pathlib import Path

# Ensure repo root is on sys.path when run as a script.
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

# Default chunking parameters (tuned for datasheet/spec content).
DEFAULT_CHUNK_SIZE = 1200
DEFAULT_OVERLAP = 100
OUTPUT_DIR = Path(__file__).resolve().parent / "output"


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="extract_local",
        description=(
            "Extract text from a PDF manual and save chunks locally as JSONL.\n"
            "Makes zero Gemini API calls and zero Supabase writes."
        ),
    )
    parser.add_argument("pdf_path", metavar="PDF_PATH")
    parser.add_argument(
        "--doc-id",
        default=None,
        help="Stable document ID (default: SHA-256 of file bytes).",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=DEFAULT_CHUNK_SIZE,
        metavar="N",
        help=f"Max chars per chunk (default: {DEFAULT_CHUNK_SIZE}).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=DEFAULT_OVERLAP,
        metavar="N",
        help=f"Overlap chars between chunks (default: {DEFAULT_OVERLAP}).",
    )
    parser.add_argument(
        "--output-dir",
        default=str(OUTPUT_DIR),
        help=f"Output directory (default: {OUTPUT_DIR}).",
    )
    parser.add_argument("--verbose", "-v", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    pdf_path = Path(args.pdf_path)
    output_dir = Path(args.output_dir)
    t_start = time.monotonic()

    print(f"\n{'='*60}")
    print(f"  Local extraction: {pdf_path.name}")
    print(f"  chunk_size={args.chunk_size}  overlap={args.overlap}")
    print(f"{'='*60}")

    # ------------------------------------------------------------------
    # 1. Extract and chunk using the existing ingest_pdf() function.
    # ------------------------------------------------------------------
    from ingest.pdf_ingestor import ingest_pdf, IngestError

    logger.info("Extracting text from '%s' ...", pdf_path)
    try:
        result = ingest_pdf(
            pdf_path,
            doc_id=args.doc_id,
            chunk_size=args.chunk_size,
            chunk_overlap=args.overlap,
        )
    except IngestError as exc:
        print(f"\nERROR - INGESTION FAILED: {exc}", file=sys.stderr)
        return 1
    except ValueError as exc:
        print(f"\nERROR - INVALID PARAMETERS: {exc}", file=sys.stderr)
        return 1

    # ------------------------------------------------------------------
    # 2. Print per-document statistics.
    # ------------------------------------------------------------------
    text_pages = result.total_pages - len(result.empty_pages)
    total_chars = sum(len(c.text) for c in result.chunks)
    ts_count = sum(1 for c in result.chunks if c.chunk_type == "troubleshooting_row")

    print(f"\n  Extractor      : {result.extractor_used}")
    print(f"  doc_id         : {result.doc_id}")
    print(f"  Total pages    : {result.total_pages}")
    print(f"  Pages with text: {text_pages}")
    print(f"  Blank pages    : {len(result.empty_pages)}")
    if result.empty_pages:
        print(f"  Blank page nos : {result.empty_pages}")
    print(f"  Extracted chars: {total_chars}")
    print(f"  Total chunks   : {len(result.chunks)}")
    if ts_count:
        print(f"  TS row chunks  : {ts_count}")
    print(f"  scanned_warning: {result.scanned_warning}")
    print()

    if result.scanned_warning:
        print("WARNING: No text extracted -- PDF appears to be scanned/image-only.")
        return 1

    if not result.chunks:
        print("WARNING: No chunks produced -- nothing to save.")
        return 1

    # ------------------------------------------------------------------
    # 3. Save chunks to JSONL.
    # ------------------------------------------------------------------
    output_dir.mkdir(parents=True, exist_ok=True)
    doc_id_safe = result.doc_id.replace("/", "_").replace("\\", "_")[:80]
    out_path = output_dir / f"{doc_id_safe}.jsonl"

    with out_path.open("w", encoding="utf-8") as fh:
        for chunk in result.chunks:
            row = {
                "doc_id": chunk.doc_id,
                "chunk_id": chunk.chunk_id,
                "chunk_index": chunk.chunk_index,
                "page_number": chunk.page_number,
                "section": chunk.chunk_type,
                "text": chunk.text,
                "bbox_x0": chunk.bbox.x0 if chunk.bbox else None,
                "bbox_y0": chunk.bbox.y0 if chunk.bbox else None,
                "bbox_x1": chunk.bbox.x1 if chunk.bbox else None,
                "bbox_y1": chunk.bbox.y1 if chunk.bbox else None,
            }
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")

    logger.info("Saved %d chunks to '%s'", len(result.chunks), out_path)

    # ------------------------------------------------------------------
    # 4. Save a human-readable summary alongside the JSONL.
    # ------------------------------------------------------------------
    summary_path = output_dir / f"{doc_id_safe}_summary.json"
    summary = {
        "source_pdf": str(pdf_path),
        "doc_id": result.doc_id,
        "extractor": result.extractor_used,
        "chunk_size": args.chunk_size,
        "overlap": args.overlap,
        "total_pages": result.total_pages,
        "pages_with_text": text_pages,
        "blank_pages": result.empty_pages,
        "extracted_chars": total_chars,
        "total_chunks": len(result.chunks),
        "troubleshooting_row_chunks": ts_count,
        "output_jsonl": str(out_path),
    }
    with summary_path.open("w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, ensure_ascii=False)

    elapsed = time.monotonic() - t_start
    print(f"  Output JSONL   : {out_path}")
    print(f"  Summary JSON   : {summary_path}")
    print(f"\n* Done in {elapsed:.2f}s  --  {len(result.chunks)} chunks saved locally.")
    print("  (Zero Gemini API calls. Zero Supabase writes.)\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
