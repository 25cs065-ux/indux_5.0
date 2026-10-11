# ingest/__init__.py
# Makes the ingest/ directory a Python package and exposes the public API.

from .pdf_ingestor import (
    ingest_pdf,
    IngestResult,
    Chunk,
    BoundingBox,
    IngestError,
    _split_text,
    _extract_troubleshooting_rows,
)

__all__ = [
    "ingest_pdf",
    "IngestResult",
    "Chunk",
    "BoundingBox",
    "IngestError",
    "_split_text",
    "_extract_troubleshooting_rows",
]
