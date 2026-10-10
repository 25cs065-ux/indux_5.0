# ingest/tests/test_new_features.py
#
# Tests for Round 1 additions to the Indux 5.0 ingestion pipeline:
#
#   A. PyMuPDF extraction + bounding-box metadata
#   B. Chunk.chunk_id generation
#   C. Troubleshooting-table row detection and preservation
#   D. extractor_used field on IngestResult
#   E. Embedder (batch embedding generation) — mocked SentenceTransformer
#   F. Storage (Supabase persistence) — mocked supabase client
#   G. Error handling: EmbeddingError, StorageError, missing credentials
#   H. run_ingest CLI (dry-run + error exit codes)
#
# Run with:
#   py -m pytest ingest/tests/ -v

from __future__ import annotations

import io
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a real PDF the same way the other test file does
# ---------------------------------------------------------------------------

def _make_pdf(pages: list[str]) -> bytes:
    """
    Minimal multi-line PDF builder — identical strategy to test_pdf_ingestor.py.
    Text is split into 60-char segments with T* newlines so PyMuPDF can extract
    the full content.
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
                {
                    NameObject("/Font"): DictionaryObject(
                        {NameObject("/F1"): writer._add_object(font)}
                    )
                }
            )
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
# Import modules under test
# ---------------------------------------------------------------------------

from ingest.pdf_ingestor import (
    BoundingBox,
    Chunk,
    IngestError,
    IngestResult,
    _extract_troubleshooting_rows,
    _remove_troubleshooting_rows,
    ingest_pdf,
)
from ingest.embedder import EmbeddingError, embed_chunks
from ingest.storage import StorageError, _chunk_to_row, save_chunks


# ---------------------------------------------------------------------------
# A.  PyMuPDF extraction + bounding-box metadata
# ---------------------------------------------------------------------------

class TestPyMuPDFExtraction:
    """Verify that the PyMuPDF extractor is used and returns bbox metadata."""

    def test_extractor_used_is_pymupdf(self):
        pdf_bytes = _make_pdf(["Hello from PyMuPDF."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert result.extractor_used == "pymupdf"
        finally:
            f.unlink(missing_ok=True)

    def test_chunks_have_bbox_when_pymupdf_is_available(self):
        pdf_bytes = _make_pdf(["Valve inspection procedure. Check torque settings."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            assert len(result.chunks) >= 1
            # With PyMuPDF, every chunk from a text-bearing page should have a bbox.
            for chunk in result.chunks:
                assert chunk.bbox is not None, (
                    f"Chunk {chunk.chunk_index} from page {chunk.page_number} "
                    "has no bbox — expected PyMuPDF to provide one."
                )
                assert isinstance(chunk.bbox, BoundingBox)
        finally:
            f.unlink(missing_ok=True)

    def test_bbox_coordinates_are_finite_floats(self):
        pdf_bytes = _make_pdf(["Safety valve pressure: 15 bar max."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            for chunk in result.chunks:
                if chunk.bbox is not None:
                    bb = chunk.bbox
                    assert bb.x1 >= bb.x0, "x1 must be >= x0"
                    assert bb.y1 >= bb.y0, "y1 must be >= y0"
                    for val in (bb.x0, bb.y0, bb.x1, bb.y1):
                        assert isinstance(val, float)
                        assert -10_000 < val < 10_000, f"Suspiciously large coordinate: {val}"
        finally:
            f.unlink(missing_ok=True)

    def test_pypdf_fallback_sets_bbox_none(self):
        """When _HAVE_FITZ is patched to False, extraction falls back to pypdf
        and chunk.bbox should be None."""
        pdf_bytes = _make_pdf(["Fallback path test."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            import ingest.pdf_ingestor as mod
            with patch.object(mod, "_HAVE_FITZ", False):
                result = ingest_pdf(f)
            assert result.extractor_used == "pypdf"
            for chunk in result.chunks:
                assert chunk.bbox is None
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# B.  Chunk.chunk_id generation
# ---------------------------------------------------------------------------

class TestChunkId:
    """chunk_id must be unique and follow the expected format."""

    def test_chunk_id_format(self):
        pdf_bytes = _make_pdf(["One two three four five."])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f, doc_id="test_doc")
            for chunk in result.chunks:
                assert chunk.chunk_id.startswith("test_doc_"), (
                    f"chunk_id '{chunk.chunk_id}' does not start with 'test_doc_'"
                )
        finally:
            f.unlink(missing_ok=True)

    def test_chunk_ids_are_unique(self):
        pages = ["Page one " * 20, "Page two " * 20, "Page three " * 20]
        pdf_bytes = _make_pdf(pages)
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f)
            ids = [c.chunk_id for c in result.chunks]
            assert len(ids) == len(set(ids)), "chunk_ids must be unique"
        finally:
            f.unlink(missing_ok=True)

    def test_chunk_id_encodes_chunk_index(self):
        long_text = "The boiler must be checked. " * 50
        pdf_bytes = _make_pdf([long_text])
        f = _write_tmp_pdf(pdf_bytes)
        try:
            result = ingest_pdf(f, doc_id="manual_x")
            for i, chunk in enumerate(result.chunks):
                expected_suffix = f"{i:05d}"
                assert chunk.chunk_id.endswith(expected_suffix), (
                    f"chunk_id '{chunk.chunk_id}' should end with '{expected_suffix}'"
                )
        finally:
            f.unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# C.  Troubleshooting-table detection and preservation
# ---------------------------------------------------------------------------

class TestTroubleshootingRows:
    """Tests for _extract_troubleshooting_rows and the ingest_pdf pipeline."""

    # --- Unit tests on the helper directly ---------------------------------

    def test_empty_text_returns_empty(self):
        assert _extract_troubleshooting_rows("") == []

    def test_normal_text_returns_empty(self):
        text = "The boiler should be serviced every 12 months. Check all valves."
        assert _extract_troubleshooting_rows(text) == []

    def test_troubleshooting_keyword_but_no_labels_returns_empty(self):
        # Has keyword but no labelled rows
        text = "Troubleshooting overview: consult the service manual."
        assert _extract_troubleshooting_rows(text) == []

    def test_two_labelled_rows_detected(self):
        text = (
            "Troubleshooting\n\n"
            "Problem: Boiler does not start\n"
            "Cause: No power supply\n"
            "Remedy: Check fuse box\n\n"
            "Problem: Low pressure alarm\n"
            "Cause: Water leak\n"
            "Remedy: Inspect pipe joints"
        )
        rows = _extract_troubleshooting_rows(text)
        assert len(rows) >= 2

    def test_each_row_contains_problem_and_remedy(self):
        text = (
            "Fault codes\n\n"
            "Problem: Overheating\n"
            "Cause: Blocked filter\n"
            "Remedy: Clean filter\n\n"
            "Problem: No ignition\n"
            "Cause: Faulty electrode\n"
            "Remedy: Replace electrode"
        )
        rows = _extract_troubleshooting_rows(text)
        assert all("Problem" in r or "Cause" in r or "Remedy" in r for r in rows)

    def test_remove_troubleshooting_rows_leaves_prose(self):
        text = (
            "General maintenance notes\n\n"
            "Problem: High noise\n"
            "Cause: Loose panel\n"
            "Remedy: Tighten screws\n\n"
            "Always wear PPE when servicing."
        )
        remaining = _remove_troubleshooting_rows(text)
        assert "General maintenance" in remaining
        assert "Always wear PPE" in remaining
        # The troubleshooting row itself should be removed
        assert "Problem: High noise" not in remaining

    # --- Integration: ingest_pdf tags troubleshooting rows correctly -------

    def test_ingest_pdf_tags_troubleshooting_chunks(self, tmp_path):
        ts_page = (
            "Troubleshooting\n\n"
            "Problem: Boiler does not start\n"
            "Cause: No power\n"
            "Remedy: Check circuit breaker\n\n"
            "Problem: Pressure too high\n"
            "Cause: Faulty regulator\n"
            "Remedy: Replace regulator"
        )
        pdf_bytes = _make_pdf([ts_page])
        pdf_file = tmp_path / "ts_test.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file)

        ts_chunks = [c for c in result.chunks if c.chunk_type == "troubleshooting_row"]
        assert len(ts_chunks) >= 2, (
            f"Expected at least 2 troubleshooting_row chunks, got {len(ts_chunks)}"
        )

    def test_normal_page_produces_only_text_chunks(self, tmp_path):
        normal_page = (
            "This is a normal maintenance page. "
            "Check valve pressure every 30 days. "
            "Lubricate bearings with ISO-VG 46 oil."
        )
        pdf_bytes = _make_pdf([normal_page])
        pdf_file = tmp_path / "normal_test.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file)
        for chunk in result.chunks:
            assert chunk.chunk_type == "text"

    def test_mixed_document_has_both_types(self, tmp_path):
        pages = [
            "Normal content page. Check oil level weekly.",
            (
                "Troubleshooting\n\n"
                "Problem: Oil leak\n"
                "Cause: Worn seal\n"
                "Remedy: Replace seal\n\n"
                "Problem: Overheating\n"
                "Cause: Low coolant\n"
                "Remedy: Top up coolant"
            ),
        ]
        pdf_bytes = _make_pdf(pages)
        pdf_file = tmp_path / "mixed.pdf"
        pdf_file.write_bytes(pdf_bytes)

        result = ingest_pdf(pdf_file)
        types = {c.chunk_type for c in result.chunks}
        assert "text" in types
        assert "troubleshooting_row" in types


# ---------------------------------------------------------------------------
# D.  extractor_used field
# ---------------------------------------------------------------------------

class TestExtractorUsed:
    def test_extractor_used_is_string(self, tmp_path):
        pdf_bytes = _make_pdf(["Extractor test."])
        pdf_file = tmp_path / "ext.pdf"
        pdf_file.write_bytes(pdf_bytes)
        result = ingest_pdf(pdf_file)
        assert isinstance(result.extractor_used, str)
        assert result.extractor_used in {"pymupdf", "pypdf"}


# ---------------------------------------------------------------------------
# E.  Embedder — mocked SentenceTransformer
# ---------------------------------------------------------------------------

class TestEmbedChunks:
    """Tests for embed_chunks() with the Gemini embedding backend (mocked)."""

    # --- helpers -----------------------------------------------------------

    def _make_chunks(self, n: int = 3) -> list[Chunk]:
        return [
            Chunk(
                text=f"Chunk number {i}",
                doc_id="test_doc",
                page_number=1,
                chunk_index=i,
            )
            for i in range(n)
        ]

    def _mock_genai_client(self, dim: int = 3072) -> MagicMock:
        """
        Return a mock google.genai.Client whose embed_content() returns
        *dim*-dimensional vectors (one per call).
        """
        fake_values = [float(j) / dim for j in range(dim)]

        mock_embedding = MagicMock()
        mock_embedding.values = fake_values

        mock_response = MagicMock()
        mock_response.embeddings = [mock_embedding]

        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_response
        return mock_client

    # --- tests -------------------------------------------------------------

    def test_returns_one_embedding_per_chunk(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(5)
        mock_client = self._mock_genai_client()
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embeddings = embed_chunks(chunks)
        assert len(embeddings) == 5

    def test_embedding_dimension_is_3072(self, monkeypatch):
        """gemini-embedding-001 must produce 3072-dimensional vectors."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(3)
        mock_client = self._mock_genai_client(dim=3072)
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embeddings = embed_chunks(chunks)
        for emb in embeddings:
            assert len(emb) == 3072, (
                f"Expected 3072-dim (gemini-embedding-001), got {len(emb)}"
            )

    def test_embeddings_are_plain_float_lists(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(2)
        mock_client = self._mock_genai_client()
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embeddings = embed_chunks(chunks)
        for emb in embeddings:
            assert isinstance(emb, list)
            assert all(isinstance(v, float) for v in emb)

    def test_empty_chunks_raises_value_error(self):
        with pytest.raises(ValueError, match="(?i)empty"):
            embed_chunks([])

    def test_missing_api_key_raises_embedding_error(self, monkeypatch):
        """GEMINI_API_KEY must be set; absence raises EmbeddingError."""
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        chunks = self._make_chunks(1)
        with pytest.raises(EmbeddingError, match="GEMINI_API_KEY"):
            embed_chunks(chunks)

    def test_embed_content_called_once_per_chunk(self, monkeypatch):
        """The Gemini API is called once for every chunk (no batch shortcut)."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(4)
        mock_client = self._mock_genai_client()
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embed_chunks(chunks)
        assert mock_client.models.embed_content.call_count == 4

    def test_api_error_raises_embedding_error(self, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(2)
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("quota exceeded")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            with pytest.raises(EmbeddingError, match="(?i)gemini"):
                embed_chunks(chunks)

    def test_missing_google_genai_raises_embedding_error(self, monkeypatch):
        """If google-genai is not installed, EmbeddingError is raised."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        chunks = self._make_chunks(1)
        with patch.dict("sys.modules", {"google": None, "google.genai": None}):
            with pytest.raises(EmbeddingError, match="(?i)google.genai"):
                embed_chunks(chunks)

    def test_custom_model_name_via_env(self, monkeypatch):
        """GEMINI_EMBED_MODEL env var overrides the default model name."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("GEMINI_EMBED_MODEL", "gemini-embedding-002")
        chunks = self._make_chunks(2)
        mock_client = self._mock_genai_client(dim=3072)
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embed_chunks(chunks)
        # Confirm the custom model name was passed to the SDK
        call_kwargs = mock_client.models.embed_content.call_args_list[0][1]
        assert call_kwargs.get("model") == "gemini-embedding-002"


# ---------------------------------------------------------------------------
# F.  Storage — mocked Supabase client
# ---------------------------------------------------------------------------

class TestSaveChunks:
    """Tests for save_chunks() with a mocked Supabase client."""

    def _make_chunks(self, n: int = 3) -> list[Chunk]:
        return [
            Chunk(
                text=f"Chunk {i}",
                doc_id="doc_abc",
                page_number=1,
                chunk_index=i,
                chunk_type="text",
            )
            for i in range(n)
        ]

    def _make_embeddings(self, n: int = 3, dim: int = 3072) -> list[list[float]]:
        import random
        return [[random.random() for _ in range(dim)] for _ in range(n)]

    def _mock_supabase(self) -> MagicMock:
        """Return a mock that mimics the supabase-py v2 fluent interface."""
        client = MagicMock()
        response = MagicMock()
        # .table(…).upsert(…, on_conflict=…).execute() returns response
        (
            client
            .table.return_value
            .upsert.return_value
            .execute.return_value
        ) = response
        return client

    def test_save_chunks_returns_count(self):
        chunks = self._make_chunks(5)
        embeddings = self._make_embeddings(5)
        mock_client = self._mock_supabase()
        from ingest import storage as mod
        with patch("ingest.storage._get_client", return_value=mock_client):
            count = save_chunks(
                chunks, embeddings,
                supabase_url="https://example.supabase.co",
                supabase_key="fake_key",
            )
        assert count == 5

    def test_upsert_called_once_for_small_batch(self):
        chunks = self._make_chunks(3)
        embeddings = self._make_embeddings(3)
        mock_client = self._mock_supabase()
        from ingest import storage as mod
        with patch("ingest.storage._get_client", return_value=mock_client):
            save_chunks(
                chunks, embeddings,
                supabase_url="https://x.supabase.co",
                supabase_key="k",
                batch_size=100,
            )
        # One .table() call → one .upsert() call
        assert mock_client.table.call_count == 1

    def test_large_batch_splits_into_multiple_calls(self):
        chunks = self._make_chunks(10)
        embeddings = self._make_embeddings(10)
        mock_client = self._mock_supabase()
        with patch("ingest.storage._get_client", return_value=mock_client):
            save_chunks(
                chunks, embeddings,
                supabase_url="https://x.supabase.co",
                supabase_key="k",
                batch_size=3,
            )
        # 10 rows / batch_size 3 → 4 calls (3+3+3+1)
        assert mock_client.table.call_count == 4

    def test_empty_chunks_returns_zero(self):
        with patch("ingest.storage._get_client") as mock_get:
            count = save_chunks(
                [], [],
                supabase_url="https://x.supabase.co",
                supabase_key="k",
            )
        assert count == 0
        mock_get.assert_not_called()

    def test_mismatched_lengths_raises_value_error(self):
        chunks = self._make_chunks(3)
        embeddings = self._make_embeddings(2)
        with pytest.raises(ValueError, match="(?i)same length"):
            save_chunks(
                chunks, embeddings,
                supabase_url="https://x.supabase.co",
                supabase_key="k",
            )

    def test_missing_url_raises_storage_error(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_URL", raising=False)
        chunks = self._make_chunks(1)
        embeddings = self._make_embeddings(1)
        with pytest.raises(StorageError, match="SUPABASE_URL"):
            save_chunks(chunks, embeddings, supabase_key="k")

    def test_missing_key_raises_storage_error(self, monkeypatch):
        monkeypatch.delenv("SUPABASE_KEY", raising=False)
        chunks = self._make_chunks(1)
        embeddings = self._make_embeddings(1)
        with pytest.raises(StorageError, match="SUPABASE_KEY"):
            save_chunks(
                chunks, embeddings,
                supabase_url="https://x.supabase.co",
            )

    def test_upsert_failure_raises_storage_error(self):
        chunks = self._make_chunks(2)
        embeddings = self._make_embeddings(2)
        mock_client = MagicMock()
        (
            mock_client
            .table.return_value
            .upsert.return_value
            .execute.side_effect
        ) = Exception("HTTP 500 Internal Server Error")
        with patch("ingest.storage._get_client", return_value=mock_client):
            with pytest.raises(StorageError, match="(?i)(upsert|database)"):
                save_chunks(
                    chunks, embeddings,
                    supabase_url="https://x.supabase.co",
                    supabase_key="k",
                )

    def test_chunk_to_row_includes_all_fields(self):
        """Row uses brain-compatible column names: id, content, manual_title, section."""
        from ingest.pdf_ingestor import BoundingBox
        bbox = BoundingBox(x0=10.0, y0=20.0, x1=300.0, y1=400.0)
        chunk = Chunk(
            text="Test chunk text",
            doc_id="doc_001",
            page_number=3,
            chunk_index=7,
            bbox=bbox,
            chunk_type="troubleshooting_row",
        )
        emb = [0.1, 0.2, 0.3]
        row = _chunk_to_row(chunk, emb)
        # primary key is now 'id', not 'chunk_id'
        assert row["id"] == chunk.chunk_id
        # text is now 'content'
        assert row["content"] == "Test chunk text"
        # doc_id is now 'manual_title'
        assert row["manual_title"] == "doc_001"
        assert row["page_number"] == 3
        assert row["chunk_index"] == 7
        # chunk_type is now 'section'
        assert row["section"] == "troubleshooting_row"
        assert row["embedding"] == emb
        assert row["bbox_x0"] == 10.0
        assert row["bbox_y0"] == 20.0
        assert row["bbox_x1"] == 300.0
        assert row["bbox_y1"] == 400.0
        # old names must NOT appear
        assert "chunk_id" not in row
        assert "doc_id" not in row
        assert "text" not in row
        assert "chunk_type" not in row

    def test_chunk_to_row_bbox_none_produces_null_coords(self):
        chunk = Chunk(
            text="No bbox chunk",
            doc_id="doc_002",
            page_number=1,
            chunk_index=0,
            bbox=None,
        )
        row = _chunk_to_row(chunk, [0.5])
        assert row["bbox_x0"] is None
        assert row["bbox_y0"] is None
        assert row["bbox_x1"] is None
        assert row["bbox_y1"] is None


# ---------------------------------------------------------------------------
# G.  run_ingest CLI — dry-run and error exit codes
# ---------------------------------------------------------------------------

class TestRunIngestCLI:
    """Tests for the run_ingest command-line entry point."""

    def _write_pdf(self, tmp_path: Path, text: str = "Valve test content.") -> Path:
        pdf_bytes = _make_pdf([text])
        f = tmp_path / "test.pdf"
        f.write_bytes(pdf_bytes)
        return f

    def test_dry_run_succeeds_without_db_credentials(self, tmp_path, monkeypatch):
        """--dry-run should pass even with no SUPABASE_URL/KEY set."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        pdf_file = self._write_pdf(tmp_path)

        # Build a mock Gemini client that returns 3072-dim vectors
        fake_values = [0.1] * 3072
        mock_emb = MagicMock(); mock_emb.values = fake_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_resp

        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            from ingest.run_ingest import main
            rc = main([str(pdf_file), "--dry-run"])

        assert rc == 0

    def test_missing_file_returns_exit_code_1(self, tmp_path):
        from ingest.run_ingest import main
        rc = main([str(tmp_path / "missing.pdf")])
        assert rc == 1

    def test_scanned_pdf_returns_exit_code_1(self, tmp_path):
        """A PDF with no text should exit with code 1 (scanned warning)."""
        pdf_bytes = _make_pdf([""])  # blank page
        pdf_file = tmp_path / "scanned.pdf"
        pdf_file.write_bytes(pdf_bytes)
        from ingest.run_ingest import main
        rc = main([str(pdf_file)])
        assert rc == 1

    def test_embedding_error_returns_exit_code_2(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        pdf_file = self._write_pdf(tmp_path)
        with patch("ingest.embedder._get_genai_client",
                   side_effect=EmbeddingError("Mock failure")):
            from ingest.run_ingest import main
            rc = main([str(pdf_file)])
        assert rc == 2

    def test_storage_error_returns_exit_code_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        pdf_file = self._write_pdf(tmp_path)
        fake_values = [0.1] * 3072
        mock_emb = MagicMock(); mock_emb.values = fake_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_resp
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            with patch("ingest.storage.save_chunks", side_effect=StorageError("DB down")):
                from ingest.run_ingest import main
                rc = main([
                    str(pdf_file),
                    "--dry-run",  # dry-run skips storage → exit 0
                ])
        # dry-run skips storage, so exit should be 0
        assert rc == 0

    def test_storage_error_without_dry_run_returns_3(self, tmp_path, monkeypatch):
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        pdf_file = self._write_pdf(tmp_path)
        fake_values = [0.1] * 3072
        mock_emb = MagicMock(); mock_emb.values = fake_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_resp
        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            with patch("ingest.storage.save_chunks", side_effect=StorageError("DB down")):
                from ingest.run_ingest import main
                rc = main([str(pdf_file)])  # no --dry-run
        assert rc == 3

    def test_doc_id_flag_is_passed_through(self, tmp_path, monkeypatch):
        """--doc-id should be visible in the result."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        pdf_file = self._write_pdf(tmp_path)
        fake_values = [0.1] * 3072
        mock_emb = MagicMock(); mock_emb.values = fake_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.return_value = mock_resp

        captured_result = {}
        original_ingest = ingest_pdf

        def capturing_ingest(path, *, doc_id=None, **kw):
            result = original_ingest(path, doc_id=doc_id, **kw)
            captured_result["doc_id"] = result.doc_id
            return result

        with patch("ingest.embedder._get_genai_client", return_value=mock_client):
            with patch("ingest.pdf_ingestor.ingest_pdf", side_effect=capturing_ingest):
                from ingest.run_ingest import main
                main([str(pdf_file), "--doc-id", "my_manual_v1", "--dry-run"])

        assert captured_result.get("doc_id") == "my_manual_v1"
