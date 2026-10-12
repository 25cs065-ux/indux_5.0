# backend/tests/test_checklist_step.py
#
# Tests for POST /checklist/step
#
# Strategy: patch ai.brain.check_step_reply before importing the FastAPI app
# so no live Gemini API calls are made.
#
# Run with:
#   .venv\Scripts\python -m pytest backend/tests/test_checklist_step.py -v

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------

@pytest.fixture()
def client(monkeypatch):
    """
    Return a TestClient for backend.main with Supabase and check_step_reply mocked.
    """
    monkeypatch.setenv("SUPABASE_URL", "https://fake.supabase.co")
    monkeypatch.setenv("SUPABASE_KEY", "fake-key")

    mock_sb = MagicMock()
    mock_check = MagicMock(return_value="yes")

    with patch("supabase.create_client", return_value=mock_sb), \
         patch("ai.brain.check_step_reply", mock_check):
        import importlib
        import backend.main as bmod
        importlib.reload(bmod)

        from fastapi.testclient import TestClient
        tc = TestClient(bmod.app, raise_server_exceptions=False)
        tc._mock_check = mock_check
        yield tc


# ---------------------------------------------------------------------------
# 1. Happy path — valid inputs
# ---------------------------------------------------------------------------

class TestChecklistStepHappyPath:

    def test_200_on_valid_input(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes it looks good", "step_question": "Is the pressure above 80 PSI?"}
        )
        assert resp.status_code == 200

    def test_result_yes(self, client):
        client._mock_check.return_value = "yes"
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yeah looks good", "step_question": "Is the oil level normal?"}
        )
        assert resp.json()["result"] == "yes"

    def test_result_no(self, client):
        client._mock_check.return_value = "no"
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "No it failed", "step_question": "Is the pressure above 80 PSI?"}
        )
        assert resp.json()["result"] == "no"

    def test_result_unclear(self, client):
        client._mock_check.return_value = "unclear"
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "I'm not sure", "step_question": "Is the pressure above 80 PSI?"}
        )
        assert resp.json()["result"] == "unclear"

    def test_response_has_result_key(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": "Is the oil level normal?"}
        )
        assert "result" in resp.json()

    def test_content_type_is_json(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": "Is the oil level normal?"}
        )
        assert "application/json" in resp.headers.get("content-type", "")

    def test_spoken_reply_and_step_question_passed_to_ai(self, client):
        client.post(
            "/checklist/step",
            json={"spoken_reply": "Looks fine", "step_question": "Is pressure normal?"}
        )
        call_args = client._mock_check.call_args
        assert call_args.args[0] == "Looks fine"
        assert call_args.args[1] == "Is pressure normal?"

    def test_whitespace_trimmed_before_call(self, client):
        client.post(
            "/checklist/step",
            json={"spoken_reply": "  Yes  ", "step_question": "  Is oil level normal?  "}
        )
        call_args = client._mock_check.call_args
        assert call_args.args[0] == "Yes"
        assert call_args.args[1] == "Is oil level normal?"


# ---------------------------------------------------------------------------
# 2. Input validation
# ---------------------------------------------------------------------------

class TestChecklistStepValidation:

    def test_empty_spoken_reply_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "", "step_question": "Is oil level normal?"}
        )
        assert resp.status_code == 422

    def test_whitespace_only_spoken_reply_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "   ", "step_question": "Is oil level normal?"}
        )
        assert resp.status_code == 422

    def test_empty_step_question_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": ""}
        )
        assert resp.status_code == 422

    def test_whitespace_only_step_question_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": "   "}
        )
        assert resp.status_code == 422

    def test_missing_spoken_reply_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"step_question": "Is oil level normal?"}
        )
        assert resp.status_code == 422

    def test_missing_step_question_returns_422(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes"}
        )
        assert resp.status_code == 422

    def test_missing_body_returns_422(self, client):
        resp = client.post("/checklist/step")
        assert resp.status_code == 422

    def test_error_response_has_detail(self, client):
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "", "step_question": "Is oil level normal?"}
        )
        assert "detail" in resp.json()


# ---------------------------------------------------------------------------
# 3. Error handling
# ---------------------------------------------------------------------------

class TestChecklistStepErrorHandling:

    def test_503_when_ai_raises(self, client):
        client._mock_check.side_effect = RuntimeError("Gemini API unreachable")
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": "Is oil level normal?"}
        )
        assert resp.status_code == 503

    def test_503_detail_is_user_friendly(self, client):
        client._mock_check.side_effect = Exception("Something broke")
        resp = client.post(
            "/checklist/step",
            json={"spoken_reply": "Yes", "step_question": "Is oil level normal?"}
        )
        body = resp.json()
        assert "detail" in body
        assert "Something broke" not in body["detail"]
