# admin-app/tests/test_admin_app.py
#
# Tests for the Indux 5.0 admin app (FastAPI).
#
# Run with:
#   py -m pytest admin-app/tests/ -v
#
# All database and embedding calls are mocked — no real Supabase/model needed.

from __future__ import annotations

import io
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

# ---------------------------------------------------------------------------
# Helper: build minimal PDF bytes (same pattern as ingest tests)
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
# Import the app via importlib (admin-app has a hyphen, not directly importable)
# ---------------------------------------------------------------------------

import importlib.util

_ADMIN_APP_DIR = Path(__file__).resolve().parent.parent
_ADMIN_MAIN = _ADMIN_APP_DIR / "main.py"

# Add admin-app/ to sys.path so relative imports inside main.py work.
if str(_ADMIN_APP_DIR.parent) not in sys.path:
    sys.path.insert(0, str(_ADMIN_APP_DIR.parent))
if str(_ADMIN_APP_DIR) not in sys.path:
    sys.path.insert(0, str(_ADMIN_APP_DIR))

spec = importlib.util.spec_from_file_location("admin_app_main", _ADMIN_MAIN)
admin_module = importlib.util.module_from_spec(spec)
sys.modules["admin_app_main"] = admin_module
spec.loader.exec_module(admin_module)

app        = admin_module.app
_jobs      = admin_module._jobs
_jobs_lock = admin_module._jobs_lock
JobStatus  = admin_module.JobStatus
IngestionJob = admin_module.IngestionJob


@pytest.fixture(autouse=True)
def clear_jobs():
    """Reset the in-memory job store before each test."""
    with _jobs_lock:
        _jobs.clear()
    yield
    with _jobs_lock:
        _jobs.clear()


@pytest.fixture
def client():
    return TestClient(app, raise_server_exceptions=False)


# ---------------------------------------------------------------------------
# Health check
# ---------------------------------------------------------------------------

class TestHealth:
    def test_health_returns_ok(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"


# ---------------------------------------------------------------------------
# Dashboard (GET /)
# ---------------------------------------------------------------------------

class TestDashboard:
    def test_dashboard_returns_html(self, client):
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_dashboard_contains_upload_form(self, client):
        resp = client.get("/")
        assert b"upload" in resp.content.lower()
        assert b"pdf" in resp.content.lower()

    def test_dashboard_shows_empty_state_message(self, client):
        resp = client.get("/")
        assert b"No jobs yet" in resp.content

    def test_dashboard_shows_job_when_present(self, client):
        import time
        with _jobs_lock:
            _jobs["abc123"] = IngestionJob(
                job_id="abc123",
                filename="boiler.pdf",
                doc_id="doc_x",
                status=JobStatus.DONE,
                progress="Done — 5 chunks saved.",
                chunks=5,
                pages=2,
            )
        resp = client.get("/")
        assert b"boiler.pdf" in resp.content
        assert b"done" in resp.content.lower()


# ---------------------------------------------------------------------------
# Upload endpoint (POST /upload)
# ---------------------------------------------------------------------------

class TestUpload:
    def _post_pdf(self, client, pdf_bytes: bytes, filename: str = "manual.pdf", doc_id: str = ""):
        files = {"pdf_file": (filename, io.BytesIO(pdf_bytes), "application/pdf")}
        data = {"doc_id": doc_id} if doc_id else {}
        return client.post("/upload", files=files, data=data, follow_redirects=False)

    def test_valid_pdf_upload_creates_job(self, client):
        pdf = _make_pdf(["Boiler manual content."])
        resp = self._post_pdf(client, pdf)
        # Should redirect to dashboard (303)
        assert resp.status_code == 303
        with _jobs_lock:
            assert len(_jobs) == 1

    def test_non_pdf_content_returns_400(self, client):
        resp = self._post_pdf(client, b"This is not a PDF", "fake.pdf")
        assert resp.status_code == 400

    def test_wrong_extension_returns_400(self, client):
        pdf = _make_pdf(["content"])
        resp = self._post_pdf(client, pdf, filename="manual.txt")
        assert resp.status_code == 400

    def test_empty_file_returns_400(self, client):
        resp = self._post_pdf(client, b"", "empty.pdf")
        assert resp.status_code == 400

    def test_job_has_correct_filename(self, client):
        pdf = _make_pdf(["Content."])
        self._post_pdf(client, pdf, filename="test_manual.pdf")
        with _jobs_lock:
            job = list(_jobs.values())[0]
        assert job.filename == "test_manual.pdf"

    def test_doc_id_is_stored_in_job(self, client):
        pdf = _make_pdf(["Content."])
        self._post_pdf(client, pdf, "manual.pdf", doc_id="pump_v2")
        with _jobs_lock:
            job = list(_jobs.values())[0]
        assert job.doc_id == "pump_v2"

    def test_job_starts_in_queued_or_running_state(self, client):
        pdf = _make_pdf(["Content."])
        self._post_pdf(client, pdf)
        with _jobs_lock:
            job = list(_jobs.values())[0]
        assert job.status in (JobStatus.QUEUED, JobStatus.RUNNING)


# ---------------------------------------------------------------------------
# Job listing (GET /jobs)
# ---------------------------------------------------------------------------

class TestJobsAPI:
    def test_jobs_returns_empty_list_initially(self, client):
        resp = client.get("/jobs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_jobs_lists_all_jobs(self, client):
        with _jobs_lock:
            _jobs["j1"] = IngestionJob(job_id="j1", filename="a.pdf", doc_id=None)
            _jobs["j2"] = IngestionJob(job_id="j2", filename="b.pdf", doc_id="doc_b")
        resp = client.get("/jobs")
        assert len(resp.json()) == 2

    def test_job_has_required_fields(self, client):
        with _jobs_lock:
            _jobs["x"] = IngestionJob(job_id="x", filename="x.pdf", doc_id=None)
        data = client.get("/jobs").json()[0]
        for field in ("job_id", "filename", "status", "progress", "chunks", "pages"):
            assert field in data, f"Missing field: {field}"


# ---------------------------------------------------------------------------
# Single job (GET /jobs/{job_id})
# ---------------------------------------------------------------------------

class TestSingleJob:
    def test_get_existing_job(self, client):
        with _jobs_lock:
            _jobs["abc"] = IngestionJob(
                job_id="abc", filename="x.pdf", doc_id=None, status=JobStatus.DONE
            )
        resp = client.get("/jobs/abc")
        assert resp.status_code == 200
        assert resp.json()["job_id"] == "abc"
        assert resp.json()["status"] == "done"

    def test_get_missing_job_returns_404(self, client):
        resp = client.get("/jobs/nonexistent")
        assert resp.status_code == 404
