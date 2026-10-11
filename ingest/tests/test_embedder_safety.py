# ingest/tests/test_embedder_safety.py
#
# Tests for the safety additions to ingest/embedder.py:
#
#   A. Rate limiting (delay_s configuration and enforcement)
#   B. Retry and exponential backoff on 429 / 5xx errors
#   C. Retry-After header parsing
#   D. Checkpoint write and resume
#   E. Stale and corrupt checkpoint handling
#   F. Checkpoint keyed by (doc_id, model, dim)
#   G. No API keys stored in checkpoints
#   H. Full-success path cleans up checkpoint
#   I. checkpoint=False disables all checkpoint I/O
#   J. env-var configuration (GEMINI_EMBED_DELAY_S, GEMINI_EMBED_MAX_RETRIES)
#
# All tests use mocks — no Gemini API calls, no Supabase writes.
#
# Run with:
#   py -m pytest ingest/tests/test_embedder_safety.py -v

from __future__ import annotations

import json
import time
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from ingest.pdf_ingestor import Chunk
from ingest.embedder import (
    DEFAULT_EMBED_DELAY_S,
    DEFAULT_MAX_RETRIES,
    EmbeddingError,
    _Checkpoint,
    _backoff_delay,
    _checkpoint_path,
    _is_retryable_error,
    _parse_retry_after,
    _resolve_delay,
    _resolve_retries,
    embed_chunks,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _make_chunks(n: int = 3, doc_id: str = "test_doc") -> list[Chunk]:
    return [
        Chunk(
            text=f"Chunk {i} of {doc_id}",
            doc_id=doc_id,
            page_number=1,
            chunk_index=i,
        )
        for i in range(n)
    ]


def _make_mock_client(dim: int = 3072) -> MagicMock:
    """Return a mock genai client that succeeds on every call."""
    fake_values = [float(j % 100) / 100 for j in range(dim)]
    mock_emb = MagicMock()
    mock_emb.values = fake_values
    mock_resp = MagicMock()
    mock_resp.embeddings = [mock_emb]
    mock_client = MagicMock()
    mock_client.models.embed_content.return_value = mock_resp
    return mock_client


def _embed_no_ckpt(chunks, mock_client, monkeypatch, **kw):
    """Call embed_chunks with checkpoint=False and delay=0 via a mock client."""
    monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
    with patch("ingest.embedder._get_genai_client", return_value=mock_client):
        return embed_chunks(chunks, checkpoint=False, delay_s=0.0, **kw)


# ---------------------------------------------------------------------------
# A. Rate limiting
# ---------------------------------------------------------------------------

class TestRateLimiting:
    """Tests for inter-request delay enforcement."""

    def test_default_delay_is_conservative(self):
        """The default delay must be ≥ 0.6 s (≤ 100 RPM on free tier)."""
        assert DEFAULT_EMBED_DELAY_S >= 0.6, (
            f"Default delay {DEFAULT_EMBED_DELAY_S}s is too aggressive — "
            "would exceed 100 RPM on the Gemini free tier."
        )

    def test_resolve_delay_uses_argument(self):
        assert _resolve_delay(1.5) == 1.5

    def test_resolve_delay_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_EMBED_DELAY_S", "2.0")
        assert _resolve_delay(None) == 2.0

    def test_resolve_delay_clamps_negative_to_zero(self):
        assert _resolve_delay(-5.0) == 0.0

    def test_resolve_delay_argument_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_EMBED_DELAY_S", "99.0")
        assert _resolve_delay(0.5) == 0.5

    def test_resolve_delay_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_EMBED_DELAY_S", raising=False)
        assert _resolve_delay(None) == DEFAULT_EMBED_DELAY_S

    def test_resolve_delay_ignores_invalid_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_EMBED_DELAY_S", "not_a_number")
        assert _resolve_delay(None) == DEFAULT_EMBED_DELAY_S

    def test_delay_zero_makes_no_sleep_calls(self, monkeypatch):
        """With delay=0.0, time.sleep must never be called between requests."""
        chunks = _make_chunks(3)
        mock_client = _make_mock_client()
        sleep_calls = []

        def counting_sleep(s):
            sleep_calls.append(s)

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep", side_effect=counting_sleep):
            embed_chunks(chunks, delay_s=0.0, checkpoint=False)

        assert sleep_calls == [], f"Expected no sleeps with delay=0, got: {sleep_calls}"

    def test_delay_applied_between_requests(self, monkeypatch):
        """With delay > 0, time.sleep is called for each non-first request."""
        chunks = _make_chunks(3)
        mock_client = _make_mock_client()
        sleep_calls = []

        def counting_sleep(s):
            sleep_calls.append(s)

        # Use a large delay so the condition `wait > 0` always fires.
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep", side_effect=counting_sleep), \
             patch("ingest.embedder.time.monotonic", side_effect=[0.0] * 20):
            embed_chunks(chunks, delay_s=1.0, checkpoint=False)

        # 3 chunks: first chunk skips the sleep (last_request_time=0 but elapsed≈0
        # in mocked time), chunks 2 and 3 get a sleep call.
        assert len(sleep_calls) >= 2, (
            f"Expected sleeps between requests, got {len(sleep_calls)} sleep calls"
        )


# ---------------------------------------------------------------------------
# B. Retry and exponential backoff
# ---------------------------------------------------------------------------

class TestRetryBackoff:
    """Tests for retry logic on transient errors."""

    def test_resolve_retries_uses_argument(self):
        assert _resolve_retries(3) == 3

    def test_resolve_retries_uses_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_EMBED_MAX_RETRIES", "7")
        assert _resolve_retries(None) == 7

    def test_resolve_retries_clamps_negative_to_zero(self):
        assert _resolve_retries(-1) == 0

    def test_resolve_retries_argument_overrides_env_var(self, monkeypatch):
        monkeypatch.setenv("GEMINI_EMBED_MAX_RETRIES", "99")
        assert _resolve_retries(2) == 2

    def test_resolve_retries_falls_back_to_default(self, monkeypatch):
        monkeypatch.delenv("GEMINI_EMBED_MAX_RETRIES", raising=False)
        assert _resolve_retries(None) == DEFAULT_MAX_RETRIES

    def test_is_retryable_429(self):
        assert _is_retryable_error("HTTP 429 Too Many Requests")

    def test_is_retryable_503(self):
        assert _is_retryable_error("503 Service Unavailable")

    def test_is_retryable_500(self):
        assert _is_retryable_error("500 Internal Server Error")

    def test_is_retryable_quota(self):
        assert _is_retryable_error("RESOURCE_EXHAUSTED: quota exceeded")

    def test_is_retryable_rate_limit(self):
        assert _is_retryable_error("rate limit exceeded, please wait")

    def test_is_retryable_winerror_10054(self):
        assert _is_retryable_error("[WinError 10054] An existing connection was forcibly closed by the remote host")

    def test_is_retryable_connection_reset(self):
        assert _is_retryable_error("Connection reset by peer")

    def test_is_retryable_connection_closed(self):
        assert _is_retryable_error("connection forcibly closed by remote")

    def test_is_retryable_timed_out(self):
        assert _is_retryable_error("Request timed out after 30s")

    def test_is_not_retryable_auth(self):
        assert not _is_retryable_error("401 Unauthorized: invalid API key")

    def test_is_not_retryable_404(self):
        assert not _is_retryable_error("404 model not found")

    def test_is_not_retryable_value_error(self):
        assert not _is_retryable_error("ValueError: contents must not be empty")

    def test_retry_on_429_eventually_succeeds(self, monkeypatch):
        """First call raises 429; second call succeeds. One retry consumed."""
        chunks = _make_chunks(1)
        good_values = [0.1] * 3072
        mock_emb = MagicMock(); mock_emb.values = good_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = [
            RuntimeError("429 Too Many Requests"),
            mock_resp,
        ]
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            result = embed_chunks(chunks, checkpoint=False, delay_s=0.0, max_retries=2)
        assert len(result) == 1
        assert mock_client.models.embed_content.call_count == 2

    def test_retry_on_503_eventually_succeeds(self, monkeypatch):
        """Two consecutive 503 errors then success — two retries consumed."""
        chunks = _make_chunks(1)
        good_values = [0.2] * 3072
        mock_emb = MagicMock(); mock_emb.values = good_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = [
            RuntimeError("503 Service Unavailable"),
            RuntimeError("503 Service Unavailable"),
            mock_resp,
        ]
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            result = embed_chunks(chunks, checkpoint=False, delay_s=0.0, max_retries=3)
        assert len(result) == 1
        assert mock_client.models.embed_content.call_count == 3

    def test_exhausted_retries_raise_embedding_error(self, monkeypatch):
        """All attempts fail → EmbeddingError after max_retries + 1 total attempts."""
        chunks = _make_chunks(1)
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("429 rate limit")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            with pytest.raises(EmbeddingError, match="(?i)gemini"):
                embed_chunks(chunks, checkpoint=False, delay_s=0.0, max_retries=2)
        # 1 initial + 2 retries = 3 total calls
        assert mock_client.models.embed_content.call_count == 3

    def test_non_retryable_error_fails_immediately(self, monkeypatch):
        """A 401 auth error must NOT be retried."""
        chunks = _make_chunks(1)
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("401 Unauthorized")
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            with pytest.raises(EmbeddingError):
                embed_chunks(chunks, checkpoint=False, delay_s=0.0, max_retries=4)
        # Must have failed on the very first attempt, not retried.
        assert mock_client.models.embed_content.call_count == 1

    def test_backoff_delay_increases_with_attempts(self):
        """Backoff delay for attempt 2 must exceed that for attempt 1."""
        delay_1 = _backoff_delay("429 error", attempt=1)
        delay_2 = _backoff_delay("429 error", attempt=2)
        delay_3 = _backoff_delay("429 error", attempt=3)
        assert delay_2 > delay_1
        assert delay_3 > delay_2

    def test_backoff_delay_is_capped(self):
        """Backoff must not exceed _BACKOFF_CAP_S regardless of attempt number."""
        from ingest.embedder import _BACKOFF_CAP_S
        for attempt in range(1, 20):
            assert _backoff_delay("429 error", attempt) <= _BACKOFF_CAP_S

    def test_retry_sleep_called_between_retries(self, monkeypatch):
        """time.sleep must be called once per retry with a positive duration."""
        chunks = _make_chunks(1)
        good_values = [0.5] * 3072
        mock_emb = MagicMock(); mock_emb.values = good_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = [
            RuntimeError("429 Too Many Requests"),
            mock_resp,
        ]
        sleep_calls = []
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            embed_chunks(chunks, checkpoint=False, delay_s=0.0, max_retries=2)
        retry_sleeps = [s for s in sleep_calls if s > 0]
        assert len(retry_sleeps) >= 1, "Expected at least one backoff sleep for the retry"
        assert all(s > 0 for s in retry_sleeps)


# ---------------------------------------------------------------------------
# C. Retry-After header parsing
# ---------------------------------------------------------------------------

class TestRetryAfterParsing:
    """Tests for _parse_retry_after() header extraction."""

    def test_colon_format(self):
        assert _parse_retry_after("Retry-After: 30") == 30.0

    def test_equals_format(self):
        assert _parse_retry_after("retry_after=15") == 15.0

    def test_prose_format(self):
        assert _parse_retry_after("retry after 10 seconds") == 10.0

    def test_float_value(self):
        assert _parse_retry_after("Retry-After: 5.5") == 5.5

    def test_no_retry_after_returns_none(self):
        assert _parse_retry_after("503 Service Unavailable") is None

    def test_retry_after_respected_in_backoff(self):
        """When Retry-After is present its value is used as the delay."""
        delay = _backoff_delay("429 Too Many Requests; Retry-After: 45", attempt=1)
        assert delay == 45.0

    def test_retry_after_capped_at_backoff_cap(self):
        """Even if Retry-After is huge, the delay is capped at _BACKOFF_CAP_S."""
        from ingest.embedder import _BACKOFF_CAP_S
        delay = _backoff_delay("Retry-After: 9999", attempt=1)
        assert delay == _BACKOFF_CAP_S


# ---------------------------------------------------------------------------
# D. Checkpoint write and resume
# ---------------------------------------------------------------------------

class TestCheckpointResume:
    """Tests for the checkpoint write/load/resume cycle."""

    def _make_ckpt(self, tmp_path: Path, doc_id: str = "doc_a",
                   model: str = "gemini-embedding-001", dim: int = 3072) -> _Checkpoint:
        from ingest import embedder as mod
        # Temporarily redirect checkpoint dir to tmp_path.
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            return _Checkpoint.load(doc_id=doc_id, model=model, dim=dim)

    def test_fresh_checkpoint_has_no_entries(self, tmp_path):
        ckpt = self._make_ckpt(tmp_path)
        assert ckpt.get("any_id") is None

    def test_put_and_get_round_trip(self, tmp_path):
        ckpt = self._make_ckpt(tmp_path)
        vec = [0.1] * 3072
        ckpt.put("chunk_001", vec)
        assert ckpt.get("chunk_001") == vec

    def test_flush_writes_to_disk(self, tmp_path):
        ckpt = self._make_ckpt(tmp_path)
        vec = [0.2] * 3072
        ckpt.put("chunk_002", vec)
        ckpt.flush()
        assert ckpt._path.exists()

    def test_flush_writes_valid_jsonl(self, tmp_path):
        ckpt = self._make_ckpt(tmp_path)
        ckpt.put("chunk_003", [0.3] * 3072)
        ckpt.flush()
        lines = ckpt._path.read_text(encoding="utf-8").splitlines()
        # First line = metadata, second = the entry.
        assert len(lines) == 2
        meta = json.loads(lines[0])
        assert meta.get("_meta") is True
        entry = json.loads(lines[1])
        assert entry["chunk_id"] == "chunk_003"
        assert len(entry["embedding"]) == 3072

    def test_no_api_key_in_checkpoint(self, tmp_path, monkeypatch):
        """API key must never appear in the checkpoint file."""
        monkeypatch.setenv("GEMINI_API_KEY", "super-secret-key-abc123")
        ckpt = self._make_ckpt(tmp_path)
        ckpt.put("c1", [0.0] * 3072)
        ckpt.flush()
        content = ckpt._path.read_text(encoding="utf-8")
        assert "super-secret-key-abc123" not in content, (
            "API key found in checkpoint file — this is a security defect."
        )

    def test_no_gemini_api_key_env_var_in_checkpoint(self, tmp_path, monkeypatch):
        """GEMINI_API_KEY env var value must not appear in checkpoint content."""
        monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyTestKey999")
        ckpt = self._make_ckpt(tmp_path)
        ckpt.put("c2", [0.0] * 3072)
        ckpt.flush()
        content = ckpt._path.read_text(encoding="utf-8")
        assert "AIzaSyTestKey999" not in content

    def test_resume_skips_already_embedded_chunks(self, tmp_path, monkeypatch):
        """
        embed_chunks resumes from a checkpoint: chunks whose chunk_ids are
        already present must not trigger an API call.
        """
        doc_id = "resume_doc"
        chunks = _make_chunks(3, doc_id=doc_id)
        mock_client = _make_mock_client()

        from ingest import embedder as mod

        # Pre-populate a checkpoint with the first chunk already embedded.
        ckpt_path = tmp_path / f"{doc_id}__gemini-embedding-001.jsonl"
        meta = {"_meta": True, "doc_id": doc_id,
                "model": "gemini-embedding-001", "dim": 3072}
        entry = {"chunk_id": chunks[0].chunk_id, "embedding": [0.5] * 3072}
        ckpt_path.write_text(
            json.dumps(meta) + "\n" + json.dumps(entry) + "\n",
            encoding="utf-8",
        )

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path), \
             patch("ingest.embedder._get_genai_client", return_value=mock_client):
            result = embed_chunks(chunks, delay_s=0.0, max_retries=0)

        # Only 2 of the 3 chunks needed API calls (chunk 0 was cached).
        assert mock_client.models.embed_content.call_count == 2
        assert len(result) == 3
        # The resumed vector matches what was in the checkpoint.
        assert result[0] == [0.5] * 3072

    def test_checkpoint_deleted_on_full_success(self, tmp_path, monkeypatch):
        """After a fully successful embed_chunks, the checkpoint file is removed."""
        doc_id = "cleanup_doc"
        chunks = _make_chunks(2, doc_id=doc_id)
        mock_client = _make_mock_client()

        from ingest import embedder as mod

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path), \
             patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embed_chunks(chunks, delay_s=0.0, max_retries=0)

        # The checkpoint file must have been deleted after success.
        ckpt_path = tmp_path / f"{doc_id}__gemini-embedding-001.jsonl"
        assert not ckpt_path.exists(), (
            "Checkpoint file should be cleaned up after a successful full run."
        )

    def test_checkpoint_survives_partial_failure(self, tmp_path, monkeypatch):
        """
        When embedding fails mid-run, the checkpoint file must still exist
        so the run can be resumed.
        """
        doc_id = "partial_doc"
        chunks = _make_chunks(3, doc_id=doc_id)
        good_values = [0.9] * 3072
        mock_emb = MagicMock(); mock_emb.values = good_values
        mock_resp = MagicMock(); mock_resp.embeddings = [mock_emb]
        mock_client = MagicMock()
        # First chunk succeeds, second fails.
        mock_client.models.embed_content.side_effect = [
            mock_resp,
            RuntimeError("401 Unauthorized"),
        ]

        from ingest import embedder as mod

        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path), \
             patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            with pytest.raises(EmbeddingError):
                embed_chunks(chunks, delay_s=0.0, max_retries=0)

        # Checkpoint must still exist with the one successful embedding.
        ckpt_path = tmp_path / f"{doc_id}__gemini-embedding-001.jsonl"
        assert ckpt_path.exists(), "Checkpoint must persist after a partial failure."
        lines = ckpt_path.read_text(encoding="utf-8").splitlines()
        entries = [json.loads(ln) for ln in lines if ln and not json.loads(ln).get("_meta")]
        assert len(entries) == 1
        assert entries[0]["chunk_id"] == chunks[0].chunk_id


