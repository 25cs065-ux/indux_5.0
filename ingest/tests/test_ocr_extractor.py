# ingest/tests/test_ocr_extractor.py
#
# Tests for OCR extraction (ocr_extractor.py) and the OCR fallback path in
# pdf_ingestor.ingest_pdf().
#
# All tests are purely local — no Gemini API calls, no Supabase writes.
# Tesseract must be installed (winget install UB-Mannheim.TesseractOCR on
# Windows) for the live OCR tests; they are marked with `ocr` so they can
# be selected or skipped independently.
#
# Test groups:
#   A. ocr_extractor unit tests (mocked pytesseract)
#   B. _configure_tesseract path logic
#   C. ingest_pdf OCR fallback — mock path (no Tesseract required)
#   D. ingest_pdf OCR fallback disabled (ocr_fallback=False)
#   E. Live smoke tests that actually call Tesseract (marker: ocr)
#
# Run all:          py -m pytest ingest/tests/test_ocr_extractor.py -v
# Run live only:    py -m pytest ingest/tests/test_ocr_extractor.py -v -m ocr
# Skip live:        py -m pytest ingest/tests/test_ocr_extractor.py -v -m "not ocr"

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers shared with the other test files
# ---------------------------------------------------------------------------

def _make_pdf(pages: list[str]) -> bytes:
    """
    Build a minimal valid PDF with one text layer per page (pypdf-based).
    Blank pages simulate image-only (scanned) pages.
    """
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

    _LINE_WIDTH = 60
    writer = PdfWriter()
    for text in pages:
        page = writer.add_blank_page(width=595, height=842)
        if text:
            segments = [text[i:i + _LINE_WIDTH] for i in range(0, len(text), _LINE_WIDTH)]

            def _esc(s: str) -> str:
                return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")

            lines = [f"BT /F1 12 Tf 14 TL 50 800 Td ({_esc(segments[0])}) Tj"]
            for seg in segments[1:]:
                lines.append(f"T* ({_esc(seg)}) Tj")
            lines.append("ET")
            content = "\n".join(lines).encode()

            stream = DecodedStreamObject()
            stream.set_data(content)
            page[NameObject("/Contents")] = writer._add_object(stream)  # type: ignore[attr-defined]
            font = DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
                NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
            })
            resources = DictionaryObject({
                NameObject("/Font"): DictionaryObject(
                    {NameObject("/F1"): writer._add_object(font)}  # type: ignore[attr-defined]
                )
            })
            page[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


def _write_tmp_pdf(content: bytes) -> Path:
    fd, path_str = tempfile.mkstemp(suffix=".pdf")
    os.write(fd, content)
    os.close(fd)
    return Path(path_str)


# ---------------------------------------------------------------------------
# Imports under test
# ---------------------------------------------------------------------------

from ingest.ocr_extractor import OcrError, ocr_pdf_pages, _configure_tesseract
from ingest.pdf_ingestor import ingest_pdf, IngestResult


# ---------------------------------------------------------------------------
# A. ocr_extractor unit tests (mocked pytesseract)
# ---------------------------------------------------------------------------

class TestOcrExtractorUnit:
    """Tests for ocr_pdf_pages() with pytesseract mocked out."""

    def _make_mock_pytesseract(self, texts: list[str]):
        """
        Return a mock pytesseract module whose image_to_string() cycles through
        the provided texts in order, one per call.
        """
        mock_pt = MagicMock()
        mock_pt.image_to_string.side_effect = texts
        return mock_pt

    def test_returns_one_tuple_per_page(self):
        """ocr_pdf_pages returns one (page_num, text, None) per PDF page."""
        pdf_bytes = _make_pdf(["", ""])  # 2 blank pages — real layout doesn't matter
        mock_pt = self._make_mock_pytesseract(["Page one OCR text", "Page two OCR text"])
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            page_data, total = ocr_pdf_pages(pdf_bytes)
        assert total == 2
        assert len(page_data) == 2

    def test_page_numbers_are_one_based(self):
        pdf_bytes = _make_pdf(["", "", ""])
        mock_pt = self._make_mock_pytesseract(["a", "b", "c"])
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            page_data, _ = ocr_pdf_pages(pdf_bytes)
        page_nums = [pn for pn, _, _ in page_data]
        assert page_nums == [1, 2, 3]

    def test_bbox_is_always_none(self):
        pdf_bytes = _make_pdf([""])
        mock_pt = self._make_mock_pytesseract(["Some text"])
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            page_data, _ = ocr_pdf_pages(pdf_bytes)
        for _, _, bbox in page_data:
            assert bbox is None, "OCR extractor must always return None for bbox"

    def test_text_is_stripped(self):
        pdf_bytes = _make_pdf([""])
        mock_pt = self._make_mock_pytesseract(["  hello world  \n"])
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            page_data, _ = ocr_pdf_pages(pdf_bytes)
        assert page_data[0][1] == "hello world"

    def test_ocr_failure_on_page_yields_empty_string(self):
        """A per-page OCR error must produce '' for that page, not raise."""
        pdf_bytes = _make_pdf(["", ""])
        mock_pt = MagicMock()
        mock_pt.image_to_string.side_effect = [RuntimeError("OCR crash"), "Good page"]
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            page_data, _ = ocr_pdf_pages(pdf_bytes)
        assert page_data[0][1] == ""
        assert page_data[1][1] == "Good page"

    def test_corrupt_pdf_raises_ocr_error(self):
        with pytest.raises(OcrError, match="(?i)(open|raster)"):
            ocr_pdf_pages(b"not a pdf at all")

    def test_empty_bytes_raises_ocr_error(self):
        with pytest.raises(OcrError, match="(?i)(open|raster)"):
            ocr_pdf_pages(b"")


# ---------------------------------------------------------------------------
# B. _configure_tesseract path logic
# ---------------------------------------------------------------------------

class TestConfigureTesseract:
    """Tests for _configure_tesseract() path resolution."""

    def test_explicit_cmd_is_used(self, tmp_path, monkeypatch):
        """An explicit tesseract_cmd argument must be used directly."""
        fake_exe = str(tmp_path / "fake_tess.exe")
        mock_pt = MagicMock()
        # We don't need the file to exist — just check the attribute is set.
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            _configure_tesseract(fake_exe)
        assert mock_pt.pytesseract.tesseract_cmd == fake_exe

    def test_env_var_is_used_when_no_explicit_cmd(self, monkeypatch):
        """TESSERACT_CMD env var must be forwarded to pytesseract."""
        monkeypatch.setenv("TESSERACT_CMD", "/usr/local/bin/tesseract")
        mock_pt = MagicMock()
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            _configure_tesseract(None)
        assert mock_pt.pytesseract.tesseract_cmd == "/usr/local/bin/tesseract"

    def test_explicit_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("TESSERACT_CMD", "/env/path/tesseract")
        mock_pt = MagicMock()
        with patch.dict("sys.modules", {"pytesseract": mock_pt}):
            _configure_tesseract("/explicit/path/tesseract")
        assert mock_pt.pytesseract.tesseract_cmd == "/explicit/path/tesseract"


# ---------------------------------------------------------------------------
# C. ingest_pdf OCR fallback — mock path (no Tesseract required)
# ---------------------------------------------------------------------------

class TestIngestPdfOcrFallback:
    """
    Tests for the OCR fallback in ingest_pdf().

    These tests mock ocr_pdf_pages so they run without Tesseract installed.
    """

    def test_scanned_pdf_triggers_ocr_fallback(self, tmp_path):
        """A scanned (all-blank-page) PDF must trigger the OCR fallback."""
        pdf_bytes = _make_pdf(["", ""])
        pdf_file = tmp_path / "scanned.pdf"
        pdf_file.write_bytes(pdf_bytes)

        ocr_page_data = [
            (1, "Machine serial number: GA-15-026.", None),
            (2, "Maintenance interval: 2000 hours.", None),
        ]

        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 2)) as mock_ocr:
            result = ingest_pdf(pdf_file)

        mock_ocr.assert_called_once()
        assert result.extractor_used == "tesseract"
        assert len(result.chunks) >= 2
        assert result.scanned_warning is False

    def test_ocr_text_appears_in_chunks(self, tmp_path):
        """Text produced by the OCR mock must appear in the result chunks."""
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "scanned2.pdf"
        pdf_file.write_bytes(pdf_bytes)

        ocr_page_data = [(1, "Pressure valve setting: 8 bar. Refer to section 4.", None)]

        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 1)):
            result = ingest_pdf(pdf_file)

        all_text = " ".join(c.text for c in result.chunks)
        assert "Pressure valve" in all_text

    def test_ocr_page_numbers_are_preserved(self, tmp_path):
        """Page numbers from OCR output must be preserved on chunks."""
        pdf_bytes = _make_pdf(["", "", ""])
        pdf_file = tmp_path / "scanned3.pdf"
        pdf_file.write_bytes(pdf_bytes)

        ocr_page_data = [
            (1, "", None),          # blank
            (2, "Lubrication chart for GA-15.", None),
            (3, "Safety: wear PPE. Check guards.", None),
        ]

        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 3)):
            result = ingest_pdf(pdf_file)

        chunk_pages = {c.page_number for c in result.chunks}
        assert 2 in chunk_pages
        assert 3 in chunk_pages
        assert 1 not in chunk_pages  # blank OCR page must not produce chunks

    def test_ocr_empty_result_falls_back_to_scanned_warning(self, tmp_path):
        """
        If OCR returns no text on any page, scanned_warning must still be True
        and no chunks produced.
        """
        pdf_bytes = _make_pdf(["", ""])
        pdf_file = tmp_path / "ocr_empty.pdf"
        pdf_file.write_bytes(pdf_bytes)

        ocr_page_data = [(1, "", None), (2, "", None)]  # OCR also found nothing

        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 2)):
            result = ingest_pdf(pdf_file)

        assert result.scanned_warning is True
        assert result.chunks == []

    def test_ocr_error_falls_back_gracefully(self, tmp_path):
        """
        If ocr_pdf_pages raises OcrError, ingest_pdf must fall back gracefully
        (scanned_warning=True) instead of propagating the exception.
        """
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "ocr_error.pdf"
        pdf_file.write_bytes(pdf_bytes)

        from ingest.ocr_extractor import OcrError
        with patch("ingest.pdf_ingestor.ocr_pdf_pages", side_effect=OcrError("Tesseract not found")):
            result = ingest_pdf(pdf_file)

        assert isinstance(result, IngestResult)
        assert result.scanned_warning is True

    def test_text_pdf_does_not_trigger_ocr(self, tmp_path):
        """A PDF that already has text must NOT call ocr_pdf_pages."""
        pdf_bytes = _make_pdf(["Normal text-based PDF page content."])
        pdf_file = tmp_path / "text_pdf.pdf"
        pdf_file.write_bytes(pdf_bytes)

        with patch("ingest.pdf_ingestor.ocr_pdf_pages") as mock_ocr:
            result = ingest_pdf(pdf_file)

        mock_ocr.assert_not_called()
        assert result.extractor_used in {"pymupdf", "pypdf"}

    def test_troubleshooting_rows_detected_in_ocr_text(self, tmp_path):
        """
        Troubleshooting rows in OCR output must be correctly identified and
        tagged as chunk_type='troubleshooting_row'.
        """
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "ts_ocr.pdf"
        pdf_file.write_bytes(pdf_bytes)

        ts_text = (
            "Troubleshooting\n\n"
            "Problem: Compressor fails to start\n"
            "Cause: No power to motor\n"
            "Remedy: Check main circuit breaker\n\n"
            "Problem: Excessive noise\n"
            "Cause: Loose panels\n"
            "Remedy: Tighten all panel fixings"
        )
        ocr_page_data = [(1, ts_text, None)]

        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 1)):
            result = ingest_pdf(pdf_file)

        ts_chunks = [c for c in result.chunks if c.chunk_type == "troubleshooting_row"]
        assert len(ts_chunks) >= 2, (
            f"Expected ≥2 troubleshooting_row chunks from OCR text, got {len(ts_chunks)}"
        )

    def test_chunk_ids_are_unique_in_ocr_result(self, tmp_path):
        """All chunk_ids from an OCR-extracted document must be unique."""
        pdf_bytes = _make_pdf(["", ""])
        pdf_file = tmp_path / "ids_ocr.pdf"
        pdf_file.write_bytes(pdf_bytes)

        long_text = "Atlas Copco GA compressor technical data. " * 10
        ocr_page_data = [
            (1, long_text, None),
            (2, long_text, None),
        ]
        with patch("ingest.pdf_ingestor.ocr_pdf_pages", return_value=(ocr_page_data, 2)):
            result = ingest_pdf(pdf_file, doc_id="ocr_manual")

        ids = [c.chunk_id for c in result.chunks]
        assert len(ids) == len(set(ids)), "chunk_ids must be unique even for OCR output"


