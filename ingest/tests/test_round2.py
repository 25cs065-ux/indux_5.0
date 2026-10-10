# ingest/tests/test_round2.py
#
# Tests for Round 2 additions:
#   A. save_page_images — PyMuPDF page rendering
#   B. describe_pages   — Gemini integration (fully mocked)
#   C. tag_safety_chunks — safety keyword tagging
#   D. highlight_pdf    — PDF annotation helper
#
# Run with:
#   py -m pytest ingest/tests/test_round2.py -v

from __future__ import annotations

import io
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helper: build a minimal PDF for testing
# ---------------------------------------------------------------------------

def _make_pdf(pages: list[str]) -> bytes:
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
            page[NameObject("/Contents")] = writer._add_object(stream)
            font = DictionaryObject(
                {
                    NameObject("/Type"): NameObject("/Font"),
                    NameObject("/Subtype"): NameObject("/Type1"),
                    NameObject("/BaseFont"): NameObject("/Helvetica"),
                    NameObject("/Encoding"): NameObject("/WinAnsiEncoding"),
                }
            )
            resources = DictionaryObject(
                {NameObject("/Font"): DictionaryObject({NameObject("/F1"): writer._add_object(font)})}
            )
            page[NameObject("/Resources")] = resources

    buf = io.BytesIO()
    writer.write(buf)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# A. save_page_images
# ---------------------------------------------------------------------------

class TestSavePageImages:
    def test_saves_png_files_for_each_page(self, tmp_path):
        from ingest.round2 import save_page_images
        pdf_path = tmp_path / "manual.pdf"
        pdf_path.write_bytes(_make_pdf(["Page 1 content", "Page 2 content"]))

        out_dir = tmp_path / "images"
        paths = save_page_images(pdf_path, out_dir)

        assert len(paths) == 2
        for p in paths:
            assert p.exists()
            assert p.suffix == ".png"

    def test_output_dir_is_created_if_missing(self, tmp_path):
        from ingest.round2 import save_page_images
        pdf_path = tmp_path / "m.pdf"
        pdf_path.write_bytes(_make_pdf(["Content"]))
        out_dir = tmp_path / "subdir" / "images"
        assert not out_dir.exists()
        save_page_images(pdf_path, out_dir)
        assert out_dir.exists()

    def test_subset_of_pages(self, tmp_path):
        from ingest.round2 import save_page_images
        pdf_path = tmp_path / "three.pdf"
        pdf_path.write_bytes(_make_pdf(["P1", "P2", "P3"]))
        out_dir = tmp_path / "imgs"
        paths = save_page_images(pdf_path, out_dir, page_numbers=[1, 3])
        assert len(paths) == 2

    def test_missing_pdf_raises_image_export_error(self, tmp_path):
        from ingest.round2 import save_page_images, ImageExportError
        with pytest.raises(ImageExportError):
            save_page_images(tmp_path / "missing.pdf", tmp_path / "out")

    def test_out_of_range_page_is_skipped(self, tmp_path):
        from ingest.round2 import save_page_images
        pdf_path = tmp_path / "one.pdf"
        pdf_path.write_bytes(_make_pdf(["Only page"]))
        out_dir = tmp_path / "out"
        # page 99 does not exist — should be silently skipped, not crash
        paths = save_page_images(pdf_path, out_dir, page_numbers=[1, 99])
        assert len(paths) == 1


# ---------------------------------------------------------------------------
# B. describe_pages (Gemini — fully mocked)
# ---------------------------------------------------------------------------

class TestDescribePages:
    def _fake_image(self, tmp_path: Path) -> Path:
        """Write a 1x1 PNG so the function has something to read."""
        p = tmp_path / "page_0001.png"
        # Minimal valid PNG header (1×1 white pixel)
        p.write_bytes(
            b"\x89PNG\r\n\x1a\n"
            b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
            b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
            b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
        )
        return p

    def test_missing_api_key_raises_gemini_error(self, tmp_path, monkeypatch):
        from ingest.round2 import describe_pages, GeminiError
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        img = self._fake_image(tmp_path)
        with pytest.raises(GeminiError, match="GEMINI_API_KEY"):
            describe_pages([img], api_key="")

    def test_missing_genai_package_raises_gemini_error(self, tmp_path):
        from ingest.round2 import describe_pages, GeminiError
        img = self._fake_image(tmp_path)
        with patch.dict("sys.modules", {"google": None, "google.generativeai": None}):
            with pytest.raises(GeminiError, match="google-generativeai"):
                describe_pages([img], api_key="fake_key")

    def test_successful_description_returned(self, tmp_path):
        from ingest.round2 import describe_pages

        img = self._fake_image(tmp_path)

        mock_genai = MagicMock()
        mock_model_inst = MagicMock()
        mock_response = MagicMock()
        mock_response.text = "This page shows a boiler pressure diagram."
        mock_model_inst.generate_content.return_value = mock_response
        mock_genai.GenerativeModel.return_value = mock_model_inst
        mock_google = MagicMock()
        mock_google.generativeai = mock_genai

        with patch.dict("sys.modules", {
            "google": mock_google,
            "google.generativeai": mock_genai,
        }):
            results = describe_pages([img], api_key="fake_key", rpm=0)

        assert results[img] == "This page shows a boiler pressure diagram."

    def test_api_error_returns_empty_string(self, tmp_path):
        from ingest.round2 import describe_pages

        img = self._fake_image(tmp_path)

        mock_genai = MagicMock()
        mock_model_inst = MagicMock()
        mock_model_inst.generate_content.side_effect = Exception("503 Service Unavailable")
        mock_genai.GenerativeModel.return_value = mock_model_inst
        mock_google = MagicMock()
        mock_google.generativeai = mock_genai

        with patch.dict("sys.modules", {
            "google": mock_google,
            "google.generativeai": mock_genai,
        }):
            results = describe_pages(
                [img], api_key="key", rpm=0, max_retries=1
            )

        assert results[img] == ""