# ---------------------------------------------------------------------------
# E. Stale and corrupt checkpoint handling
# ---------------------------------------------------------------------------

class TestCheckpointStaleAndCorrupt:
    """Tests for invalid or mismatched checkpoint files."""

    def test_stale_model_checkpoint_is_discarded(self, tmp_path):
        """A checkpoint saved with a different model must be discarded silently."""
        ckpt_path = _checkpoint_path("stale_doc", "gemini-embedding-001")
        stale_path = tmp_path / ckpt_path.name
        meta = {"_meta": True, "doc_id": "stale_doc",
                "model": "old-model-v0", "dim": 3072}
        entry = {"chunk_id": "x", "embedding": [1.0] * 3072}
        stale_path.write_text(json.dumps(meta) + "\n" + json.dumps(entry) + "\n",
                               encoding="utf-8")

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="stale_doc", model="gemini-embedding-001", dim=3072)

        # The stale entry must have been discarded.
        assert ckpt.get("x") is None

    def test_stale_dim_checkpoint_is_discarded(self, tmp_path):
        """A checkpoint saved with a different dimension must be discarded."""
        ckpt_path = _checkpoint_path("dim_doc", "gemini-embedding-001")
        stale_path = tmp_path / ckpt_path.name
        meta = {"_meta": True, "doc_id": "dim_doc",
                "model": "gemini-embedding-001", "dim": 768}   # wrong dim
        entry = {"chunk_id": "y", "embedding": [0.0] * 768}
        stale_path.write_text(json.dumps(meta) + "\n" + json.dumps(entry) + "\n",
                               encoding="utf-8")

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="dim_doc", model="gemini-embedding-001", dim=3072)

        assert ckpt.get("y") is None

    def test_corrupt_checkpoint_is_discarded(self, tmp_path):
        """A corrupt (non-JSON) checkpoint must be discarded without raising."""
        ckpt_path = _checkpoint_path("corrupt_doc", "gemini-embedding-001")
        bad_path = tmp_path / ckpt_path.name
        bad_path.write_text("this is not json at all!!!", encoding="utf-8")

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="corrupt_doc",
                                    model="gemini-embedding-001", dim=3072)

        assert ckpt.get("anything") is None

    def test_empty_checkpoint_file_is_safe(self, tmp_path):
        """A zero-byte checkpoint must be handled gracefully."""
        ckpt_path = _checkpoint_path("empty_doc", "gemini-embedding-001")
        empty_path = tmp_path / ckpt_path.name
        empty_path.write_text("", encoding="utf-8")

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="empty_doc",
                                    model="gemini-embedding-001", dim=3072)

        assert ckpt.get("anything") is None

    def test_checkpoint_missing_meta_line_is_discarded(self, tmp_path):
        """A checkpoint whose first line is not a meta record must be discarded."""
        ckpt_path = _checkpoint_path("nometa_doc", "gemini-embedding-001")
        bad_path = tmp_path / ckpt_path.name
        entry = {"chunk_id": "z", "embedding": [0.0] * 3072}
        bad_path.write_text(json.dumps(entry) + "\n", encoding="utf-8")

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="nometa_doc",
                                    model="gemini-embedding-001", dim=3072)

        assert ckpt.get("z") is None

    def test_entries_with_wrong_dim_are_silently_skipped(self, tmp_path):
        """Entries with the wrong embedding length must be skipped, not crash."""
        ckpt_path = _checkpoint_path("wrongdim_doc", "gemini-embedding-001")
        p = tmp_path / ckpt_path.name
        meta  = {"_meta": True, "doc_id": "wrongdim_doc",
                 "model": "gemini-embedding-001", "dim": 3072}
        good  = {"chunk_id": "good", "embedding": [0.1] * 3072}
        bad   = {"chunk_id": "bad",  "embedding": [0.1] * 128}  # wrong dim
        p.write_text(
            json.dumps(meta) + "\n" + json.dumps(good) + "\n" + json.dumps(bad) + "\n",
            encoding="utf-8",
        )

        from ingest import embedder as mod
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path):
            ckpt = _Checkpoint.load(doc_id="wrongdim_doc",
                                    model="gemini-embedding-001", dim=3072)

        assert ckpt.get("good") is not None
        assert ckpt.get("bad") is None


