# ingest/troubleshooting_override.py
#
# MANUAL-SPECIFIC OVERRIDE (not a general OCR parser fix).
#
# The GA15-26 Instruction Book troubleshooting tables (PDF pages 127-129,
# printed pages 125-127) are scanned images. The OCR path
# (pytesseract.image_to_string) returns plain text without cell positions, so
# _extract_columnar_ts_rows() cannot tell when a Condition cell is blank (the
# previous condition continues). It groups cells in threes, which shifts the
# columns and attaches faults/remedies to the wrong conditions.
#
# This module replaces those broken rows with chunks built from a reference
# transcription verified by reading the original PDF pages:
#   ingest/overrides/ga15_26_troubleshooting.json
#   2 tables, 13 conditions, 47 fault -> remedy rows; conditions may span pages.
#
# One chunk per condition, containing all of its fault/remedy pairs.
#
# Scope: only doc_id "GA15-26_Instruction_Book", only troubleshooting_row
# chunks on pages 127-129. Every other chunk is left exactly as produced.
# Remove this override once the OCR table parser understands cell positions.

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

DOC_ID = "GA15-26_Instruction_Book"
PAGES = (127, 128, 129)
EXPECTED_CONDITIONS = 13
EXPECTED_ROWS = 47
REFERENCE_PATH = Path(__file__).resolve().parent / "overrides" / "ga15_26_troubleshooting.json"

# Chunk IDs for the database replacement of the existing rows. They cannot
# collide with the positional "{doc_id}_{index:05d}" IDs.
OVERRIDE_ID_PREFIX = f"{DOC_ID}_TS_C"


class OverrideError(ValueError):
    """The reference data is incomplete or inconsistent; do not use it."""


