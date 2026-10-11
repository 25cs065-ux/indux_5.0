# backend/tests/test_diagnose_photo.py
#
# Focused tests for POST /diagnose-photo
#
# Tests cover:
#   - Happy path: valid JPEG / PNG returns correct response shape
#   - Validation: empty file, file too large, wrong magic bytes, wrong content-type
#   - Error handling: ai_diagnose_photo raises → 503
#   - Response contract: all required keys present, types correct
#   - The endpoint never calls diagnose_photo on an invalid file
#
# No live credentials or Gemini API calls are made.
#
# Run with:
#   .venv\Scripts\python -m pytest backend/tests/test_diagnose_photo.py -v

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# ---------------------------------------------------------------------------
# Minimal synthetic image bytes
# ---------------------------------------------------------------------------

# A real JPEG begins with FF D8 FF (SOI + APP marker start).
_JPEG_MAGIC = b"\xff\xd8\xff\xe0" + b"\x00" * 100

# A real PNG begins with the 8-byte signature.
_PNG_MAGIC = b"\x89PNG\r\n\x1a\n" + b"\x00" * 100

# A GIF header (should be rejected).
_GIF_MAGIC = b"GIF89a" + b"\x00" * 100

# A PDF header (should be rejected).
_PDF_MAGIC = b"%PDF-1.4" + b"\x00" * 100

# Plain text (should be rejected).
_TEXT_CONTENT = b"this is not an image" + b"\x00" * 100

_DIAGNOSIS_RESULT = {
    "observed_condition": "Oil pooling under the filter housing.",
    "suggested_query": "There is oil leaking from the compressor.",
    "detected_problem_type": "oil leak",
}


# ---------------------------------------------------------------------------
# Fixture: TestClient with mocked Supabase and diagnose_photo
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    mock_sb = MagicMock()
    mock_diagnose = MagicMock(return_value=_DIAGNOSIS_RESULT)

    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai.brain.diagnose_photo", mock_diagnose):

        import importlib
        import backend.main as bmod
        importlib.reload(bmod)

        from fastapi.testclient import TestClient
        tc = TestClient(bmod.app, raise_server_exceptions=False)
        tc._mock_diagnose = mock_diagnose
        yield tc


def _post_image(client, image_bytes: bytes, filename: str = "photo.jpg",
                content_type: str = "image/jpeg") -> object:
    """POST a synthetic image to /diagnose-photo using multipart form-data."""
    return client.post(
        "/diagnose-photo",
        files={"image": (filename, io.BytesIO(image_bytes), content_type)},
    )


# ---------------------------------------------------------------------------
# 1. Happy path — valid JPEG
# ---------------------------------------------------------------------------

