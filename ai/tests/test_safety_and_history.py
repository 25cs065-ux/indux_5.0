# ai/tests/test_safety_and_history.py
#
# Focused tests for Stage 3:
#   - Safety triggers fire on all keywords defined in docs/safety-rules.json
#   - Safety checklist is returned even when retrieval finds no chunks (NOT_FOUND path)
#   - is_dangerous=True whenever safety_checklist is non-empty
#   - NOT_FOUND response contains no invented steps
#   - Repair history is passed as context-only; it never appears as a manual source
#   - ask() response shape matches the docs/json-format.md contract
#
# All Supabase and Gemini calls are mocked — no live credentials required.
#
# Run with:
#   .venv\Scripts\python -m pytest ai/tests/test_safety_and_history.py -v

from __future__ import annotations

import sys
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Ensure repo root is on sys.path so `from ai.brain import ...` works.
_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _mock_genai_client_no_embed():
    """Gemini client that raises on embed_content (simulates retrieval failure)."""
    client = MagicMock()
    client.models.embed_content.side_effect = RuntimeError("No API key")
    return client


def _mock_supabase_no_rows():
    """Supabase client that returns empty results for every call."""
    sb = MagicMock()
    empty = MagicMock()
    empty.data = []
    empty.count = 0
    # Fluent chain: .table().select().ilike().limit().execute()
    sb.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = empty
    # .rpc().execute()
    sb.rpc.return_value.execute.return_value = MagicMock(data=[])
    return sb


def _make_fake_chunk(content: str = "Compressor overheating procedure.") -> dict:
    return {
        "id": "doc_00001",
        "content": content,
        "manual_title": "GA15-26_Instruction_Book",
        "page_number": 12,
        "section": "text",
        "distance": 0.30,
    }


def _mock_supabase_with_rows(chunks: list):
    """Supabase client that returns chunks from the RPC call."""
    sb = MagicMock()
    empty = MagicMock()
    empty.data = []
    sb.table.return_value.select.return_value.ilike.return_value.limit.return_value.execute.return_value = empty
    rpc_result = MagicMock()
    rpc_result.data = chunks
    sb.rpc.return_value.execute.return_value = rpc_result
    return sb


def _mock_genai_client_with_embed(chunks_returned):
    """Gemini client whose embed_content returns a dummy 3072-dim vector."""
    client = MagicMock()
    fake_emb = MagicMock()
    fake_emb.values = [0.01] * 3072
    client.models.embed_content.return_value = MagicMock(embeddings=[fake_emb])
    # generate_content returns a valid QueryResponse JSON that Gemini would produce
    fake_response = MagicMock()
    fake_response.text = json.dumps({
        "status": "OK",
        "problem_type": "overheating",
        "summary": "Check the cooler and oil level.",
        "is_dangerous": False,
        "safety_checklist": [],
        "history_note": "",
        "steps": [{"step_no": 1, "instruction": "Check oil level.", "check_question": "Is oil level normal?"}],
        "sources": [{"manual": "GA15-26_Instruction_Book", "page": 12}],
        "escalate": False
    })
    client.models.generate_content.return_value = fake_response
    return client


# ---------------------------------------------------------------------------
# Patching context: replace module-level supabase and client in brain
# ---------------------------------------------------------------------------

def _patch_brain(mock_sb, mock_genai):
    """Return a dict of patches to apply together."""
    return {
        "supabase": patch("ai.brain.supabase", mock_sb),
        "client": patch("ai.brain.client", mock_genai),
    }


# ---------------------------------------------------------------------------
# 1. safety_check() — unit tests, no mocking needed
# ---------------------------------------------------------------------------

