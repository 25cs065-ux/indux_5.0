# ingest/tests/test_troubleshooting_override.py
#
# Regression tests for the GA15-26 troubleshooting-table override
# (ingest/troubleshooting_override.py). Expectations below were typed from the
# original PDF pages 127-129, independently of the JSON reference, so an edit
# to the reference that changes any verified mapping fails here.
#
# Run: .venv\Scripts\python -m pytest ingest/tests/test_troubleshooting_override.py -v

from __future__ import annotations

import copy
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from ingest.pdf_ingestor import Chunk  # noqa: E402
from ingest.troubleshooting_override import (  # noqa: E402
    DOC_ID,
    OVERRIDE_ID_PREFIX,
    OverrideError,
    apply_troubleshooting_override,
    build_override_records,
    load_reference,
    plan_database_replacement,
    validate_reference,
)

# (condition, pages, number of fault/remedy rows), in document order.
EXPECTED_STRUCTURE = [
    ("Compressor starts running, but does not load after a delay time", [127], 4),
    ("Compressor does not unload, safety valve blows", [127], 2),
    ("Condensate is not discharged from condensate separator during loading", [127], 1),
    ("Compressor air output or pressure below normal", [127], 8),
    ("Excessive oil consumption; oil carry-over through discharge line", [127, 128], 4),
    ("Safety valve blows after loading", [128], 5),
    ("Compressor element outlet temperature or delivery air temperature above normal", [128], 6),
    ("Pressure dew point too high", [128], 6),
    ("Condenser pressure too high or too low", [128, 129], 4),
    ("Compressor stops or does not start", [129], 2),
    ("Electronic condensate drain remains inoperative", [129], 1),
    ("Condensate trap continuously discharges air and water", [129], 1),
    ("Evaporator pressure is too high or too low at unload", [129], 3),
]

LOW_PRESSURE_ROWS = [
    ("Air consumption exceeds air delivery of compressor", "Check equipment connected"),
    ("Choked air filter element", "Replace filter element"),
    ("Solenoid valve malfunctioning", "Replace valve"),
    ("Leak in control air tubes", "Replace leaking tubes"),
    ("Inlet valve does not fully open", "Have valve checked"),
    ("Air leakage", "Have leaks repaired"),
    ("Safety valve leaking", "Have valve replaced"),
    ("Compressor element out of order", "Consult Atlas Copco"),
]


@pytest.fixture()
def ref():
    return load_reference()


@pytest.fixture()
def records(ref):
    return build_override_records(ref)


def by_condition(records):
    return {r["condition"]: r for r in records}


# ---------------------------------------------------------------------------
# 1. Reference matches the verified PDF structure
# ---------------------------------------------------------------------------