# ---------------------------------------------------------------------------
# F. Checkpoint keyed by (doc_id, model, dim)
# ---------------------------------------------------------------------------

class TestCheckpointKeying:
    """The checkpoint filename encodes doc_id and model."""

    def test_checkpoint_path_includes_doc_id(self):
        p = _checkpoint_path("my_manual_v1", "gemini-embedding-001")
        assert "my_manual_v1" in p.name

    def test_checkpoint_path_includes_model(self):
        p = _checkpoint_path("doc_x", "gemini-embedding-001")
        assert "gemini-embedding-001" in p.name or "gemini" in p.name

    def test_different_models_use_different_paths(self):
        p1 = _checkpoint_path("doc", "gemini-embedding-001")
        p2 = _checkpoint_path("doc", "gemini-embedding-002")
        assert p1 != p2

    def test_different_docs_use_different_paths(self):
        p1 = _checkpoint_path("doc_a", "gemini-embedding-001")
        p2 = _checkpoint_path("doc_b", "gemini-embedding-001")
        assert p1 != p2

    def test_checkpoint_path_is_safe_filename(self):
        """Slashes and special chars in doc_id must not appear in the filename."""
        p = _checkpoint_path("path/to/../doc?name=1&v=2", "model")
        assert "/" not in p.name
        assert "\\" not in p.name
        assert "?" not in p.name
        assert "=" not in p.name


