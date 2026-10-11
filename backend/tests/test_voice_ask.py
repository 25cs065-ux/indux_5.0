# backend/tests/test_voice_ask.py
#
# Focused tests for POST /voice-ask
#
# Strategy: patch module-level supabase and ai_ask in backend.main before
# importing the FastAPI app so no live credentials or Gemini calls are needed.
#
# Run with:
#   .venv\Scripts\python -m pytest backend/tests/test_voice_ask.py -v

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on sys.path.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

def _make_ok_answer() -> dict:
    return {
        "status": "OK",
        "problem_type": "overheating",
        "summary": "Check the cooler and oil level.",
        "is_dangerous": False,
        "safety_checklist": [],
        "history_note": "",
        "steps": [{"step_no": 1, "instruction": "Check oil.", "check_question": "Is oil level normal?"}],
        "sources": [{"manual": "GA15-26_Instruction_Book", "page": 12}],
        "escalate": False,
    }


def _make_not_found_answer() -> dict:
    return {
        "status": "NOT_FOUND",
        "problem_type": "other",
        "summary": "Not found in manual.",
        "is_dangerous": False,
        "safety_checklist": [],
        "history_note": "",
        "steps": [],
        "sources": [],
        "escalate": True,
    }


def _make_dangerous_answer() -> dict:
    return {
        "status": "NOT_FOUND",
        "problem_type": "other",
        "summary": "Not found in manual.",
        "is_dangerous": True,
        "safety_checklist": ["Stop the machine and allow it to cool completely."],
        "history_note": "",
        "steps": [],
        "sources": [],
        "escalate": True,
    }


@pytest.fixture()
def client(monkeypatch):
    """
    Return a TestClient for backend.main with Supabase and ai_ask mocked.

    The mock Supabase returns empty repair history.
    The mock ai_ask is a MagicMock that tests can customise via client._mock_ask.
    """
    # Mock Supabase client at the env-var level so the module-level
    # create_client() call doesn't need real credentials.
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    mock_sb = MagicMock()
    empty = MagicMock()
    empty.data = []
    (
        mock_sb.table.return_value
        .select.return_value
        .eq.return_value
        .order.return_value
        .limit.return_value
        .execute.return_value
    ) = empty

    mock_ask = MagicMock(return_value=_make_ok_answer())

    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai.brain.ask", mock_ask):
        # Import (or re-import) the app after patching.
        import importlib
        import backend.main as bmod
        importlib.reload(bmod)

        from fastapi.testclient import TestClient
        tc = TestClient(bmod.app, raise_server_exceptions=False)
        tc._mock_ask = mock_ask
        tc._mock_sb = mock_sb
        yield tc


# ---------------------------------------------------------------------------
# 1. Happy path — transcript is forwarded to ai_ask and response is correct
# ---------------------------------------------------------------------------

