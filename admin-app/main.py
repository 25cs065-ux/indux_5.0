# admin-app/main.py
#
# Indux 5.0 — Admin App
#
# A lightweight FastAPI application for administrators to:
#   1. Upload PDF manuals for ingestion
#   2. Monitor ingestion job progress / status
#   3. View a basic dashboard of ingested documents
#
# Usage:
#   py -m uvicorn admin-app.main:app --reload  (from repo root)
#   OR:
#   cd admin-app && py -m uvicorn main:app --reload
#
# Environment variables:
#   SUPABASE_URL   : Supabase project endpoint
#   SUPABASE_KEY   : Supabase service-role key
#   EMBED_MODEL    : sentence-transformers model (default: all-MiniLM-L6-v2)
#
# Upload directory (temp storage before ingestion):
#   admin-app/uploads/   (created automatically)

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import threading
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional

# Add repo root to sys.path so we can import ingest.*
_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

# ---------------------------------------------------------------------------
# Job tracking (in-memory; fine for a prototype)
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED    = "queued"
    RUNNING   = "running"
    DONE      = "done"
    FAILED    = "failed"


@dataclass
class IngestionJob:
    job_id:   str
    filename: str
    doc_id:   Optional[str]
    status:   JobStatus = JobStatus.QUEUED
    progress: str = "Waiting…"
    chunks:   int = 0
    pages:    int = 0
    extractor: str = ""
    error:    str = ""
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None


# Global job store: job_id → IngestionJob
_jobs: Dict[str, IngestionJob] = {}
_jobs_lock = threading.Lock()

# ---------------------------------------------------------------------------
# App setup
# ---------------------------------------------------------------------------

UPLOAD_DIR = Path(__file__).parent / "uploads"
UPLOAD_DIR.mkdir(exist_ok=True)

app = FastAPI(
    title="Indux 5.0 — Admin App",
    description="PDF ingestion dashboard for factory manual management.",
    version="1.0.0",
)

# ---------------------------------------------------------------------------
# Background ingestion worker
# ---------------------------------------------------------------------------

def _run_ingestion(job_id: str, pdf_path: Path, doc_id: Optional[str]) -> None:
    """Run the full ingestion pipeline in a background thread."""
    with _jobs_lock:
        job = _jobs[job_id]
        job.status = JobStatus.RUNNING
        job.progress = "Extracting text…"

    try:
        from ingest.pdf_ingestor import ingest_pdf, IngestError

        # Step 1: Extract + chunk
        _update_job(job_id, progress="Step 1/3 — Extracting text…")
        try:
            result = ingest_pdf(pdf_path, doc_id=doc_id)
        except IngestError as exc:
            _fail_job(job_id, f"Extraction failed: {exc}")
            return

        if result.scanned_warning:
            _fail_job(job_id, "No text extracted — PDF appears to be scanned/image-only.")
            return

        _update_job(
            job_id,
            progress=f"Step 2/3 — Embedding {len(result.chunks)} chunks…",
            chunks=len(result.chunks),
            pages=result.total_pages,
            extractor=result.extractor_used,
        )

        # Step 2: Embed
        from ingest.embedder import embed_chunks, EmbeddingError
        try:
            embeddings = embed_chunks(result.chunks)
        except EmbeddingError as exc:
            _fail_job(job_id, f"Embedding failed: {exc}")
            return

        # Step 3: Save
        _update_job(job_id, progress="Step 3/3 — Saving to database…")
        from ingest.storage import save_chunks, StorageError
        try:
            n = save_chunks(result.chunks, embeddings)
        except StorageError as exc:
            _fail_job(job_id, f"Database error: {exc}")
            return

        _update_job(
            job_id,
            status=JobStatus.DONE,
            progress=f"Done — {n} chunks saved.",
            finished_at=time.time(),
        )

    except Exception as exc:  # noqa: BLE001
        _fail_job(job_id, f"Unexpected error: {exc}")
    finally:
        # Clean up uploaded file
        try:
            pdf_path.unlink(missing_ok=True)
        except Exception:
            pass


def _update_job(job_id: str, **kwargs) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job is None:
            return   # Job was cleared (e.g. during testing); silently ignore.
        for k, v in kwargs.items():
            setattr(job, k, v)


