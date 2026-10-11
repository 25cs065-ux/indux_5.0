# ingest/verify_ingestion.py
#
# Stage 1 / Stage 2 validation script.
# Queries Supabase ONLY — no Gemini calls, no embeddings, no writes.
#
# Usage:
#   py -m ingest.verify_ingestion
#
# What it does:
#   1. Counts rows in manual_chunks WHERE manual_title = 'GA15-26_Instruction_Book'
#   2. Prints distinct chunk types and page-number range
#   3. Prints a sample of troubleshooting_row chunks
#   4. Runs 4 keyword (ilike) retrieval probes — no vector embedding needed
#      so this is completely offline from Gemini.

from __future__ import annotations

import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(dotenv_path=Path(__file__).resolve().parent / ".env")

SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")
DOC_ID = "GA15-26_Instruction_Book"
TABLE = "manual_chunks"

SEP = "-" * 70


def get_client():
    try:
        from supabase import create_client
    except ImportError:
        print("ERROR: supabase package not installed. Run: py -m pip install supabase")
        sys.exit(1)
    if not SUPABASE_URL or not SUPABASE_KEY:
        print("ERROR: SUPABASE_URL or SUPABASE_KEY not set in ingest/.env")
        sys.exit(1)
    return create_client(SUPABASE_URL, SUPABASE_KEY)


def section(title: str):
    print(f"\n{SEP}")
    print(f"  {title}")
    print(SEP)


def main():
    client = get_client()
    tbl = client.table(TABLE)

    # ------------------------------------------------------------------
    # 1. Total row count for this doc
    # ------------------------------------------------------------------
    section("1. Row count for GA15-26_Instruction_Book")
    res = (
        tbl.select("id", count="exact")
        .eq("manual_title", DOC_ID)
        .execute()
    )
    total = res.count
    print(f"  Total rows in Supabase: {total}")
    if total == 0:
        print("  !! No rows found. Check that ingestion completed successfully.")
        sys.exit(1)

    # ------------------------------------------------------------------
    # 2. Chunk type breakdown
    # ------------------------------------------------------------------
    section("2. Chunk type breakdown")
    res2 = (
        tbl.select("section")
        .eq("manual_title", DOC_ID)
        .execute()
    )
    from collections import Counter
    counts = Counter(r["section"] for r in res2.data)
    for chunk_type, n in sorted(counts.items()):
        print(f"  {chunk_type:<25} {n:>5} chunks")

    # ------------------------------------------------------------------
    # 3. Page number range
    # ------------------------------------------------------------------
    section("3. Page number range")
    res3 = (
        tbl.select("page_number")
        .eq("manual_title", DOC_ID)
        .execute()
    )
    pages = [r["page_number"] for r in res3.data if r["page_number"] is not None]
    if pages:
        print(f"  Min page: {min(pages)}   Max page: {max(pages)}")
        print(f"  Distinct pages with content: {len(set(pages))}")
    else:
        print("  No page number data found.")

    # ------------------------------------------------------------------
    # 4. Sample troubleshooting_row chunks
    # ------------------------------------------------------------------
    section("4. Sample troubleshooting_row chunks (first 5)")
    res4 = (
        tbl.select("id, page_number, content")
        .eq("manual_title", DOC_ID)
        .eq("section", "troubleshooting_row")
        .limit(5)
        .execute()
    )
    if not res4.data:
        print("  No troubleshooting_row chunks found.")
    else:
        for row in res4.data:
            print(f"\n  [{row['id']} | page {row['page_number']}]")
            print(f"  {row['content'][:300]}")

    # ------------------------------------------------------------------
    # 5. Keyword retrieval probes (ilike — no embedding needed)
    # ------------------------------------------------------------------
    probes = [
        ("Safety warning — LOTO / emergency stop",
         "lockout"),
        ("Start-up procedure",
         "starting"),
        ("Troubleshooting — compressor does not start",
         "does not start"),
        ("Out-of-scope question — diesel engine",
         "diesel engine"),
    ]

    section("5. Keyword retrieval probes")
    for label, keyword in probes:
        print(f"\n  Query: \"{label}\"  (keyword: '{keyword}')")
        res5 = (
            tbl.select("id, manual_title, page_number, section, content")
            .eq("manual_title", DOC_ID)
            .ilike("content", f"%{keyword}%")
            .limit(3)
            .execute()
        )
        hits = res5.data
        if not hits:
            print(f"  -> No hits for '{keyword}'")
        else:
            print(f"  -> {len(hits)} hit(s):")
            for h in hits:
                snippet = h["content"].replace("\n", " ")[:200]
                print(f"     page {h['page_number']} [{h['section']}]  {snippet}...")

    # ------------------------------------------------------------------
    # Summary
    # ------------------------------------------------------------------
    section("SUMMARY")
    print(f"  Document     : {DOC_ID}")
    print(f"  Total chunks : {total}")
    ts_count = counts.get("troubleshooting_row", 0)
    txt_count = counts.get("text", 0)
    print(f"  text chunks  : {txt_count}")
    print(f"  ts_row chunks: {ts_count}")
    print()
    print("  Verification complete. No embeddings generated, no writes performed.")
    print()


if __name__ == "__main__":
    main()