class TestDiagnosePhotoHappyPath:

    def test_200_on_valid_jpeg(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.status_code == 200

    def test_200_on_valid_png(self, client):
        resp = _post_image(client, _PNG_MAGIC, filename="photo.png",
                           content_type="image/png")
        assert resp.status_code == 200

    def test_status_success(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.json()["status"] == "success"

    def test_observed_condition_present(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.json()["observed_condition"] == _DIAGNOSIS_RESULT["observed_condition"]

    def test_suggested_query_present(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.json()["suggested_query"] == _DIAGNOSIS_RESULT["suggested_query"]

    def test_detected_problem_type_present(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.json()["detected_problem_type"] == _DIAGNOSIS_RESULT["detected_problem_type"]

    def test_jpeg_mime_type_passed_to_diagnose(self, client):
        _post_image(client, _JPEG_MAGIC, content_type="image/jpeg")
        call_kwargs = client._mock_diagnose.call_args
        mime_passed = call_kwargs.kwargs.get("mime_type") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert mime_passed == "image/jpeg"

    def test_png_mime_type_passed_to_diagnose(self, client):
        _post_image(client, _PNG_MAGIC, filename="photo.png",
                    content_type="image/png")
        call_kwargs = client._mock_diagnose.call_args
        mime_passed = call_kwargs.kwargs.get("mime_type") or (
            call_kwargs.args[1] if len(call_kwargs.args) > 1 else None
        )
        assert mime_passed == "image/png"

    def test_image_bytes_passed_to_diagnose(self, client):
        _post_image(client, _JPEG_MAGIC)
        call_args = client._mock_diagnose.call_args
        image_bytes_passed = call_args.args[0] if call_args.args else None
        assert image_bytes_passed is not None
        assert image_bytes_passed[:4] == _JPEG_MAGIC[:4]

    def test_content_type_is_json(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 2. Input validation — file-level checks
# ---------------------------------------------------------------------------

class TestDiagnosePhotoValidation:

    def test_empty_file_returns_422(self, client):
        resp = _post_image(client, b"")
        assert resp.status_code == 422

    def test_wrong_magic_bytes_returns_415(self, client):
        resp = _post_image(client, _GIF_MAGIC, filename="photo.gif",
                           content_type="image/gif")
        assert resp.status_code == 415

    def test_pdf_file_returns_415(self, client):
        resp = _post_image(client, _PDF_MAGIC, filename="doc.pdf",
                           content_type="application/pdf")
        assert resp.status_code == 415

    def test_text_disguised_as_jpeg_returns_415(self, client):
        """Magic bytes must be validated regardless of the filename extension."""
        resp = _post_image(client, _TEXT_CONTENT, filename="fake.jpg",
                           content_type="image/jpeg")
        assert resp.status_code == 415

    def test_oversized_file_returns_413(self, client):
        big = _JPEG_MAGIC + b"\x00" * (5 * 1024 * 1024 + 1)
        resp = _post_image(client, big)
        assert resp.status_code == 413

    def test_missing_image_field_returns_422(self, client):
        resp = client.post("/diagnose-photo")
        assert resp.status_code == 422

    def test_wrong_content_type_header_returns_415(self, client):
        """Content-type: text/plain is rejected before reading bytes."""
        resp = _post_image(client, _JPEG_MAGIC, content_type="text/plain")
        assert resp.status_code == 415

    def test_error_response_has_detail(self, client):
        resp = _post_image(client, b"")
        assert "detail" in resp.json()

    def test_diagnose_not_called_on_empty_file(self, client):
        _post_image(client, b"")
        client._mock_diagnose.assert_not_called()

    def test_diagnose_not_called_on_wrong_magic(self, client):
        _post_image(client, _GIF_MAGIC, filename="photo.gif",
                    content_type="image/jpeg")
        client._mock_diagnose.assert_not_called()


# ---------------------------------------------------------------------------
# 3. Response contract
# ---------------------------------------------------------------------------

class TestDiagnosePhotoResponseContract:

    REQUIRED_KEYS = {"status", "observed_condition", "suggested_query",
                     "detected_problem_type"}

    def test_all_keys_present(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        body = resp.json()
        for key in self.REQUIRED_KEYS:
            assert key in body, f"Key '{key}' missing from response"

    def test_all_values_are_strings(self, client):
        resp = _post_image(client, _JPEG_MAGIC)
        body = resp.json()
        for key in self.REQUIRED_KEYS:
            assert isinstance(body[key], str), f"Key '{key}' should be a string"

    def test_fallback_when_diagnose_returns_missing_fields(self, client):
        """If Gemini omits a key, the endpoint must still return all keys."""
        client._mock_diagnose.return_value = {}
        resp = _post_image(client, _JPEG_MAGIC)
        body = resp.json()
        for key in self.REQUIRED_KEYS:
            assert key in body
        assert body["observed_condition"] == ""
        assert body["suggested_query"] == ""
        assert body["detected_problem_type"] == "other"

    def test_partial_response_fills_defaults(self, client):
        """Only observed_condition is returned; other keys must still be present."""
        client._mock_diagnose.return_value = {
            "observed_condition": "Temperature gauge reads high."
        }
        resp = _post_image(client, _JPEG_MAGIC)
        body = resp.json()
        assert body["observed_condition"] == "Temperature gauge reads high."
        assert body["suggested_query"] == ""
        assert body["detected_problem_type"] == "other"


# ---------------------------------------------------------------------------
# 4. Error handling — AI helper raises
# ---------------------------------------------------------------------------

class TestDiagnosePhotoErrorHandling:

    def test_503_when_diagnose_raises(self, client):
        client._mock_diagnose.side_effect = RuntimeError("Gemini API error")
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.status_code == 503

    def test_503_detail_is_user_friendly(self, client):
        client._mock_diagnose.side_effect = Exception("Internal crash")
        resp = _post_image(client, _JPEG_MAGIC)
        body = resp.json()
        assert "detail" in body
        assert "Internal crash" not in body["detail"]

    def test_503_on_json_parse_error(self, client):
        """If diagnose_photo raises (e.g. json.loads fails inside), return 503."""
        import json
        client._mock_diagnose.side_effect = json.JSONDecodeError("bad", "", 0)
        resp = _post_image(client, _JPEG_MAGIC)
        assert resp.status_code == 503