def _fail_job(job_id: str, error: str) -> None:
    _update_job(
        job_id,
        status=JobStatus.FAILED,
        progress="Failed.",
        error=error,
        finished_at=time.time(),
    )


# ---------------------------------------------------------------------------
# API routes
# ---------------------------------------------------------------------------

@app.get("/", response_class=HTMLResponse)
async def dashboard():
    """Render the admin dashboard HTML page."""
    with _jobs_lock:
        jobs_snapshot = list(_jobs.values())

    # Sort newest first
    jobs_snapshot.sort(key=lambda j: j.started_at, reverse=True)

    rows = ""
    for job in jobs_snapshot:
        status_color = {
            JobStatus.QUEUED:  "#888",
            JobStatus.RUNNING: "#1a73e8",
            JobStatus.DONE:    "#188038",
            JobStatus.FAILED:  "#c5221f",
        }.get(job.status, "#888")

        elapsed = ""
        if job.finished_at:
            elapsed = f"{job.finished_at - job.started_at:.1f}s"
        elif job.status == JobStatus.RUNNING:
            elapsed = f"{time.time() - job.started_at:.1f}s…"

        error_html = f'<span style="color:#c5221f;font-size:12px;">{job.error}</span>' if job.error else ""
        rows += f"""
        <tr>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;font-family:monospace;font-size:12px;">{job.job_id[:8]}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{job.filename}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;color:{status_color};font-weight:600;">{job.status.value}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{job.progress}{error_html}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{job.chunks}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{job.pages}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;">{job.extractor}</td>
          <td style="padding:8px 12px;border-bottom:1px solid #e5e7eb;text-align:right;">{elapsed}</td>
        </tr>"""

    if not rows:
        rows = '<tr><td colspan="8" style="padding:24px;text-align:center;color:#57606a;">No jobs yet. Upload a PDF to get started.</td></tr>'

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Indux 5.0 — Admin</title>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; }}
    body {{
      margin: 0; padding: 0;
      font-family: -apple-system, "Segoe UI", system-ui, sans-serif;
      font-size: 14px; line-height: 1.6;
      background: #f7f8fa; color: #1f2328;
    }}
    header {{
      background: #ffffff; border-bottom: 1px solid #e5e7eb;
      padding: 14px 32px; display: flex; align-items: center; gap: 16px;
    }}
    header h1 {{ margin: 0; font-size: 18px; font-weight: 700; color: #1f2328; }}
    header span {{ font-size: 12px; color: #57606a; }}
    .container {{ max-width: 1100px; margin: 32px auto; padding: 0 24px; }}
    .card {{
      background: #ffffff; border: 1px solid #e5e7eb;
      border-radius: 8px; padding: 24px; margin-bottom: 24px;
    }}
    h2 {{ margin: 0 0 16px; font-size: 15px; font-weight: 600; color: #1f2328; }}
    .upload-form {{ display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }}
    .form-group {{ display: flex; flex-direction: column; gap: 4px; }}
    label {{ font-size: 12px; font-weight: 600; color: #57606a; }}
    input[type=file], input[type=text] {{
      border: 1px solid #e5e7eb; border-radius: 4px;
      padding: 6px 10px; font-size: 14px; background: #fff;
    }}
    input[type=text] {{ width: 240px; }}
    button[type=submit] {{
      background: #3b82d4; color: #fff; border: none;
      border-radius: 4px; padding: 8px 20px; font-size: 14px;
      font-weight: 600; cursor: pointer;
    }}
    button[type=submit]:hover {{ background: #2563b0; }}
    table {{ width: 100%; border-collapse: collapse; }}
    th {{
      text-align: left; padding: 8px 12px;
      font-size: 12px; font-weight: 600; color: #57606a;
      border-bottom: 2px solid #e5e7eb;
    }}
    #refresh-btn {{
      background: none; border: 1px solid #e5e7eb;
      border-radius: 4px; padding: 4px 12px; font-size: 13px;
      cursor: pointer; color: #57606a; float: right;
    }}
    #refresh-btn:hover {{ background: #f7f8fa; }}
    .status-note {{ font-size: 12px; color: #57606a; margin-top: 8px; }}
  </style>
</head>
<body>
  <header>
    <h1>Indux 5.0 — Admin</h1>
    <span>PDF Manual Ingestion Dashboard</span>
  </header>
  <div class="container">

    <!-- Upload card -->
    <div class="card">
      <h2>Upload PDF Manual</h2>
      <form class="upload-form" method="post" action="/upload" enctype="multipart/form-data">
        <div class="form-group">
          <label for="pdf_file">PDF file</label>
          <input type="file" id="pdf_file" name="pdf_file" accept=".pdf" required>
        </div>
        <div class="form-group">
          <label for="doc_id">Document ID (optional)</label>
          <input type="text" id="doc_id" name="doc_id" placeholder="e.g. boiler_manual_v3">
        </div>
        <button type="submit">Upload &amp; Ingest</button>
      </form>
      <p class="status-note">
        File is validated, chunked, embedded, and stored automatically.
        Refresh the page to see progress updates.
      </p>
    </div>

    <!-- Jobs table card -->
    <div class="card">
      <h2>Ingestion Jobs <button id="refresh-btn" onclick="location.reload()">↻ Refresh</button></h2>
      <table>
        <thead>
          <tr>
            <th>Job ID</th>
            <th>File</th>
            <th>Status</th>
            <th>Progress</th>
            <th style="text-align:right">Chunks</th>
            <th style="text-align:right">Pages</th>
            <th>Extractor</th>
            <th style="text-align:right">Time</th>
          </tr>
        </thead>
        <tbody>
          {rows}
        </tbody>
      </table>
    </div>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html)


@app.post("/upload")
async def upload_pdf(
    pdf_file: UploadFile = File(...),
    doc_id: Optional[str] = Form(default=None),
):
    """
    Accept a PDF upload, validate it, and start a background ingestion job.
    Returns JSON with the job_id, or redirects to the dashboard on success.
    """
    # Validate file extension
    if not pdf_file.filename or not pdf_file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only .pdf files are accepted.")

    # Read the file
    contents = await pdf_file.read()

    if len(contents) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes).")

    if not contents.startswith(b"%PDF-"):
        raise HTTPException(
            status_code=400,
            detail="File does not appear to be a valid PDF (missing %PDF- header).",
        )

    # Save to uploads dir with a unique name
    job_id = str(uuid.uuid4())
    safe_name = f"{job_id}_{pdf_file.filename}"
    upload_path = UPLOAD_DIR / safe_name
    upload_path.write_bytes(contents)

    # Create job record
    job = IngestionJob(
        job_id=job_id,
        filename=pdf_file.filename,
        doc_id=doc_id or None,
    )
    with _jobs_lock:
        _jobs[job_id] = job

    # Launch background thread
    t = threading.Thread(
        target=_run_ingestion,
        args=(job_id, upload_path, doc_id or None),
        daemon=True,
    )
    t.start()

    # Redirect to dashboard (browser form submit)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url="/", status_code=303)


@app.get("/jobs", response_class=JSONResponse)
async def list_jobs():
    """Return all ingestion jobs as JSON (for polling)."""
    with _jobs_lock:
        return [
            {
                "job_id":    j.job_id,
                "filename":  j.filename,
                "doc_id":    j.doc_id,
                "status":    j.status.value,
                "progress":  j.progress,
                "chunks":    j.chunks,
                "pages":     j.pages,
                "extractor": j.extractor,
                "error":     j.error,
            }
            for j in _jobs.values()
        ]


@app.get("/jobs/{job_id}", response_class=JSONResponse)
async def get_job(job_id: str):
    """Return a single ingestion job by ID."""
    with _jobs_lock:
        job = _jobs.get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail=f"Job '{job_id}' not found.")
    return {
        "job_id":    job.job_id,
        "filename":  job.filename,
        "doc_id":    job.doc_id,
        "status":    job.status.value,
        "progress":  job.progress,
        "chunks":    job.chunks,
        "pages":     job.pages,
        "extractor": job.extractor,
        "error":     job.error,
    }


@app.get("/health")
async def health():
    """Liveness check."""
    return {"status": "ok", "version": "1.0.0"}