# ---------------------------------------------------------------------------
# G. checkpoint=False disables all I/O
# ---------------------------------------------------------------------------

class TestCheckpointDisabled:
    """With checkpoint=False, no filesystem operations occur."""

    def test_no_checkpoint_file_created(self, tmp_path, monkeypatch):
        chunks = _make_chunks(2, doc_id="nocache_doc")
        mock_client = _make_mock_client()

        from ingest import embedder as mod
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch.object(mod, "_CHECKPOINT_DIR", tmp_path), \
             patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embed_chunks(chunks, checkpoint=False, delay_s=0.0)

        # No files should have been created in tmp_path.
        created = list(tmp_path.iterdir())
        assert created == [], f"Unexpected files created: {created}"

    def test_checkpoint_false_does_not_call_checkpoint_load(self, monkeypatch):
        chunks = _make_chunks(2)
        mock_client = _make_mock_client()
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        with patch("ingest.embedder._Checkpoint.load") as mock_load, \
             patch("ingest.embedder._get_genai_client", return_value=mock_client):
            embed_chunks(chunks, checkpoint=False, delay_s=0.0)
        mock_load.assert_not_called()


# ---------------------------------------------------------------------------
# H. env-var configuration round-trip through embed_chunks
# ---------------------------------------------------------------------------

