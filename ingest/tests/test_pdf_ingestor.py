# ingest/tests/test_pdf_ingestor.py
#
# Automated tests for the PDF ingestion module.
#
# These tests create small synthetic PDFs entirely in memory using pypdf,
# so no real industrial manuals are needed and nothing confidential is stored.
#
# Run with:
#   python -m pytest ingest/tests/ -v
#
# Test coverage:
#   1. Valid multi-page PDF                – chunks are produced for each page
#   2. Page-number preservation            – each chunk knows its exact page
#   3. Text chunking and overlap           – long text splits with overlap
#   4. Empty pages                         – empty pages are reported, not crashed
#   5. Invalid / corrupt PDFs             – IngestError is raised
#   6. Missing files                       – IngestError is raised
#   7. PDFs with no extractable text       – scanned_warning is set
#   8. Metadata preservation               – doc_id propagates to every chunk
#   9. Zero-byte file                      – IngestError is raised
#  10. Non-PDF file disguised as .pdf      – IngestError is raised
#  11. doc_id override                     – caller-supplied ID is honoured
#  12. chunk_size / chunk_overlap params   – validated and respected

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helper: build a real (pypdf-readable) PDF entirely in memory
# ---------------------------------------------------------------------------

def _make_pdf(pages: list[str]) -> bytes:
    """
    Create a minimal but valid PDF containing one text layer per page.

    Parameters
    ----------
    pages : List of strings — one entry per page.
            An empty string produces a page with no text (simulates a blank page).

    Returns
    -------
    Raw PDF bytes that pypdf can open and extract text from.
    """
    # We build the PDF by hand using pypdf's writer so we don't need
    # an additional library (reportlab, fpdf2, etc.).
    from pypdf import PdfWriter
    from pypdf.generic import (
        DecodedStreamObject,
        DictionaryObject,
        NameObject,
    )

    writer = PdfWriter()

    for text in pages:
        # Add a blank A4 page, then optionally paint text onto it.
        page = writer.add_blank_page(width=595, height=842)

        if text:
            # Build a minimal PDF content stream: BT ... ET block.
            # We encode every character as its ASCII byte value, which
            # pypdf's text extractor can read back directly.
            safe_text = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            content = f"BT /F1 12 Tf 50 800 Td ({safe_text}) Tj ET\n".encode()

            # Attach the content stream to the page.
            stream = DecodedStreamObject()
            stream.set_data(content)
            page[NameObject("/Contents")] = writer._add_object(stream)  # type: ignore[attr-defined]

            # Register a minimal font resource so text renders.
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
            resources = DictionaryObject(
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}  # type: ignore[attr-defined]
                    )
                }
            )
            page[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _write_tmp_pdf(content: bytes, suffix: str = ".pdf") -> Path:
    """Write *content* to a named temporary file and return its Path."""
    fd, path_str = tempfile.mkstemp(suffix=suffix)
    os.write(fd, content)
    os.close(fd)
    return Path(path_str)


# ---------------------------------------------------------------------------
# Import the module under test
# ---------------------------------------------------------------------------

from ingest.pdf_ingestor import (  # noqa: E402 — must come after helper defs
    Chunk,
    IngestError,
    IngestResult,
    _split_text,
    ingest_pdf,
)


# ---------------------------------------------------------------------------
# Tests: _split_text (unit — no file I/O)
# ---------------------------------------------------------------------------

class TestSplitText:
    """Tests for the internal text-splitting helper."""

    def test_empty_string_returns_empty_list(self):
        assert _split_text("", 100, 20) == []

    def test_short_text_fits_in_one_chunk(self):
        result = _split_text("Hello world", 100, 20)
        assert len(result) == 1
        assert result[0] == "Hello world"

    def test_long_text_splits_into_multiple_chunks(self):
        # 30-char text, chunk_size=10, overlap=3 → step=7
        # starts: 0, 7, 14, 21, 28
        text = "A" * 30
        result = _split_text(text, chunk_size=10, chunk_overlap=3)
        assert len(result) > 1

    def test_overlap_shared_between_chunks(self):
        # Use a text where overlap is clearly traceable.
        text = "ABCDEFGHIJKLMNOPQRSTUVWXYZ"  # 26 chars
        # chunk_size=10, overlap=4 → step=6
        # chunk 0: [0:10]  = "ABCDEFGHIJ"
        # chunk 1: [6:16]  = "GHIJKLMNOP"  — G-H-I-J overlap with chunk 0
        result = _split_text(text, chunk_size=10, chunk_overlap=4)
        assert result[0][-4:] == result[1][:4]

    def test_chunk_size_equals_text_length(self):
        text = "EXACTLY10C"
        result = _split_text(text, chunk_size=10, chunk_overlap=0)
        assert len(result) == 1
        assert result[0] == text

    def test_whitespace_only_chunk_is_skipped(self):
        # A chunk that strips to nothing should not be included.
        result = _split_text("   ", 100, 0)
        assert result == []


# ---------------------------------------------------------------------------
# Tests: ingest_pdf — file validation errors
# ---------------------------------------------------------------------------

class TestFileValidation:
    """Tests that bad inputs raise IngestError with clear messages."""

    def test_missing_file_raises(self, tmp_path):
        missing = tmp_path / "nonexistent.pdf"
        with pytest.raises(IngestError, match="not found"):
            ingest_pdf(missing)

    def test_zero_byte_file_raises(self, tmp_path):
        empty = tmp_path / "empty.pdf"
        empty.write_bytes(b"")
        with pytest.raises(IngestError, match="empty"):
            ingest_pdf(empty)

    def test_non_pdf_content_raises(self, tmp_path):
        fake = tmp_path / "fake.pdf"
        fake.write_bytes(b"This is just plain text, not a PDF.")
        with pytest.raises(IngestError, match="valid PDF"):
            ingest_pdf(fake)

    def test_corrupt_pdf_raises(self, tmp_path):
        corrupt = tmp_path / "corrupt.pdf"
        # Start with the magic header but then garbage.
        # pypdf either raises PdfReadError (corrupt) or reports 0 pages — both
        # are caught and re-raised as IngestError by the implementation.
        corrupt.write_bytes(b"%PDF-1.4\n" + b"\x00" * 50)
        with pytest.raises(IngestError, match="(?i)(corrupt|no pages|read)"):
            ingest_pdf(corrupt)

    def test_invalid_chunk_size_raises(self, tmp_path):
        pdf_bytes = _make_pdf(["Hello"])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            with pytest.raises(ValueError, match="chunk_size"):
                ingest_pdf(f, chunk_size=0)
        finally:
            f.unlink(missing_ok=True)

    def test_invalid_overlap_raises(self, tmp_path):
        pdf_bytes = _make_pdf(["Hello"])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            with pytest.raises(ValueError, match="chunk_overlap"):
                ingest_pdf(f, chunk_size=10, chunk_overlap=10)
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: ingest_pdf — successful ingestion
# ---------------------------------------------------------------------------

class TestSuccessfulIngestion:
    """Tests for well-formed PDFs."""

    def test_valid_single_page_pdf(self):
        pdf_bytes = _make_pdf(["Hello factory worker. This is page one."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert isinstance(result, IngestResult)
            assert result.total_pages == 1
            assert len(result.chunks) >= 1
            assert result.scanned_warning is False
        finally:
            f.unlink(missing_ok=True)

    def test_valid_multi_page_pdf_produces_chunks(self):
        pages = [
            "Page one content about the boiler system.",
            "Page two content about the pump assembly.",
            "Page three content about safety procedures.",
        ]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert result.total_pages == 3
            assert len(result.chunks) >= 3
        finally:
            f.unlink(missing_ok=True)

    def test_page_numbers_are_preserved(self):
        pages = ["Alpha page content.", "Beta page content.", "Gamma page content."]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            # Each page must appear at least once in the chunks.
            found_pages = {c.page_number for c in result.chunks}
            assert 1 in found_pages
            assert 2 in found_pages
            assert 3 in found_pages
        finally:
            f.unlink(missing_ok=True)

    def test_page_numbers_are_one_based(self):
        pdf_bytes = _make_pdf(["First page text."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert all(c.page_number >= 1 for c in result.chunks)
        finally:
            f.unlink(missing_ok=True)

    def test_chunk_index_is_sequential(self):
        # Generate enough text to guarantee multiple chunks.
        long_text = "The boiler valve must be checked every 30 days. " * 40
        pdf_bytes = _make_pdf([long_text])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            indices = [c.chunk_index for c in result.chunks]
            assert indices == list(range(len(result.chunks)))
        finally:
            f.unlink(missing_ok=True)

    def test_doc_id_is_consistent_across_chunks(self):
        pages = ["Page A content.", "Page B content."]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            doc_ids = {c.doc_id for c in result.chunks}
            assert len(doc_ids) == 1  # all chunks share the same doc_id
        finally:
            f.unlink(missing_ok=True)

    def test_caller_supplied_doc_id_is_used(self):
        pdf_bytes = _make_pdf(["Some machine SOP content."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f, doc_id="manual_boiler_v2")
            assert result.doc_id == "manual_boiler_v2"
            assert all(c.doc_id == "manual_boiler_v2" for c in result.chunks)
        finally:
            f.unlink(missing_ok=True)

    def test_default_doc_id_is_sha256_hex(self):
        import hashlib
        pdf_bytes = _make_pdf(["Content here."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            expected = hashlib.sha256(pdf_bytes).hexdigest()
            result = ingest_pdf(f)
            assert result.doc_id == expected
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: ingest_pdf — empty pages
# ---------------------------------------------------------------------------

class TestEmptyPages:
    """Tests for PDFs that contain one or more blank pages."""

    def test_empty_page_is_reported_in_empty_pages_list(self):
        # Page 2 is blank (empty string).
        pages = ["Useful content on page one.", "", "Useful content on page three."]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert 2 in result.empty_pages
        finally:
            f.unlink(missing_ok=True)

    def test_empty_page_does_not_produce_chunk(self):
        pages = ["Good content.", ""]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            # No chunk should reference the blank page 2.
            assert all(c.page_number != 2 for c in result.chunks)
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: ingest_pdf — scanned / image-only PDFs
# ---------------------------------------------------------------------------

class TestScannedPdf:
    """Tests for PDFs that produce no extractable text on any page."""

    def test_all_blank_pages_triggers_scanned_warning(self):
        # All pages are blank — simulates an image-only scanned PDF.
        pages = ["", "", ""]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert result.scanned_warning is True
            assert len(result.chunks) == 0
        finally:
            f.unlink(missing_ok=True)

    def test_scanned_pdf_returns_empty_chunks_not_error(self):
        """
        Scanned PDFs are not an error — they just yield no chunks and a warning.
        The caller can decide whether to reject or report the file.
        """
        pdf_bytes = _make_pdf([""])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert isinstance(result, IngestResult)
            assert result.chunks == []
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Tests: ingest_pdf — chunking parameters
# ---------------------------------------------------------------------------

class TestChunkingParameters:
    """Tests for custom chunk_size and chunk_overlap settings."""

    def test_large_chunk_size_produces_fewer_chunks(self):
        text = "Word " * 200  # ~1000 chars
        pdf_bytes = _make_pdf([text])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            small_chunks = ingest_pdf(f, chunk_size=100, chunk_overlap=10)
            large_chunks = ingest_pdf(f, chunk_size=500, chunk_overlap=50)
            assert len(large_chunks.chunks) < len(small_chunks.chunks)
        finally:
            f.unlink(missing_ok=True)

    def test_overlap_means_chunk_text_is_shared(self):
        # With overlap=50, adjacent chunks share 50 characters.
        text = "X" * 300
        pdf_bytes = _make_pdf([text])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f, chunk_size=100, chunk_overlap=50)
            if len(result.chunks) >= 2:
                end_of_first = result.chunks[0].text[-50:]
                start_of_second = result.chunks[1].text[:50]
                assert end_of_first == start_of_second
        finally:
            f.unlink(missing_ok=True)

    def test_overlap_near_chunk_size_still_terminates(self):
        # chunk_overlap = chunk_size - 1 is technically valid (step = 1).
        # This test confirms the loop terminates and returns at least one chunk
        # rather than hanging or raising.
        text = "AB" * 20  # 40 chars
        result = _split_text(text, chunk_size=10, chunk_overlap=9)
        # step=1, so we get many chunks — verify it's finite and non-empty.
        assert len(result) > 0
        assert all(len(c) <= 10 for c in result)


# ---------------------------------------------------------------------------
# Integration / smoke test — end-to-end through a real temporary file
# ---------------------------------------------------------------------------

class TestIntegrationSmoke:
    """
    Full end-to-end smoke test.

    Writes a temporary PDF to disk, calls ingest_pdf(), and verifies that
    every piece of metadata on every returned chunk is exactly correct.
    This is the single test that would catch a wiring mistake between any
    two stages of the pipeline (extraction → splitting → metadata attachment).
    """

    def test_full_pipeline_metadata_on_every_chunk(self, tmp_path):
        """
        Three-page PDF with distinct text on each page.
        After ingestion every chunk must carry the right doc_id, the right
        1-based page_number, a sequential chunk_index, and non-empty text.
        """
        pages = [
            "Boiler system overview. Safety valve must open at 15 bar.",
            "Pump assembly instructions. Lubricate bearings every 500 hours.",
            "Emergency shutdown procedure. Pull red handle and call supervisor.",
        ]
        pdf_bytes = _make_pdf(pages)
        pdf_file = tmp_path / "smoke_manual.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file, doc_id="smoke_manual_v1")

        # --- Top-level result fields ----------------------------------------
        assert result.doc_id == "smoke_manual_v1"
        assert result.total_pages == 3
        assert result.scanned_warning is False
        assert result.empty_pages == []          # all pages have text
        assert len(result.chunks) >= 3           # at least one chunk per page

        # --- Per-chunk invariants -------------------------------------------
        for i, chunk in enumerate(result.chunks):
            # chunk_index must be 0-based sequential across the whole document
            assert chunk.chunk_index == i, (
                f"chunk at position {i} has chunk_index={chunk.chunk_index}"
            )
            # doc_id must match what was passed in
            assert chunk.doc_id == "smoke_manual_v1", (
                f"chunk {i} has wrong doc_id: {chunk.doc_id!r}"
            )
            # page_number must be 1-based and within the document range
            assert 1 <= chunk.page_number <= 3, (
                f"chunk {i} has out-of-range page_number={chunk.page_number}"
            )
            # text must be a non-empty string
            assert isinstance(chunk.text, str) and chunk.text.strip(), (
                f"chunk {i} has empty or non-string text"
            )

        # --- Page coverage --------------------------------------------------
        # Every page that has text must be represented by at least one chunk.
        pages_in_chunks = {c.page_number for c in result.chunks}
        assert pages_in_chunks == {1, 2, 3}, (
            f"Expected chunks from pages {{1,2,3}}, got {pages_in_chunks}"
        )

    def test_smoke_empty_page_in_middle_is_skipped_cleanly(self, tmp_path):
        """
        Five-page PDF where page 3 is blank.
        Confirms that the blank page is in empty_pages, no chunk references it,
        and pages 1, 2, 4, 5 are all represented.
        """
        pages = [
            "Page one: valve specifications.",
            "Page two: pressure readings.",
            "",                                   # blank — page 3
            "Page four: maintenance log format.",
            "Page five: contact list.",
        ]
        pdf_bytes = _make_pdf(pages)
        pdf_file = tmp_path / "smoke_blank_middle.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file)

        assert result.total_pages == 5
        assert 3 in result.empty_pages
        assert all(c.page_number != 3 for c in result.chunks)
        pages_in_chunks = {c.page_number for c in result.chunks}
        assert {1, 2, 4, 5}.issubset(pages_in_chunks)

    def test_smoke_scanned_pdf_returns_warning_not_error(self, tmp_path):
        """
        Image-only PDF (all blank pages) must return IngestResult with
        scanned_warning=True and zero chunks — never raise an exception.
        """
        pdf_bytes = _make_pdf(["", "", ""])
        pdf_file = tmp_path / "smoke_scanned.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file)

        assert isinstance(result, IngestResult)
        assert result.scanned_warning is True
        assert result.chunks == []
        assert result.total_pages == 3
        assert result.empty_pages == [1, 2, 3]

    def test_smoke_invalid_pdf_raises_ingest_error(self, tmp_path):
        """
        A file with a .pdf extension but non-PDF content must raise
        IngestError, not any other exception type.
        """
        bad_file = tmp_path / "not_a_pdf.pdf"
        bad_file.write_bytes(b"JFIF" + b"\x00" * 100)   # JPEG-like bytes

        with pytest.raises(IngestError):
            ingest_pdf(bad_file)
