#!/usr/bin/env python
# ingest/run_ingest.py
#
# One-command ingestion entry point for Indux 5.0.
#
# Usage
# -----
#   py ingest/run_ingest.py path/to/manual.pdf
#   py ingest/run_ingest.py path/to/manual.pdf --doc-id boiler_manual_v3
#   py ingest/run_ingest.py path/to/manual.pdf --dry-run   # skip DB write
#   py ingest/run_ingest.py path/to/manual.pdf --chunk-size 600 --overlap 100
#
# Environment variables
# ---------------------
#   SUPABASE_URL   : Supabase project REST endpoint (required unless --dry-run)
#   SUPABASE_KEY   : Supabase service-role key      (required unless --dry-run)
#   EMBED_MODEL    : sentence-transformers model name (default: all-MiniLM-L6-v2)
#
# Exit codes
# ----------
#   0 : Success
#   1 : Ingestion error (bad file, scanned PDF, etc.)
#   2 : Embedding error
#   3 : Database / storage error
#   4 : Unexpected error

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path

# ---------------------------------------------------------------------------
# Logging configuration — INFO by default, DEBUG with --verbose
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="run_ingest",
        description=(
            "Ingest a PDF manual into Indux 5.0.\n\n"
            "Pipeline: validate → extract text (PyMuPDF) → chunk →\n"
            "          embed (sentence-transformers) → save (Supabase)"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "pdf_path",
        metavar="PDF_PATH",
        help="Path to the PDF file to ingest.",
    )
    parser.add_argument(
        "--doc-id",
        default=None,
        help=(
            "Stable document identifier (default: SHA-256 hash of file bytes). "
            "Useful for human-readable IDs like 'boiler_manual_v3'."
        ),
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=800,
        metavar="N",
        help="Maximum characters per chunk (default: 800).",
    )
    parser.add_argument(
        "--overlap",
        type=int,
        default=150,
        metavar="N",
        help="Overlap characters between consecutive chunks (default: 150).",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=32,
        metavar="N",
        help="Chunks per embedding batch (default: 32).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Extract and embed but do NOT write to Supabase. "
            "Use this to test without database credentials."
        ),
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG logging.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """
    Main entry point.  Returns an exit code (0 = success).
    """
    args = _parse_args(argv)

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    pdf_path = Path(args.pdf_path)
    t_start = time.monotonic()

    # ------------------------------------------------------------------
    # Step 1 — Validate + extract + chunk
    # ------------------------------------------------------------------
    print(f"\n{'='*60}")
    print(f"  Ingesting: {pdf_path.name}")
    print(f"{'='*60}")

    try:
        from ingest.pdf_ingestor import ingest_pdf, IngestError
    except ImportError:
        # Allow running as a module inside the package
        from pdf_ingestor import ingest_pdf, IngestError  # type: ignore

    logger.info("Step 1/3 — Extracting text from '%s' …", pdf_path)
    try:
        result = ingest_pdf(
            pdf_path,
            doc_id=args.doc_id,
            chunk_size=args.chunk_size,
            chunk_overlap=args.overlap,
        )
    except IngestError as exc:
        _print_error("INGESTION FAILED", str(exc))
        return 1
    except ValueError as exc:
        _print_error("INVALID PARAMETERS", str(exc))
        return 1
    except Exception as exc:  # noqa: BLE001
        _print_error("UNEXPECTED ERROR during extraction", str(exc))
        return 4

    _print_result_summary(result)

    if result.scanned_warning:
        _print_warning(
            "No text was extracted from any page.  The PDF may be scanned / "
            "image-only.  No chunks will be stored."
        )
        return 1

    if not result.chunks:
        _print_warning("No chunks were produced.  Nothing to embed or store.")
        return 1

    # ------------------------------------------------------------------
    # Step 2 — Embed
    # ------------------------------------------------------------------
    logger.info("Step 2/3 — Embedding %d chunks …", len(result.chunks))
    try:
        try:
            from ingest.embedder import embed_chunks, EmbeddingError
        except ImportError:
            from embedder import embed_chunks, EmbeddingError  # type: ignore

        embeddings = embed_chunks(
            result.chunks,
            batch_size=args.batch_size,
        )
        logger.info("Embedding complete.  Dimension: %d", len(embeddings[0]))
    except EmbeddingError as exc:
        _print_error("EMBEDDING FAILED", str(exc))
        return 2
    except Exception as exc:  # noqa: BLE001
        _print_error("UNEXPECTED ERROR during embedding", str(exc))
        return 4

    # ------------------------------------------------------------------
    # Step 3 — Save to Supabase (skipped in dry-run mode)
    # ------------------------------------------------------------------
    if args.dry_run:
        _print_warning(
            "--dry-run mode: skipping Supabase write.  "
            f"Would have saved {len(result.chunks)} chunks."
        )
    else:
        logger.info("Step 3/3 — Saving %d chunks to Supabase …", len(result.chunks))
        try:
            try:
                from ingest.storage import save_chunks, StorageError
            except ImportError:
                from storage import save_chunks, StorageError  # type: ignore

            saved = save_chunks(result.chunks, embeddings)
            logger.info("Saved %d rows to Supabase.", saved)
        except StorageError as exc:
            _print_error("DATABASE ERROR", str(exc))
            return 3
        except Exception as exc:  # noqa: BLE001
            _print_error("UNEXPECTED ERROR during save", str(exc))
            return 4

    elapsed = time.monotonic() - t_start
    print(f"\n✓ Done in {elapsed:.1f}s  —  {len(result.chunks)} chunks ingested.")
    print(f"  Extractor : {result.extractor_used}")
    print(f"  doc_id    : {result.doc_id}")
    print(f"  Pages     : {result.total_pages}")
    if result.empty_pages:
        print(f"  Blank pgs : {result.empty_pages}")
    print()
    return 0


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _print_result_summary(result: object) -> None:
    print(f"\n  Extractor  : {result.extractor_used}")  # type: ignore[attr-defined]
    print(f"  doc_id     : {result.doc_id}")             # type: ignore[attr-defined]
    print(f"  Pages      : {result.total_pages}")        # type: ignore[attr-defined]
    print(f"  Chunks     : {len(result.chunks)}")        # type: ignore[attr-defined]
    ts = sum(1 for c in result.chunks if c.chunk_type == "troubleshooting_row")  # type: ignore[attr-defined]
    if ts:
        print(f"  TS rows    : {ts}")
    if result.empty_pages:                               # type: ignore[attr-defined]
        print(f"  Blank pages: {result.empty_pages}")    # type: ignore[attr-defined]
    print()


def _print_error(title: str, message: str) -> None:
    print(f"\n✗ {title}:", file=sys.stderr)
    for line in message.splitlines():
        print(f"    {line}", file=sys.stderr)
    print(file=sys.stderr)


def _print_warning(message: str) -> None:
    print(f"\n⚠  {message}\n")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    sys.exit(main())