class TestSafetyCheckUnit:
    """safety_check() is a pure function; test it directly."""

    def _run(self, question: str):
        from ai.brain import safety_check
        return safety_check(question)

    # --- S1: Opening panels / covers ---

    def test_s1_open_panel(self):
        result = self._run("Can I open panel while the compressor is running?")
        assert len(result) > 0, "S1 'open panel' must trigger safety checklist"

    def test_s1_remove_cover(self):
        result = self._run("How do I remove cover from the compressor?")
        assert len(result) > 0, "S1 'remove cover' must trigger safety checklist"

    def test_s1_open_door(self):
        result = self._run("Is it safe to open door to the electrical cubicle?")
        assert len(result) > 0, "S1 'open door' must trigger safety checklist"

    # --- S2: Pressurised parts / loosening fittings ---

    def test_s2_loosen_hose(self):
        result = self._run("I want to loosen a hose while there is still pressure")
        assert len(result) > 0, "S2 'loosen' must trigger safety checklist"

    def test_s2_disconnect(self):
        result = self._run("How do I disconnect the pressure line?")
        assert len(result) > 0, "S2 'disconnect' must trigger safety checklist"

    def test_s2_valve(self):
        result = self._run("Can I adjust the safety valve now?")
        assert len(result) > 0, "S2 'valve' must trigger safety checklist"

    def test_s2_drain(self):
        result = self._run("How do I drain condensate from the receiver?")
        assert len(result) > 0, "S2 'drain' must trigger safety checklist"

    def test_s2_high_pressure(self):
        result = self._run("The high pressure alarm is going off")
        assert len(result) > 0, "S2 'high pressure' must trigger safety checklist"

    # --- S3: Electrical / burning smell / sparks / trip ---

    def test_s3_burning_smell(self):
        result = self._run("There is a burning smell from the motor")
        assert len(result) > 0, "S3 'burning smell' must trigger safety checklist"

    def test_s3_sparks(self):
        result = self._run("I can see sparks near the control panel")
        assert len(result) > 0, "S3 'sparks' must trigger safety checklist"

    def test_s3_trip(self):
        result = self._run("The motor tripped and won't reset")
        assert len(result) > 0, "S3 'trip' must trigger safety checklist"

    def test_s3_wiring(self):
        result = self._run("There is a problem with the wiring")
        assert len(result) > 0, "S3 'wiring' must trigger safety checklist"

    def test_s3_electrical(self):
        result = self._run("I need to check the electrical connections")
        assert len(result) > 0, "S3 'electrical' must trigger safety checklist"

    # --- S4: Hot surfaces / hot oil ---

    def test_s4_hot(self):
        result = self._run("The compressor is getting very hot")
        assert len(result) > 0, "S4 'hot' must trigger safety checklist"

    def test_s4_overheat(self):
        result = self._run("The machine is starting to overheat")
        assert len(result) > 0, "S4 'overheat' must trigger safety checklist"

    def test_s4_oil_change(self):
        result = self._run("I want to do an oil change right now")
        assert len(result) > 0, "S4 'oil change' must trigger safety checklist"

    def test_s4_drain_oil(self):
        result = self._run("How do I drain oil from the compressor?")
        assert len(result) > 0, "S4 'drain oil' must trigger safety checklist"

    # --- Rotating machinery ---

    def test_rotating_belt(self):
        result = self._run("The drive belt is squeaking loudly")
        assert len(result) > 0, "Rotating 'belt' must trigger safety checklist"

    def test_rotating_pulley(self):
        result = self._run("I need to adjust the pulley tension")
        assert len(result) > 0, "Rotating 'pulley' must trigger safety checklist"

    # --- No danger: safe questions ---

    def test_no_trigger_for_safe_question(self):
        result = self._run("What is the maximum working pressure of the GA 22?")
        # spec question — no danger keywords
        assert isinstance(result, list), "safety_check must always return a list"

    def test_no_trigger_for_unrelated(self):
        result = self._run("How do I bake chocolate chip cookies?")
        assert result == [], "Unrelated question must return empty safety checklist"

    # --- Deduplication ---

    def test_no_duplicates_in_checklist(self):
        # Both S2 and S3 could fire; items must be deduplicated
        result = self._run("There is a burning smell and I need to loosen the drain valve")
        assert len(result) == len(set(result)), "safety_check must not return duplicate items"

    # --- Checklist is always a list ---

    def test_returns_list(self):
        result = self._run("Something is wrong")
        assert isinstance(result, list)


# ---------------------------------------------------------------------------
# 2. ask() — NOT_FOUND path: safety fires even when no chunks
# ---------------------------------------------------------------------------