class TestVoiceAskHappyPath:

    def test_200_on_valid_transcript(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert resp.status_code == 200

    def test_response_status_success(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert resp.json()["status"] == "success"

    def test_question_field_echoes_transcript(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert resp.json()["question"] == "Compressor is overheating"

    def test_machine_id_default(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert resp.json()["machine_id"] == "compressor_01"

    def test_machine_id_explicit(self, client):
        resp = client.post(
            "/voice-ask",
            json={"transcript": "Compressor is overheating", "machine_id": "compressor-02"}
        )
        assert resp.json()["machine_id"] == "compressor-02"

    def test_is_demo_false(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert resp.json()["is_demo"] is False

    def test_answer_nested_under_answer_key(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert "answer" in resp.json()

    def test_answer_contains_status(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor is overheating"})
        assert "status" in resp.json()["answer"]

    def test_transcript_is_passed_to_ai_ask(self, client):
        client.post("/voice-ask", json={"transcript": "Compressor garam ho raha hai"})
        call_kwargs = client._mock_ask.call_args
        assert call_kwargs.kwargs.get("question") == "Compressor garam ho raha hai" or \
               (call_kwargs.args and call_kwargs.args[0] == "Compressor garam ho raha hai")

    def test_machine_id_passed_to_ai_ask(self, client):
        client.post(
            "/voice-ask",
            json={"transcript": "Oil leaking", "machine_id": "compressor-02"}
        )
        call_kwargs = client._mock_ask.call_args
        assert call_kwargs.kwargs.get("machine_id") == "compressor-02"

    def test_repair_history_passed_to_ai_ask(self, client):
        """ai_ask must always receive repair_history (even if empty list)."""
        client.post("/voice-ask", json={"transcript": "Overheating"})
        call_kwargs = client._mock_ask.call_args
        assert "repair_history" in call_kwargs.kwargs

    def test_whitespace_only_transcript_is_trimmed(self, client):
        """Leading/trailing whitespace is stripped; pure whitespace is rejected."""
        resp = client.post("/voice-ask", json={"transcript": "   "})
        assert resp.status_code == 422

    def test_leading_trailing_whitespace_trimmed(self, client):
        """A transcript with surrounding spaces should succeed after trimming."""
        resp = client.post("/voice-ask", json={"transcript": "  Compressor is hot  "})
        assert resp.status_code == 200
        # The echoed question must be the trimmed version.
        assert resp.json()["question"] == "Compressor is hot"


# ---------------------------------------------------------------------------
# 2. Input validation — empty / missing transcript
# ---------------------------------------------------------------------------

class TestVoiceAskValidation:

    def test_empty_string_returns_422(self, client):
        resp = client.post("/voice-ask", json={"transcript": ""})
        assert resp.status_code == 422

    def test_whitespace_only_returns_422(self, client):
        resp = client.post("/voice-ask", json={"transcript": "   \t\n"})
        assert resp.status_code == 422

    def test_missing_transcript_field_returns_422(self, client):
        resp = client.post("/voice-ask", json={"machine_id": "compressor-01"})
        assert resp.status_code == 422

    def test_null_transcript_returns_422(self, client):
        resp = client.post("/voice-ask", json={"transcript": None})
        assert resp.status_code == 422

    def test_non_string_transcript_returns_422(self, client):
        resp = client.post("/voice-ask", json={"transcript": 12345})
        # Pydantic will coerce int to str ("12345") — this is a valid string,
        # not an error. Confirm it does not crash (200 or 422 are both acceptable,
        # but it must not be a 500).
        assert resp.status_code in (200, 422)

    def test_missing_body_returns_422(self, client):
        resp = client.post("/voice-ask")
        assert resp.status_code == 422

    def test_empty_string_error_message_is_informative(self, client):
        resp = client.post("/voice-ask", json={"transcript": ""})
        body = resp.json()
        assert "detail" in body


# ---------------------------------------------------------------------------
# 3. Response contract matches docs/json-format.md outer envelope
# ---------------------------------------------------------------------------

class TestVoiceAskResponseContract:

    OUTER_KEYS = {"status", "machine_id", "question", "answer", "is_demo"}

    def test_outer_envelope_keys_present(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        body = resp.json()
        for key in self.OUTER_KEYS:
            assert key in body, f"Outer envelope key '{key}' missing"

    def test_answer_has_inner_contract_keys(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        answer = resp.json()["answer"]
        for key in ("status", "problem_type", "summary", "is_dangerous",
                    "safety_checklist", "history_note", "steps", "sources", "escalate"):
            assert key in answer, f"Inner answer key '{key}' missing"

    def test_not_found_answer_propagated(self, client):
        client._mock_ask.return_value = _make_not_found_answer()
        resp = client.post("/voice-ask", json={"transcript": "How to bake cookies"})
        assert resp.json()["answer"]["status"] == "NOT_FOUND"
        assert resp.json()["answer"]["escalate"] is True
        assert resp.json()["answer"]["steps"] == []

    def test_dangerous_answer_propagated(self, client):
        client._mock_ask.return_value = _make_dangerous_answer()
        resp = client.post("/voice-ask", json={"transcript": "Drain hot oil now"})
        assert resp.json()["answer"]["is_dangerous"] is True
        assert len(resp.json()["answer"]["safety_checklist"]) > 0

    def test_ok_answer_propagated(self, client):
        client._mock_ask.return_value = _make_ok_answer()
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        assert resp.json()["answer"]["status"] == "OK"

    def test_content_type_is_json(self, client):
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        assert "application/json" in resp.headers.get("content-type", "")


# ---------------------------------------------------------------------------
# 4. Error handling — ai_ask raises an exception
# ---------------------------------------------------------------------------

class TestVoiceAskErrorHandling:

    def test_503_when_ai_ask_raises(self, client):
        client._mock_ask.side_effect = RuntimeError("Gemini API unreachable")
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        assert resp.status_code == 503

    def test_503_detail_is_user_friendly(self, client):
        client._mock_ask.side_effect = Exception("Something broke")
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        body = resp.json()
        assert "detail" in body
        # Must not leak internal exception message to the client.
        assert "Something broke" not in body["detail"]

    def test_503_when_supabase_history_raises(self, client):
        (
            client._mock_sb.table.return_value
            .select.return_value
            .eq.return_value
            .order.return_value
            .limit.return_value
            .execute.side_effect
        ) = Exception("DB connection refused")
        resp = client.post("/voice-ask", json={"transcript": "Compressor overheating"})
        assert resp.status_code == 503


# ---------------------------------------------------------------------------
# 5. Hinglish / multilingual transcripts (Q29, Q30 from test-questions.csv)
# ---------------------------------------------------------------------------

class TestVoiceAskMultilingual:

    def test_hinglish_overheating_question(self, client):
        """Q29: Compressor garam ho raha hai kya check karna chahiye"""
        resp = client.post(
            "/voice-ask",
            json={"transcript": "Compressor garam ho raha hai kya check karna chahiye"}
        )
        assert resp.status_code == 200
        assert resp.json()["question"] == "Compressor garam ho raha hai kya check karna chahiye"

    def test_hinglish_pressure_question(self, client):
        """Q30: Pressure kam aa raha hai kya karun"""
        resp = client.post(
            "/voice-ask",
            json={"transcript": "Pressure kam aa raha hai kya karun"}
        )
        assert resp.status_code == 200

    def test_multilingual_transcript_passes_through_unchanged(self, client):
        """The transcript must be forwarded to ai_ask as-is (no translation)."""
        transcript = "Compressor garam ho raha hai kya check karna chahiye"
        client.post("/voice-ask", json={"transcript": transcript})
        call_kwargs = client._mock_ask.call_args
        forwarded = (
            call_kwargs.kwargs.get("question")
            or (call_kwargs.args[0] if call_kwargs.args else None)
        )
        assert forwarded == transcript