# ---------------------------------------------------------------------------
# D. ingest_pdf OCR fallback disabled (ocr_fallback=False)
# ---------------------------------------------------------------------------

class TestIngestPdfOcrDisabled:
    """Tests that ocr_fallback=False preserves the old scanned-PDF behaviour."""

    def test_no_ocr_when_disabled(self, tmp_path):
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "no_ocr.pdf"
        pdf_file.write_bytes(pdf_bytes)

        with patch("ingest.pdf_ingestor.ocr_pdf_pages") as mock_ocr:
            result = ingest_pdf(pdf_file, ocr_fallback=False)

        mock_ocr.assert_not_called()
        assert result.scanned_warning is True
        assert result.chunks == []

    def test_extractor_is_not_tesseract_when_disabled(self, tmp_path):
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "no_ocr2.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file, ocr_fallback=False)
        assert result.extractor_used != "tesseract"


# ---------------------------------------------------------------------------
# E. Live smoke tests — require Tesseract installed
# ---------------------------------------------------------------------------


@pytest.mark.ocr
class TestOcrLive:
    """
    Live Tesseract smoke tests.  These render a real PDF page and call
    Tesseract.  They only run when Tesseract is actually installed and the
    test is not skipped with -m "not ocr".
    """

    def test_tesseract_is_reachable(self):
        """Tesseract must be installed and return a version string."""
        import pytesseract
        version = pytesseract.get_tesseract_version()
        assert version is not None, "Tesseract did not return a version"

    def test_ocr_pdf_pages_on_synthetic_scanned_pdf(self, tmp_path):
        """
        Build a blank-page PDF and run OCR on it.  We do not assert specific
        text content (a blank white page produces little), but we do assert
        that:
          - the function returns without error
          - total_pages matches what we put in
          - each entry is (int, str, None)
        """
        pdf_bytes = _make_pdf(["", ""])
        page_data, total = ocr_pdf_pages(pdf_bytes)
        assert total == 2
        assert len(page_data) == 2
        for pn, text, bbox in page_data:
            assert isinstance(pn, int)
            assert isinstance(text, str)
            assert bbox is None

    def test_ocr_text_based_page_contains_expected_words(self, tmp_path):
        """
        Build a PDF with real text rendered as a vector font, run OCR, and
        check that Tesseract picks up the key word.

        Note: this tests OCR on a vector-font PDF (not a scanned image).
        Tesseract reads the rasterised bitmap, so it should still extract
        legible text at 300 DPI.
        """
        text_on_page = "Safety valve pressure limit 15 bar maximum operation"
        pdf_bytes = _make_pdf([text_on_page])
        page_data, total = ocr_pdf_pages(pdf_bytes)
        assert total == 1
        extracted = page_data[0][1].lower()
        # Tesseract may not get every word perfectly, but "safety" and "bar"
        # are distinct enough to survive OCR at 300 DPI on Helvetica.
        found_keywords = [kw for kw in ("safety", "bar", "pressure", "valve") if kw in extracted]
        assert len(found_keywords) >= 2, (
            f"Expected at least 2 of [safety, bar, pressure, valve] in OCR output; "
            f"got: {extracted!r}"
        )

    def test_ingest_pdf_ocr_fallback_live(self, tmp_path):
        """
        Full pipeline: blank-page PDF → ingest_pdf (OCR enabled) → check that
        extractor_used is 'tesseract' and IngestResult is well-formed.

        For a truly blank page Tesseract may find no text, so we accept either
        extractor_used='tesseract' (OCR ran) or scanned_warning=True (OCR ran
        but found nothing).  What must NOT happen is a crash.
        """
        pdf_bytes = _make_pdf([""])
        pdf_file = tmp_path / "live_scanned.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file, ocr_fallback=True)
        assert isinstance(result, IngestResult)
        # OCR must have been attempted — extractor_used should be 'tesseract'
        # OR (if blank) scanned_warning=True.
        assert result.extractor_used == "tesseract" or result.scanned_warning is True
