import os
import re
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client
from schemas import QueryResponse, StepItem, SourceReference

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
supabase: Client = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_KEY", "")
)

SAFETY_TRIGGERS = [
    {
        "keywords": ["electrical", "wiring", "high voltage", "capacitor", "shock", "motor terminal"],
        "checklist": [
            "Perform Lockout/Tagout (LOTO) on the main breaker.",
            "Verify zero electrical energy with a calibrated multimeter.",
            "Wear insulated rubber gloves and eye protection."
        ]
    },
    {
        "keywords": ["high pressure", "receiver tank", "blowdown", "pressure relief", "burst"],
        "checklist": [
            "Turn off the unit and vent all air until pressure gauge reads 0 PSI.",
            "Do not loosen any fitting or hose under active pressure.",
            "Wear safety goggles and ear protection."
        ]
    },
    {
        "keywords": ["belt", "pulley", "flywheel", "rotating", "fan blade"],
        "checklist": [
            "Power down and tag out machine.",
            "Ensure drive pulleys have completely stopped rotating.",
            "Do not place fingers between belt and pulley groove."
        ]
    }
]

SIMILARITY_DISTANCE_CUTOFF = 0.65

def get_embedding(text: str) -> List[float]:
    response = client.models.embed_content(
        model="gemini-embedding-001",
        contents=text
    )
    return response.embeddings[0].values

def safety_check(question: str) -> List[str]:
    q_lower = question.lower()
    checklist = []
    for item in SAFETY_TRIGGERS:
        if any(kw in q_lower for kw in item["keywords"]):
            checklist.extend(item["checklist"])
    return list(dict.fromkeys(checklist))

def search_chunks(question: str, top_k: int = 5) -> List[Dict[str, Any]]:
    exact_matches = []
    
    # 1. Exact match for error codes (e.g. 'E-12', 'ERR-01')
    code_match = re.findall(r'\b[A-Za-z]{1,4}[-_\s]?\d{1,4}\b', question)
    if code_match:
        for code in code_match:
            clean_code = code.strip()
            try:
                res = supabase.table("manual_chunks").select("*").ilike("content", f"%{clean_code}%").limit(2).execute()
                if res.data:
                    exact_matches.extend(res.data)
            except Exception as e:
                print(f"[Warning] Error querying manual_chunks table: {e}")

    # 2. Vector embedding retrieval
    vector_matches = []
    try:
        vector = get_embedding(question)
        rpc_res = supabase.rpc("match_manual_chunks", {
            "query_embedding": vector,
            "match_count": top_k
        }).execute()
        vector_matches = rpc_res.data or []
    except Exception as e:
        print(f"[Warning] match_manual_chunks RPC not yet available in Supabase: {e}")

    # Filter by cutoff distance
    valid_vector_matches = [
        item for item in vector_matches 
        if item.get("distance", 0.0) <= SIMILARITY_DISTANCE_CUTOFF
    ]

    seen_ids = set()
    combined = []
    for chunk in (exact_matches + valid_vector_matches):
        c_id = chunk.get("id")
        if c_id not in seen_ids:
            seen_ids.add(c_id)
            combined.append(chunk)

    return combined
def ask(
    question: str, 
    machine_id: Optional[str] = "Compressor #01", 
    repair_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    safety_items = safety_check(question)
    chunks = search_chunks(question)

    if not chunks:
        not_found_obj = QueryResponse(
            status="NOT_FOUND",
            problem_type="unknown",
            summary="This issue or error code was not found in the verified manual.",
            safety_checklist=safety_items,
            steps=[],
            sources=[],
            escalate_to_engineer=True
        )
        return not_found_obj.model_dump()

    context_text = "\n\n".join([
        f"[Manual: {c.get('manual_title', 'Compressor Manual')} | Page: {c.get('page_number', 1)} | Section: {c.get('section', '')}]\n{c.get('content')}"
        for c in chunks
    ])

    history_text = "No prior repair history recorded for this machine."
    if repair_history:
        history_text = "\n".join([
            f"- Past Date: {h.get('date')} | Issue: {h.get('problem')} | Resolution: {h.get('action')}"
            for h in repair_history
        ])

    prompt = f"""
You are an expert industrial technician assistant for industrial air compressors.
Answer the technician's question STRICTLY using the context below. Do NOT invent steps.

Technician Question: "{question}"
Target Machine: {machine_id}

PAST REPAIR HISTORY FOR THIS MACHINE:
{history_text}

VERIFIED MANUAL CHUNKS:
{context_text}

OUTPUT RULES:
- Output valid JSON adhering to the specified schema.
- If the chunks do not contain a solution, return status="NOT_FOUND", empty steps list [], and escalate_to_engineer=true.
- Break fixes into short, clear, numbered steps. Each step must have a yes/no verification question.
- Cite the manual and page accurately.
- Categorize problem_type into one of: ['overheating', 'low pressure', 'oil leak', 'electrical', 'noise', 'belt', 'general'].
- NEVER return null for lists; use empty [] instead.
"""

    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_schema=QueryResponse,
            temperature=0.1
        )
    )

    try:
        parsed_data = json.loads(response.text)
        if safety_items:
            existing = parsed_data.get("safety_checklist", [])
            parsed_data["safety_checklist"] = list(dict.fromkeys(existing + safety_items))
        return parsed_data
    except Exception as e:
        return QueryResponse(
            status="NOT_FOUND",
            summary=f"Failed to parse AI response: {str(e)}",
            steps=[],
            sources=[],
            escalate_to_engineer=True
        ).model_dump()

def diagnose_photo(image_bytes: bytes, mime_type: str = "image/jpeg") -> Dict[str, Any]:
    image_part = types.Part.from_bytes(data=image_bytes, mime_type=mime_type)
    prompt = """
Examine this industrial air compressor photograph.
Identify visible components, warning lights, gauge readouts, leaks, or mechanical wear.
Return JSON with:
{
  "observed_condition": "Brief 1-sentence description of what is visible",
  "suggested_query": "A targeted question to look up in the troubleshooting manual",
  "detected_problem_type": "oil leak | overheating | low pressure | electrical | noise | belt | other"
}
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=[image_part, prompt],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            temperature=0.1
        )
    )
    return json.loads(response.text)

def check_step_reply(spoken_reply: str, step_question: str) -> str:
    prompt = f"""
Step question: "{step_question}"
Technician spoken answer: "{spoken_reply}"

Classify the answer into exactly one of these lowercase words:
- "yes" (if affirmative, completed, or normal)
- "no" (if failed, not completed, or abnormal)
- "unclear" (if ambiguous, requesting clarification, or not a clear yes/no)

Return ONLY the single word.
"""
    response = client.models.generate_content(
        model="gemini-2.5-flash",
        contents=prompt,
        config=types.GenerateContentConfig(temperature=0.0)
    )
    res = response.text.strip().lower()
    if "yes" in res:
        return "yes"
    if "no" in res:
        return "no"
    return "unclear"