class TestVerifiedStructure:

    def test_13_conditions_and_47_rows(self, records):
        assert len(records) == 13
        assert sum(len(r["rows"]) for r in records) == 47

    def test_conditions_pages_and_row_counts_in_document_order(self, records):
        assert [(r["condition"], r["pages"], len(r["rows"])) for r in records] == EXPECTED_STRUCTURE

    def test_two_tables_with_7_and_6_conditions(self, records):
        tables = [r["table"] for r in records]
        assert tables[:7] == ["Faults and remedies, compressor"] * 7
        assert tables[7:] == ["Faults and remedies, dryer"] * 6

    def test_low_pressure_has_exactly_its_eight_verified_faults(self, records):
        rows = by_condition(records)["Compressor air output or pressure below normal"]["rows"]
        assert [(r["fault"], r["remedy"]) for r in rows] == LOW_PRESSURE_ROWS

    def test_discharge_tube_belongs_only_to_condensate_condition(self, records):
        owners = [r["condition"] for r in records if any(x["fault"] == "Discharge tube clogged" for x in r["rows"])]
        assert owners == ["Condensate is not discharged from condensate separator during loading"]
        rows = by_condition(records)[owners[0]]["rows"]
        assert rows == [{"fault": "Discharge tube clogged", "remedy": "Check and correct as necessary"}]

    def test_conditions_spanning_pages_keep_their_continued_rows(self, records):
        oil = by_condition(records)["Excessive oil consumption; oil carry-over through discharge line"]
        assert oil["pages"] == [127, 128]
        assert [x["fault"] for x in oil["rows"]] == [
            "Incorrect oil causing foam",
            "Oil level too high",
            "Oil separator defective",
            "Malfunctioning of the scavenge line",
        ]
        cond = by_condition(records)["Condenser pressure too high or too low"]
        assert cond["pages"] == [128, 129]
        assert [x["fault"] for x in cond["rows"]] == [
            "Fan control switch out of order",
            "Fan blades or fan motor out of order",
            "Ambient temperature too high",
            "Condenser externally clogged",
        ]

    @pytest.mark.parametrize(
        "condition,fault,remedy",
        [
            ("Compressor starts running, but does not load after a delay time",
             "Minimum pressure valve leaking (when net is depressurized)", "Have valve checked"),
            ("Compressor does not unload, safety valve blows", "Inlet valve does not close", "Have valve checked"),
            ("Excessive oil consumption; oil carry-over through discharge line",
             "Oil level too high", "Check for overfilling. Release pressure and drain oil to correct level."),
            ("Safety valve blows after loading", "Oil separator element clogged", "Replace oil separator element"),
            ("Compressor element outlet temperature or delivery air temperature above normal",
             "Oil level too low", "Check and correct"),
            ("Compressor element outlet temperature or delivery air temperature above normal",
             "Compressor element out of order", "Consult Atlas Copco Customer Centre"),
            ("Pressure dew point too high", "Shortage of refrigerant", "Have circuit checked for leaks and recharged"),
            ("Condenser pressure too high or too low", "Fan control switch out of order", "Replace"),
            ("Compressor stops or does not start",
             "Thermal protection of refrigerant compressor motor has tripped",
             "Motor will restart when motor windings have cooled down"),
            ("Evaporator pressure is too high or too low at unload", "Condenser pressure too high or too low", "See above"),
            ("Evaporator pressure is too high or too low at unload",
             "Shortage of refrigerant", "Have circuit checked for leaks and recharged if necessary"),
        ],
    )
    def test_spot_checked_associations(self, records, condition, fault, remedy):
        rows = by_condition(records)[condition]["rows"]
        assert {"fault": fault, "remedy": remedy} in rows

    def test_no_fault_text_appears_as_a_condition(self, records):
        conditions = {r["condition"] for r in records}
        for bad in ("Discharge tube clogged", "Replace filter element", "Have valve replaced", "Air leakage"):
            assert bad not in conditions

    def test_no_duplicate_conditions_or_duplicate_faults_within_a_condition(self, records):
        names = [r["condition"] for r in records]
        assert len(names) == len(set(names))
        for r in records:
            faults = [x["fault"] for x in r["rows"]]
            assert len(faults) == len(set(faults)), r["condition"]


# ---------------------------------------------------------------------------
# 2. Validation refuses incomplete or inconsistent references
# ---------------------------------------------------------------------------

class TestValidationRefuses:

    def _first_cond(self, ref):
        return ref["tables"][0]["conditions"][0]

    def test_missing_row(self, ref):
        bad = copy.deepcopy(ref)
        bad["tables"][0]["conditions"][3]["rows"].pop()
        with pytest.raises(OverrideError, match="47"):
            validate_reference(bad)

    def test_missing_condition(self, ref):
        bad = copy.deepcopy(ref)
        bad["tables"][1]["conditions"].pop()
        with pytest.raises(OverrideError, match="13 conditions"):
            validate_reference(bad)

    def test_duplicate_condition(self, ref):
        bad = copy.deepcopy(ref)
        bad["tables"][0]["conditions"][1]["condition"] = self._first_cond(bad)["condition"]
        with pytest.raises(OverrideError, match="duplicate condition"):
            validate_reference(bad)

    def test_empty_remedy(self, ref):
        bad = copy.deepcopy(ref)
        self._first_cond(bad)["rows"][0]["remedy"] = ""
        with pytest.raises(OverrideError, match="fault and remedy"):
            validate_reference(bad)

    def test_untrimmed_text(self, ref):
        bad = copy.deepcopy(ref)
        self._first_cond(bad)["rows"][0]["fault"] = " Solenoid valve out of order"
        with pytest.raises(OverrideError):
            validate_reference(bad)

    def test_page_outside_127_129(self, ref):
        bad = copy.deepcopy(ref)
        self._first_cond(bad)["pages"] = [126]
        with pytest.raises(OverrideError, match="pages"):
            validate_reference(bad)

    def test_non_consecutive_pages(self, ref):
        bad = copy.deepcopy(ref)
        self._first_cond(bad)["pages"] = [127, 129]
        with pytest.raises(OverrideError, match="pages"):
            validate_reference(bad)

    def test_duplicate_fault_within_condition(self, ref):
        bad = copy.deepcopy(ref)
        rows = bad["tables"][0]["conditions"][3]["rows"]
        rows[1] = dict(rows[0])
        bad["tables"][0]["conditions"][3]["rows"].append({"fault": "Extra", "remedy": "Extra"})
        with pytest.raises(OverrideError, match="duplicate fault"):
            validate_reference(bad)