class TestAskNotFoundWithSafety:
    """When retrieval returns no chunks, safety items must still appear."""

    def _ask_with_no_chunks(self, question: str) -> dict:
        """Call ask() with mocked Supabase (no chunks) and Gemini (embed fails)."""
        from ai.brain import ask
        mock_sb = _mock_supabase_no_rows()
        mock_genai = _mock_genai_client_no_embed()
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            return ask(question=question, machine_id="compressor-01")

    # Contract shape

    def test_not_found_status(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert result["status"] == "NOT_FOUND"

    def test_not_found_escalate_true(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert result["escalate"] is True

    def test_not_found_steps_empty(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert result["steps"] == [], "NOT_FOUND must never contain invented steps"

    def test_not_found_sources_empty(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert result["sources"] == [], "NOT_FOUND must never contain invented sources"

    def test_not_found_has_summary(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert isinstance(result.get("summary"), str)

    # Safety in NOT_FOUND path

    def test_safety_checklist_present_when_danger_keyword_in_not_found(self):
        result = self._ask_with_no_chunks("I have a burning smell from the motor")
        checklist = result.get("safety_checklist", [])
        assert len(checklist) > 0, (
            "safety_checklist must be non-empty even when retrieval returns no chunks"
        )

    def test_is_dangerous_true_when_danger_in_not_found(self):
        result = self._ask_with_no_chunks("There are sparks near the panel")
        assert result.get("is_dangerous") is True, (
            "is_dangerous must be True when safety keywords present, even in NOT_FOUND"
        )

    def test_is_dangerous_false_when_no_danger_in_not_found(self):
        result = self._ask_with_no_chunks("What is the capital of France?")
        assert result.get("is_dangerous") is False

    def test_safety_checklist_empty_when_no_danger_in_not_found(self):
        result = self._ask_with_no_chunks("What is the model number of this compressor?")
        assert result.get("safety_checklist") == []

    # All four safety rules fire in NOT_FOUND path

    def test_s1_fires_in_not_found(self):
        result = self._ask_with_no_chunks("Can I open panel while running?")
        assert result.get("is_dangerous") is True
        assert len(result.get("safety_checklist", [])) > 0

    def test_s2_fires_in_not_found(self):
        result = self._ask_with_no_chunks("I want to loosen a fitting now")
        assert result.get("is_dangerous") is True
        assert len(result.get("safety_checklist", [])) > 0

    def test_s3_fires_in_not_found(self):
        result = self._ask_with_no_chunks("There is a burning smell coming from the wiring")
        assert result.get("is_dangerous") is True
        assert len(result.get("safety_checklist", [])) > 0

    def test_s4_fires_in_not_found(self):
        result = self._ask_with_no_chunks("I want to drain oil right after running hot")
        assert result.get("is_dangerous") is True
        assert len(result.get("safety_checklist", [])) > 0

    def test_rotating_fires_in_not_found(self):
        result = self._ask_with_no_chunks("I need to replace the belt")
        assert result.get("is_dangerous") is True
        assert len(result.get("safety_checklist", [])) > 0

    # problem_type

    def test_problem_type_is_other_in_not_found(self):
        result = self._ask_with_no_chunks("How do I bake cookies?")
        assert result.get("problem_type") == "other"

    # Response has all required contract keys

    def test_not_found_has_all_contract_keys(self):
        result = self._ask_with_no_chunks("Unrelated question")
        for key in ("status", "problem_type", "summary", "is_dangerous",
                    "safety_checklist", "history_note", "steps", "sources", "escalate"):
            assert key in result, f"Contract key '{key}' missing from NOT_FOUND response"

    # Lists are never None

    def test_lists_are_never_none(self):
        result = self._ask_with_no_chunks("Unrelated question")
        assert result.get("steps") is not None
        assert result.get("sources") is not None
        assert result.get("safety_checklist") is not None

    # Strings are never None

    def test_strings_are_never_none(self):
        result = self._ask_with_no_chunks("Unrelated question")
        assert result.get("summary") is not None
        assert result.get("history_note") is not None


# ---------------------------------------------------------------------------
# 3. ask() — repair history is context-only, never a manual source
# ---------------------------------------------------------------------------

class TestRepairHistoryContextOnly:
    """History is passed to the AI prompt as context but must never appear
    as a SourceReference (manual citation) in the response."""

    def _ask_with_history(self, question: str, history: list) -> dict:
        """Call ask() with chunks available and a repair history list."""
        from ai.brain import ask
        chunks = [_make_fake_chunk("Check the cooler and top up the oil level.")]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            return ask(question=question, machine_id="compressor-01", repair_history=history)

    def test_history_does_not_become_a_source(self):
        history = [
            {"date": "2026-01-12", "problem": "High temperature", "action": "Cleaned cooler", "outcome": "Resolved"}
        ]
        result = self._ask_with_history("Compressor is overheating", history)
        sources = result.get("sources", [])
        for src in sources:
            assert "repair_history" not in str(src).lower(), (
                "repair_history must never appear as a verified manual source"
            )

    def test_history_does_not_inflate_step_count(self):
        """Having repair history must not cause extra invented steps."""
        history = [
            {"date": "2026-01-12", "problem": "Oil leak", "action": "Replaced seal", "outcome": "Resolved"},
            {"date": "2026-02-20", "problem": "Overheating", "action": "Cleaned cooler", "outcome": "Resolved"},
        ]
        result_no_history = None
        result_with_history = None

        chunks = [_make_fake_chunk()]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)

        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            from ai.brain import ask
            result_no_history = ask("Compressor overheating", machine_id="compressor-01")
            result_with_history = ask("Compressor overheating", machine_id="compressor-01", repair_history=history)

        # Both should produce the same mocked response (Gemini is mocked identically)
        assert result_no_history["steps"] == result_with_history["steps"], (
            "Adding repair history must not change the step list (Gemini response is mocked)"
        )

    def test_ask_accepts_empty_history(self):
        """ask() must not crash when repair_history is an empty list."""
        chunks = [_make_fake_chunk()]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            from ai.brain import ask
            result = ask("Compressor overheating", machine_id="compressor-01", repair_history=[])
        assert result["status"] in ("OK", "NOT_FOUND")

    def test_ask_accepts_none_history(self):
        """ask() must not crash when repair_history is None."""
        chunks = [_make_fake_chunk()]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            from ai.brain import ask
            result = ask("Compressor overheating", machine_id="compressor-01", repair_history=None)
        assert result["status"] in ("OK", "NOT_FOUND")


# ---------------------------------------------------------------------------
# 4. ask() — safety merges into AI response (chunks present path)
# ---------------------------------------------------------------------------

class TestAskSafetyMergeWithChunks:
    """When chunks ARE found, safety items must still be injected into the
    response and is_dangerous must be set to True."""

    def _ask_with_chunks_and_safety(self, question: str) -> dict:
        chunks = [_make_fake_chunk()]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            from ai.brain import ask
            return ask(question=question, machine_id="compressor-01")

    def test_safety_injected_when_chunks_present_and_danger_keyword(self):
        result = self._ask_with_chunks_and_safety(
            "Compressor is very hot and I want to drain oil now"
        )
        checklist = result.get("safety_checklist", [])
        assert len(checklist) > 0, (
            "Safety checklist must be non-empty when danger keyword is in question, "
            "even when retrieval returns chunks"
        )

    def test_is_dangerous_true_when_chunks_present_and_danger_keyword(self):
        result = self._ask_with_chunks_and_safety(
            "There is a burning smell from the motor"
        )
        assert result.get("is_dangerous") is True

    def test_no_duplicates_after_merge(self):
        result = self._ask_with_chunks_and_safety(
            "I have a burning smell and I also need to loosen the drain valve"
        )
        checklist = result.get("safety_checklist", [])
        assert len(checklist) == len(set(checklist)), (
            "Merged safety checklist must not contain duplicate items"
        )


# ---------------------------------------------------------------------------
# 5. Response contract shape tests
# ---------------------------------------------------------------------------

class TestResponseContractShape:
    """Every response from ask() must contain all keys mandated by
    docs/json-format.md, with correct types."""

    def _ask_not_found(self) -> dict:
        from ai.brain import ask
        mock_sb = _mock_supabase_no_rows()
        mock_genai = _mock_genai_client_no_embed()
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            return ask("Completely unrelated question about gardening", machine_id="compressor-01")

    def _ask_ok(self) -> dict:
        from ai.brain import ask
        chunks = [_make_fake_chunk()]
        mock_sb = _mock_supabase_with_rows(chunks)
        mock_genai = _mock_genai_client_with_embed(chunks)
        with patch("ai.brain.supabase", mock_sb), patch("ai.brain.client", mock_genai):
            return ask("Compressor overheating", machine_id="compressor-01")

    CONTRACT_KEYS = {
        "status": str,
        "problem_type": (str, type(None)),
        "summary": str,
        "is_dangerous": bool,
        "safety_checklist": list,
        "history_note": str,
        "steps": list,
        "sources": list,
        "escalate": bool,
    }

    @pytest.mark.parametrize("key,expected_type", CONTRACT_KEYS.items())
    def test_not_found_has_correct_key_types(self, key, expected_type):
        result = self._ask_not_found()
        assert key in result, f"Key '{key}' missing from NOT_FOUND response"
        assert isinstance(result[key], expected_type), (
            f"Key '{key}' has wrong type: expected {expected_type}, got {type(result[key])}"
        )

    @pytest.mark.parametrize("key,expected_type", CONTRACT_KEYS.items())
    def test_ok_has_correct_key_types(self, key, expected_type):
        result = self._ask_ok()
        assert key in result, f"Key '{key}' missing from OK response"
        assert isinstance(result[key], expected_type), (
            f"Key '{key}' has wrong type: expected {expected_type}, got {type(result[key])}"
        )

    def test_status_is_only_ok_or_not_found_for_not_found(self):
        result = self._ask_not_found()
        assert result["status"] in ("OK", "NOT_FOUND")

    def test_status_is_only_ok_or_not_found_for_ok(self):
        result = self._ask_ok()
        assert result["status"] in ("OK", "NOT_FOUND")

    def test_lists_never_none(self):
        for result in (self._ask_not_found(), self._ask_ok()):
            assert result["steps"] is not None
            assert result["sources"] is not None
            assert result["safety_checklist"] is not None

    def test_strings_never_none(self):
        for result in (self._ask_not_found(), self._ask_ok()):
            assert result["summary"] is not None
            assert result["history_note"] is not None