def load_reference(path: Path = REFERENCE_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _clean(value: Any) -> bool:
    return isinstance(value, str) and value.strip() != "" and value == value.strip()


def validate_reference(ref: dict[str, Any]) -> list[dict[str, Any]]:
    """
    Check the reference strictly and return the conditions in document order.
    Raises OverrideError listing every problem found (never guesses).
    """
    problems: list[str] = []
    tables = ref.get("tables")
    if not isinstance(tables, list) or not tables:
        raise OverrideError("reference has no tables")

    conditions: list[dict[str, Any]] = []
    last_page = PAGES[0]
    for t_i, table in enumerate(tables):
        title = table.get("title")
        if not _clean(title):
            problems.append(f"table {t_i}: missing or untrimmed title")
        seen: set[str] = set()
        for c_i, cond in enumerate(table.get("conditions") or []):
            where = f"table {t_i} condition {c_i}"
            name = cond.get("condition")
            if not _clean(name):
                problems.append(f"{where}: missing or untrimmed condition text")
                continue
            if name.lower() in seen:
                problems.append(f"{where}: duplicate condition {name!r}")
            seen.add(name.lower())

            pages = cond.get("pages")
            if (
                not isinstance(pages, list)
                or not pages
                or any(p not in PAGES for p in pages)
                or pages != sorted(set(pages))
                or pages != list(range(pages[0], pages[-1] + 1))
            ):
                problems.append(f"{where}: pages must be consecutive values within {PAGES}, got {pages!r}")
            elif pages[0] < last_page:
                problems.append(f"{where}: out of page order")
            else:
                last_page = pages[0]

            rows = cond.get("rows")
            if not isinstance(rows, list) or not rows:
                problems.append(f"{where}: no fault/remedy rows")
                continue
            faults: set[str] = set()
            for r_i, row in enumerate(rows):
                if not _clean(row.get("fault")) or not _clean(row.get("remedy")):
                    problems.append(f"{where} row {r_i}: fault and remedy must both be present")
                elif row["fault"].lower() in faults:
                    problems.append(f"{where} row {r_i}: duplicate fault {row['fault']!r}")
                else:
                    faults.add(row["fault"].lower())
            conditions.append({"table": title, **cond})

    n_cond = len(conditions)
    n_rows = sum(len(c.get("rows") or []) for c in conditions)
    if n_cond != EXPECTED_CONDITIONS:
        problems.append(f"expected {EXPECTED_CONDITIONS} conditions, found {n_cond}")
    if n_rows != EXPECTED_ROWS:
        problems.append(f"expected {EXPECTED_ROWS} fault/remedy rows, found {n_rows}")
    if problems:
        raise OverrideError("; ".join(problems))
    return conditions


def condition_text(cond: dict[str, Any]) -> str:
    """Chunk text: table, condition, pages, then every fault with its remedy."""
    pages = cond["pages"]
    page_label = f"page {pages[0]}" if len(pages) == 1 else f"pages {pages[0]}-{pages[-1]}"
    lines = [
        f"{cond['table']} (GA15-26 Instruction Book, Problem solving, {page_label})",
        f"Condition: {cond['condition']}",
        "Possible faults and remedies for this condition:",
    ]
    for i, row in enumerate(cond["rows"], start=1):
        lines.append(f"{i}. Fault: {row['fault']} | Remedy: {row['remedy']}")
    return "\n".join(lines)


def build_override_records(ref: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    """
    One record per verified condition, in document order:
    {n, condition, table, pages, page_number (first page), text, rows}.
    """
    conditions = validate_reference(ref if ref is not None else load_reference())
    records = []
    for n, cond in enumerate(conditions, start=1):
        records.append(
            {
                "n": n,
                "condition": cond["condition"],
                "table": cond["table"],
                "pages": list(cond["pages"]),
                "page_number": cond["pages"][0],
                "rows": [dict(r) for r in cond["rows"]],
                "text": condition_text(cond),
            }
        )
    return records


def is_overridden_row(doc_id: str, page_number: int, chunk_type: str) -> bool:
    return doc_id == DOC_ID and page_number in PAGES and chunk_type == "troubleshooting_row"


def apply_troubleshooting_override(doc_id: str, chunks: list) -> list:
    """
    Hook for ingest_pdf(): for GA15-26_Instruction_Book, replace the OCR
    troubleshooting_row chunks on pages 127-129 with the verified condition
    chunks, placed where the first replaced row was, then renumber
    chunk_index/chunk_id positionally. Other documents are returned unchanged.
    """
    if doc_id != DOC_ID:
        return chunks
    replaced = [i for i, c in enumerate(chunks) if is_overridden_row(c.doc_id, c.page_number, c.chunk_type)]
    if not replaced:
        return chunks

    records = build_override_records()
    insert_at = replaced[0]
    Chunk = type(chunks[insert_at])  # same Chunk class as the pipeline; no import cycle
    new_chunks = [
        Chunk(
            text=r["text"],
            doc_id=doc_id,
            page_number=r["page_number"],
            chunk_index=0,  # renumbered below
            bbox=None,
            chunk_type="troubleshooting_row",
        )
        for r in records
    ]
    drop = set(replaced)
    kept_before = [c for i, c in enumerate(chunks[:insert_at]) if i not in drop]
    kept_after = [c for i, c in enumerate(chunks) if i > insert_at and i not in drop]
    result = kept_before + new_chunks + kept_after
    for idx, c in enumerate(result):
        c.chunk_index = idx
        c.chunk_id = f"{c.doc_id}_{idx:05d}"
    return result


def plan_database_replacement(existing_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """
    Pure planning for replacing the live rows (no database access).

    existing_rows: the manual's rows (id, page_number, section, chunk_index).
    Returns the exact IDs to delete and the records to insert. New rows reuse
    chunk_index values freed by the deleted rows on the same first page, so
    document order is preserved and (manual_title, chunk_index) stays unique.
    """
    rows = [r for r in existing_rows]
    to_delete = sorted(
        (r for r in rows if r.get("section") == "troubleshooting_row" and r.get("page_number") in PAGES),
        key=lambda r: r["chunk_index"],
    )
    freed: dict[int, list[int]] = {p: [] for p in PAGES}
    for r in to_delete:
        freed[r["page_number"]].append(r["chunk_index"])

    records = build_override_records()
    inserts = []
    for rec in records:
        pool = freed[rec["page_number"]]
        if not pool:
            raise OverrideError(f"no freed chunk_index left on page {rec['page_number']} for {rec['condition']!r}")
        chunk_index = pool.pop(0)
        inserts.append(
            {
                "id": f"{OVERRIDE_ID_PREFIX}{rec['n']:02d}",
                "content": rec["text"],
                "manual_title": DOC_ID,
                "page_number": rec["page_number"],
                "section": "troubleshooting_row",
                "chunk_index": chunk_index,
                "bbox_x0": None,
                "bbox_y0": None,
                "bbox_x1": None,
                "bbox_y1": None,
            }
        )
    existing_ids = {r["id"] for r in rows}
    clash = [i["id"] for i in inserts if i["id"] in existing_ids]
    if clash:
        raise OverrideError(f"override IDs already exist: {clash}")
    return {"delete_ids": [r["id"] for r in to_delete], "inserts": inserts}