# ---------------------------------------------------------------------------
# 3. Chunk text
# ---------------------------------------------------------------------------

class TestChunkText:

    def test_text_contains_condition_and_every_pair(self, records):
        for r in records:
            assert f"Condition: {r['condition']}" in r["text"]
            for i, row in enumerate(r["rows"], start=1):
                assert f"{i}. Fault: {row['fault']} | Remedy: {row['remedy']}" in r["text"]

    def test_page_labels(self, records):
        rec = by_condition(records)
        assert "page 127)" in rec["Compressor air output or pressure below normal"]["text"]
        assert "pages 127-128)" in rec["Excessive oil consumption; oil carry-over through discharge line"]["text"]
        assert "pages 128-129)" in rec["Condenser pressure too high or too low"]["text"]

    def test_page_number_is_first_page(self, records):
        assert [r["page_number"] for r in records] == [p[0] for _, p, _ in EXPECTED_STRUCTURE]

    def test_low_pressure_text_does_not_mention_discharge_tube(self, records):
        assert "Discharge tube" not in by_condition(records)["Compressor air output or pressure below normal"]["text"]


# ---------------------------------------------------------------------------
# 4. Pipeline hook: only the GA15-26 troubleshooting rows on pp.127-129 change
# ---------------------------------------------------------------------------

def _chunk(doc, page, idx, kind, text):
    return Chunk(text=text, doc_id=doc, page_number=page, chunk_index=idx, chunk_type=kind)


def _pipeline_chunks(doc=DOC_ID):
    out, idx = [], 0
    def add(page, kind, text):
        nonlocal idx
        out.append(_chunk(doc, page, idx, kind, text)); idx += 1
    add(126, "text", "dryer cleaning text")
    for i in range(12): add(127, "troubleshooting_row", f"broken p127 row {i}")
    add(127, "text", "Warning: press the stop button")
    for i in range(14): add(128, "troubleshooting_row", f"broken p128 row {i}")
    add(128, "text", "Instruction book")
    for i in range(11): add(129, "troubleshooting_row", f"broken p129 row {i}")
    add(130, "text", "Technical data")
    add(50, "troubleshooting_row", "unrelated row elsewhere")
    return out


