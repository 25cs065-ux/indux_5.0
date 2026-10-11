# INDUX 5.0 — Locked JSON Schema Contract

All AI responses from `/ask` adhere strictly to this schema (`ai/schemas.py`).
**Rule:** Arrays are always `[]`, never `null`.

## Schema Fields

| Field | Type | Description |
|---|---|---|
| `status` | string | `"SUCCESS"`, `"NOT_FOUND"`, or `"SAFETY_ALERT"` |
| `problem_type` | string | `'overheating'`, `'low pressure'`, `'oil leak'`, `'electrical'`, `'noise'`, `'belt'`, `'general'` |
| `summary` | string | Brief 1-2 sentence overview of the diagnosis |
| `safety_checklist` | list[string] | Mandatory safety actions (LOTO, depressurization). Empty `[]` if safe. |
| `steps` | list[object] | Ordered repair steps with verification checks. Empty `[]` on `NOT_FOUND`. |
| `sources` | list[object] | Exact manual citations. Empty `[]` on `NOT_FOUND`. |
| `escalate` | boolean | `true` if issue cannot be resolved via manual or requires lead engineer. |
| `search_score` | float \| null | Best chunk vector distance (lower is closer; `0.0` for exact matches). |

---

## Example 1: `SUCCESS` (Standard Fix)
```json
{
  "status": "SUCCESS",
  "problem_type": "low pressure",
  "summary": "Intake air filter is clogged causing insufficient pressure build-up.",
  "safety_checklist": [],
  "steps": [
    {
      "step_number": 1,
      "instruction": "Inspect intake air filter cartridge for dust accumulation.",
      "check_question": "Is the filter cartridge clogged with debris?"
    },
    {
      "step_number": 2,
      "instruction": "Clean cartridge with compressed air or replace if saturated.",
      "check_question": "Is the replacement cartridge seated securely in the housing?"
    }
  ],
  "sources": [
    {
      "manual_title": "Industrial Compressor SOP Manual",
      "page_number": 8,
      "section": "Pressure System"
    }
  ],
  "escalate": false,
  "search_score": 0.312
}