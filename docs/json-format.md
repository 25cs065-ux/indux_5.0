# API JSON Format (LOCKED)

Every answer from `/ask` uses this shape.

## Normal answer (status OK)
```json
{
  "status": "OK",
  "machine_id": "compressor-01",
  "problem_type": "overheating",
  "summary": "Likely high oil or air temperature.",
  "is_dangerous": false,
  "safety_checklist": [],
  "history_note": "",
  "steps": [
    {"step_no": 1, "instruction": "Check the oil level.", "check_question": "Is the oil level between the marks?"}
  ],
  "sources": [{"manual": "GA15-26_Instruction_Book.pdf", "page": 1}],
  "escalate": false
}
```

## Not found (status NOT_FOUND)
```json
{
  "status": "NOT_FOUND",
  "machine_id": "compressor-01",
  "problem_type": "other",
  "summary": "",
  "is_dangerous": false,
  "safety_checklist": [],
  "history_note": "",
  "steps": [],
  "sources": [],
  "escalate": true
}
```

## Rules
- Lists are always `[]`, never null and never missing.
- Strings are always `""`, never null.
- `status` is only `OK` or `NOT_FOUND`.
- `page` is a number (the PDF page number, not the printed one).
- `problem_type` must come from `lists/problem-types.json`.