# ---------------------------------------------------------------------------
# C. tag_safety_chunks
# ---------------------------------------------------------------------------

class TestTagSafetyChunks:
    from ingest.pdf_ingestor import Chunk

    def _chunk(self, text: str, chunk_type: str = "text") -> "Chunk":
        from ingest.pdf_ingestor import Chunk
        return Chunk(
            text=text,
            doc_id="doc",
            page_number=1,
            chunk_index=0,
            chunk_type=chunk_type,
        )

    def test_safety_keyword_danger_is_tagged(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk("DANGER: Do not operate with the guard removed.")
        result = tag_safety_chunks([chunk])
        assert result[0].chunk_type == "safety"

    def test_warning_keyword_is_tagged(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk("WARNING: High voltage present.")
        result = tag_safety_chunks([chunk])
        assert result[0].chunk_type == "safety"

    def test_non_safety_chunk_unchanged(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk("Check the oil level every 500 hours.")
        result = tag_safety_chunks([chunk])
        assert result[0].chunk_type == "text"

    def test_mixed_list_tags_only_safety_chunks(self):
        from ingest.round2 import tag_safety_chunks
        chunks = [
            self._chunk("Normal maintenance procedure."),
            self._chunk("CAUTION: Wear PPE before servicing."),
            self._chunk("Replace filter every 6 months."),
            self._chunk("EMERGENCY stop procedure: pull red handle."),
        ]
        result = tag_safety_chunks(chunks)
        types = [c.chunk_type for c in result]
        assert types[0] == "text"
        assert types[1] == "safety"
        assert types[2] == "text"
        assert types[3] == "safety"

    def test_original_chunks_are_not_mutated(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk("WARNING: Keep hands clear.")
        tag_safety_chunks([chunk])
        # The original chunk should still have chunk_type="text"
        assert chunk.chunk_type == "text"

    def test_ppe_keyword_is_tagged(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk("Always wear PPE: hard hat, gloves, and safety boots.")
        result = tag_safety_chunks([chunk])
        assert result[0].chunk_type == "safety"

    def test_empty_list_returns_empty(self):
        from ingest.round2 import tag_safety_chunks
        assert tag_safety_chunks([]) == []

    def test_troubleshooting_row_safety_is_tagged(self):
        from ingest.round2 import tag_safety_chunks
        chunk = self._chunk(
            "Problem: Fire alarm\nCause: Overheating\nRemedy: Emergency shutdown",
            chunk_type="troubleshooting_row",
        )
        result = tag_safety_chunks([chunk])
        assert result[0].chunk_type == "safety"


# ---------------------------------------------------------------------------
# D. highlight_pdf
# ---------------------------------------------------------------------------

class TestHighlightPdf:
    def _make_pdf_file(self, tmp_path: Path, pages: list[str] | None = None) -> Path:
        if pages is None:
            pages = ["Valve inspection procedure. Check torque settings."]
        pdf_path = tmp_path / "source.pdf"
        pdf_path.write_bytes(_make_pdf(pages))
        return pdf_path

    def test_highlight_creates_output_file(self, tmp_path):
        from ingest.round2 import highlight_pdf
        src = self._make_pdf_file(tmp_path)
        out = tmp_path / "highlighted.pdf"
        result = highlight_pdf(src, out, page_number=1)
        assert result == out
        assert out.exists()
        assert out.stat().st_size > 0

    def test_highlight_with_bbox(self, tmp_path):
        from ingest.round2 import highlight_pdf
        from ingest.pdf_ingestor import BoundingBox
        src = self._make_pdf_file(tmp_path)
        out = tmp_path / "hl_bbox.pdf"
        bbox = BoundingBox(x0=50.0, y0=700.0, x1=400.0, y1=820.0)
        result = highlight_pdf(src, out, page_number=1, bbox=bbox)
        assert result.exists()

    def test_highlight_without_bbox_falls_back_to_full_page(self, tmp_path):
        from ingest.round2 import highlight_pdf
        src = self._make_pdf_file(tmp_path)
        out = tmp_path / "hl_full.pdf"
        result = highlight_pdf(src, out, page_number=1, bbox=None)
        assert result.exists()

    def test_out_of_range_page_raises_highlight_error(self, tmp_path):
        from ingest.round2 import highlight_pdf, HighlightError
        src = self._make_pdf_file(tmp_path)
        out = tmp_path / "err.pdf"
        with pytest.raises(HighlightError, match="out of range"):
            highlight_pdf(src, out, page_number=99)

    def test_missing_source_raises_highlight_error(self, tmp_path):
        from ingest.round2 import highlight_pdf, HighlightError
        with pytest.raises(HighlightError):
            highlight_pdf(
                tmp_path / "missing.pdf",
                tmp_path / "out.pdf",
                page_number=1,
            )

    def test_multi_page_pdf_highlight_correct_page(self, tmp_path):
        from ingest.round2 import highlight_pdf
        src = self._make_pdf_file(tmp_path, pages=["Page one.", "Page two.", "Page three."])
        out = tmp_path / "hl_p2.pdf"
        result = highlight_pdf(src, out, page_number=2)
        assert result.exists()
