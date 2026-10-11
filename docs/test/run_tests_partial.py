import csv
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv
load_dotenv(ROOT / ".env")

from ai.brain import ask

QUESTIONS = ROOT / "docs" / "test" / "test-questions.csv"
RESULTS = ROOT / "docs" / "test" / "test-results-partial.csv"

ROUND = sys.argv[1] if len(sys.argv) > 1 else "1"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 13
END = int(sys.argv[3]) if len(sys.argv) > 3 else 28
PAUSE_SECONDS = 4
MACHINE = "compressor-01"
TESTER = "Khushi"


def to_dict(res):
    if isinstance(res, dict):
        return res
    if hasattr(res, "model_dump"):
        return res.model_dump()
    return dict(res)


def find_score(res):
    for key in ("top_distance", "distance", "best_distance", "score", "search_score"):
        if key in res and res[key] is not None:
            return res[key]
    return ""


def qnum(qid):
    return int("".join(ch for ch in qid if ch.isdigit()))


rows_out = []
with open(QUESTIONS, newline="", encoding="utf-8") as f:
    for row in csv.DictReader(f):
        qid = row["id"]
        if not (START <= qnum(qid) <= END):
            continue
        question, cat = row["question"], row["category"]

        try:
            res = to_dict(ask(question, MACHINE))
        except Exception as e:
            print(qid, "ERROR", e)
            rows_out.append([qid, ROUND, "ERROR", "", "", str(e)[:150], TESTER])
            time.sleep(PAUSE_SECONDS)
            continue

        status = res.get("status", "")
        sources = res.get("sources") or []
        escalate = res.get("escalate", res.get("escalate_to_engineer", ""))
        notes = ""

        if cat == "not_in_manual":
            passed = status == "NOT_FOUND" and not res.get("steps")
        elif cat == "safety":
            passed = bool(res.get("is_dangerous"))
        elif cat == "history":
            passed = "CHECK"
            notes = (res.get("history_note") or res.get("summary") or "")[:150]
        else:
            passed = status == "OK" and len(sources) > 0
            if sources:
                notes = f"{sources[0].get('manual')} p{sources[0].get('page')}"

        print(qid, status, passed, find_score(res))
        rows_out.append([qid, ROUND, passed, find_score(res), escalate, notes, TESTER])
        time.sleep(PAUSE_SECONDS)

with open(RESULTS, "w", newline="", encoding="utf-8") as f:
    w = csv.writer(f)
    w.writerow(["id", "round", "passed", "search_score", "escalate", "notes", "tested_by"])
    w.writerows(rows_out)

print("Saved", RESULTS)