# backend/tests/test_manual_page.py
#
# Tests for GET /manual-page
#
# The endpoint renders a PDF page to PNG using ingest.round2.save_page_images.
# All filesystem/rendering calls are mocked — no real PDFs or PyMuPDF needed.
#
# Run with:
#   .venv\Scripts\python -m pytest backend/tests/test_manual_page.py -v

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch, call
import tempfile

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Minimal 1×1 white PNG bytes (valid PNG magic)
_FAKE_PNG = (
    b"\x89PNG\r\n\x1a\n"
    b"\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02"
    b"\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f\x00"
    b"\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
)


@pytest.fixture()
def client(monkeypatch, tmp_path):
    """
    Return a TestClient for backend.main with:
      - Supabase mocked (no real credentials)
      - ingest.round2.save_page_images mocked to return a fake PNG file
      - _MANUALS_DIR overridden to a temp dir containing a fake PDF file
    """
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    # Create a fake PDF file in a temp manuals dir.
    fake_manuals_dir = tmp_path / "manuals"
    fake_manuals_dir.mkdir()
    fake_pdf = fake_manuals_dir / "GA15-26_Instruction_Book.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")

    # save_page_images mock: writes _FAKE_PNG to a temp file and returns [path].
    def _mock_save_page_images(pdf_path, out_dir, *, dpi=150, page_numbers=None, fmt="png"):
        out_path = Path(out_dir) / "page.png"
        out_path.write_bytes(_FAKE_PNG)
        # Return empty if the requested page is out of range (simulate)
        if page_numbers and page_numbers[0] > 999:
            return []
        return [out_path]

    mock_sb = MagicMock()

    with patch("supabase.create_client", return_value=mock_sb):
        import importlib
        import backend.main as bmod
        importlib.reload(bmod)

        # Override the manuals directory to our temp directory.
        bmod._MANUALS_DIR = fake_manuals_dir

        with patch("ingest.round2.save_page_images", side_effect=_mock_save_page_images):
            from fastapi.testclient import TestClient
            tc = TestClient(bmod.app, raise_server_exceptions=False)
            tc._fake_manuals_dir = fake_manuals_dir
            tc._fake_pdf = fake_pdf
            yield tc


# ---------------------------------------------------------------------------
# 1. Happy path
# ---------------------------------------------------------------------------

class TestManualPageHappyPath:

    def test_200_on_valid_request(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=1")
        assert resp.status_code == 200

    def test_content_type_is_png(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=1")
        assert "image/png" in resp.headers.get("content-type", "")

    def test_response_body_starts_with_png_magic(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=1")
        assert resp.content[:4] == b"\x89PNG"

    def test_accepts_pdf_suffix_in_manual_name(self, client):
        """manual=GA15-26_Instruction_Book.pdf should work the same as without .pdf."""
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book.pdf&page=1")
        assert resp.status_code == 200

    def test_page_2_is_accepted(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=2")
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# 2. Validation
# ---------------------------------------------------------------------------

class TestManualPageValidation:

    def test_page_zero_returns_422(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=0")
        assert resp.status_code == 422

    def test_negative_page_returns_422(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=-1")
        assert resp.status_code == 422

    def test_missing_manual_param_returns_422(self, client):
        resp = client.get("/manual-page?page=1")
        assert resp.status_code == 422

    def test_missing_page_param_returns_422(self, client):
        resp = client.get("/manual-page?manual=GA15-26_Instruction_Book")
        assert resp.status_code == 422

    def test_unknown_manual_returns_404(self, client):
        resp = client.get("/manual-page?manual=does_not_exist&page=1")
        assert resp.status_code == 404

    def test_404_has_detail(self, client):
        resp = client.get("/manual-page?manual=does_not_exist&page=1")
        assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# 3. Error handling — renderer raises
# ---------------------------------------------------------------------------

class TestManualPageErrorHandling:

    def test_503_when_render_raises(self, client):
        with patch("ingest.round2.save_page_images", side_effect=RuntimeError("PyMuPDF unavailable")):
            resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=1")
        assert resp.status_code == 503

    def test_503_detail_is_user_friendly(self, client):
        with patch("ingest.round2.save_page_images", side_effect=Exception("Internal crash")):
            resp = client.get("/manual-page?manual=GA15-26_Instruction_Book&page=1")
        body = resp.json()
        assert "detail" in body
        assert "Internal crash" not in body["detail"]
