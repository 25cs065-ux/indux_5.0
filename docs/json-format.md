@'
# API JSON Format (LOCKED)

Endpoint: `POST /ask`

Request body:
```json
{"question": "Compressor is overheating what should I check", "machine_id": "compressor-01"}
```

## Response shape

The response has an outer wrapper. The actual answer is inside `answer`.

```json
{
  "status": "success",
  "machine_id": "compressor-01",
  "question": "Compressor is overheating what should I check",
  "answer": {
    "status": "NOT_FOUND",
    "problem_type": "other",
    "summary": "",
    "is_dangerous": false,
    "safety_checklist": [],
    "history_note": "",
    "steps": [],
    "sources": [],
    "escalate": true
  },
  "is_demo": false
}
```

## Reading the response (for the worker app)

- Read `answer.status`. The outer `status` only says the request worked.
- `answer.status` is `OK` or `NOT_FOUND`.
- If `NOT_FOUND`, show the "Escalate to lead engineer" screen (`answer.escalate` is true).
- If `answer.is_dangerous` is true, show the safety checklist and lock the steps until every box is ticked.
- `machine_id` is in the outer wrapper, not inside `answer`.

## Example: OK answer

```json
{
  "status": "success",
  "machine_id": "compressor-01",
  "question": "What is the maximum working pressure of the GA 22",
  "answer": {
    "status": "OK",
    "problem_type": "other",
    "summary": "(short summary)",
    "is_dangerous": false,
    "safety_checklist": [],
    "history_note": "",
    "steps": [
      {"step_no": 1, "instruction": "(step text)", "check_question": "(yes/no question)"}
    ],
    "sources": [{"manual": "GA15-26_Datasheet", "page": 1}],
    "escalate": false
  },
  "is_demo": false
}
```

(Check the exact field names inside `steps` and `sources` against a real response before relying on this example.)

## Rules

- Lists (`steps`, `sources`, `safety_checklist`) are always `[]`, never null or missing.
- Strings are never null. Use `""`. `problem_type` is never null; use `"other"` if unsure.
- `answer.status` is only `OK` or `NOT_FOUND`.
- The flag is `escalate` (not `escalate_to_engineer`).
- Machine ids use hyphens: `compressor-01`, `compressor-02`.
- Manual names have no `` extension (they match `manual_title` in Supabase): `GA15-26_Datasheet`, `GA15-26_Instruction_Book`, `Compressed_Air_Manual`.
- `page` is a number (the PDF page number).
- `problem_type` comes from `docs/lists/problem-types.json`.
- The live safety rules are in `ai/brain.py`. `docs/safety-rules.json` is the reference list; keep both in sync.
'@ | Set-Content -Path docs\json-format.md -Encoding UTF8