class TestPipelineHook:

    def test_other_documents_are_untouched(self):
        chunks = _pipeline_chunks(doc="Compressed_Air_Manual")
        assert apply_troubleshooting_override("Compressed_Air_Manual", chunks) is chunks

    def test_replaces_37_rows_with_13_condition_chunks(self):
        result = apply_troubleshooting_override(DOC_ID, _pipeline_chunks())
        ts = [c for c in result if c.chunk_type == "troubleshooting_row" and c.page_number in (127, 128, 129)]
        assert len(ts) == 13
        assert not any("broken" in c.text for c in result)
        assert [c.text.split("\n")[1] for c in ts] == [f"Condition: {name}" for name, _, _ in EXPECTED_STRUCTURE]

    def test_unrelated_chunks_keep_text_and_order(self):
        before = [c.text for c in _pipeline_chunks() if not (c.chunk_type == "troubleshooting_row" and c.page_number in (127, 128, 129))]
        result = apply_troubleshooting_override(DOC_ID, _pipeline_chunks())
        after = [c.text for c in result if not c.text.startswith("Faults and remedies")]
        assert after == before

    def test_condition_chunks_sit_where_the_table_started(self):
        result = apply_troubleshooting_override(DOC_ID, _pipeline_chunks())
        assert result[0].text == "dryer cleaning text"
        assert result[1].text.startswith("Faults and remedies, compressor")

    def test_renumbered_positionally_with_unique_ids(self):
        result = apply_troubleshooting_override(DOC_ID, _pipeline_chunks())
        assert [c.chunk_index for c in result] == list(range(len(result)))
        assert [c.chunk_id for c in result] == [f"{DOC_ID}_{i:05d}" for i in range(len(result))]
        assert len(result) == len(_pipeline_chunks()) - 37 + 13

    def test_no_rows_to_replace_is_a_no_op(self):
        chunks = [_chunk(DOC_ID, 10, 0, "text", "intro")]
        assert apply_troubleshooting_override(DOC_ID, chunks) is chunks


# ---------------------------------------------------------------------------
# 5. Database replacement plan (pure; no database access)
# ---------------------------------------------------------------------------

def _live_like_rows():
    """Mirrors the live layout: ts rows at 324-335 (p127), 338-351 (p128), 353-363 (p129)."""
    rows = [{"id": f"{DOC_ID}_{i:05d}", "page_number": 100, "section": "text", "chunk_index": i} for i in range(0, 324)]
    pages = {**{i: 127 for i in range(324, 336)}, 336: 127, 337: 127,
             **{i: 128 for i in range(338, 352)}, 352: 128,
             **{i: 129 for i in range(353, 364)}, 364: 129}
    for i in range(324, 365):
        section = "text" if i in (336, 337, 352, 364) else "troubleshooting_row"
        rows.append({"id": f"{DOC_ID}_{i:05d}", "page_number": pages[i], "section": section, "chunk_index": i})
    rows += [{"id": f"{DOC_ID}_{i:05d}", "page_number": 131, "section": "text", "chunk_index": i} for i in range(365, 416)]
    return rows


class TestReplacementPlan:

    def test_deletes_exactly_the_37_troubleshooting_rows(self):
        plan = plan_database_replacement(_live_like_rows())
        assert len(plan["delete_ids"]) == 37
        assert plan["delete_ids"][0] == f"{DOC_ID}_00324"
        assert f"{DOC_ID}_00336" not in plan["delete_ids"]  # text chunk on p127 kept

    def test_inserts_13_rows_with_override_ids(self):
        plan = plan_database_replacement(_live_like_rows())
        ids = [r["id"] for r in plan["inserts"]]
        assert ids == [f"{OVERRIDE_ID_PREFIX}{n:02d}" for n in range(1, 14)]
        assert all(r["manual_title"] == DOC_ID and r["section"] == "troubleshooting_row" for r in plan["inserts"])

    def test_reuses_freed_indices_on_the_same_page(self):
        plan = plan_database_replacement(_live_like_rows())
        assert [r["chunk_index"] for r in plan["inserts"]] == [324, 325, 326, 327, 328, 338, 339, 340, 341, 353, 354, 355, 356]

    def test_final_state_has_unique_ids_and_indices(self):
        rows = _live_like_rows()
        plan = plan_database_replacement(rows)
        kept = [r for r in rows if r["id"] not in set(plan["delete_ids"])]
        final = kept + plan["inserts"]
        assert len(final) == 416 - 37 + 13 == 392
        assert len({r["id"] for r in final}) == 392
        assert len({r["chunk_index"] for r in final}) == 392

    def test_refuses_when_override_ids_already_exist(self):
        rows = _live_like_rows() + [{"id": f"{OVERRIDE_ID_PREFIX}01", "page_number": 127, "section": "x", "chunk_index": 999}]
        with pytest.raises(OverrideError, match="already exist"):
            plan_database_replacement(rows)