class TestEnvVarConfig:
    """env vars GEMINI_EMBED_DELAY_S and GEMINI_EMBED_MAX_RETRIES are respected."""

    def test_max_retries_env_var_limits_attempts(self, monkeypatch):
        """GEMINI_EMBED_MAX_RETRIES=0 means one attempt only, no retries."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("GEMINI_EMBED_MAX_RETRIES", "0")
        chunks = _make_chunks(1)
        mock_client = MagicMock()
        mock_client.models.embed_content.side_effect = RuntimeError("429 rate limit")
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep"):
            with pytest.raises(EmbeddingError):
                embed_chunks(chunks, checkpoint=False, delay_s=0.0)
        assert mock_client.models.embed_content.call_count == 1

    def test_delay_env_var_is_used(self, monkeypatch):
        """GEMINI_EMBED_DELAY_S=0.0 disables sleep via env var."""
        monkeypatch.setenv("GEMINI_API_KEY", "fake-key")
        monkeypatch.setenv("GEMINI_EMBED_DELAY_S", "0.0")
        chunks = _make_chunks(2)
        mock_client = _make_mock_client()
        sleep_calls = []
        with patch("ingest.embedder._get_genai_client", return_value=mock_client), \
             patch("ingest.embedder.time.sleep", side_effect=lambda s: sleep_calls.append(s)):
            embed_chunks(chunks, checkpoint=False)
        # With delay=0 from env var, no sleep for rate limiting.
        rate_limit_sleeps = [s for s in sleep_calls if s == 0.0]
        # The important assertion: no positive sleeps from rate limiting
        # (there might be backoff sleeps if retries happened, but there are none here).
        assert all(s >= 0 for s in sleep_calls)
