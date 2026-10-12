import os
import re
import json
from typing import List, Dict, Any, Optional
from dotenv import load_dotenv
from google import genai
from google.genai import types
from supabase import create_client, Client

try:
    from ai.schemas import QueryResponse, StepItem, SourceReference
except ModuleNotFoundError:
    from schemas import QueryResponse, StepItem, SourceReference

load_dotenv()

client = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
supabase: Client = create_client(
    os.getenv("SUPABASE_URL", ""),
    os.getenv("SUPABASE_KEY", "")
)

SAFETY_TRIGGERS = [
    {
        # S1: opening panels / covers while energised
        "keywords": [
            "open panel", "remove cover", "open door", "open cover",
            "open the panel", "remove the cover", "open the door",
            "electrical cubicle", "control panel",
        ],
        "checklist": [
            "Perform Lockout/Tagout (LOTO) before opening any panel or cover.",
            "Verify zero electrical energy with a calibrated multimeter.",
            "Wear insulated rubber gloves and eye protection."
        ]
    },
    {
        # S2: pressurised fittings / drain / valve work
        "keywords": [
            "electrical", "wiring", "high voltage", "capacitor", "shock", "motor terminal",
            "burning smell", "sparks", "spark", "trip", "tripped",
        ],
        "checklist": [
            "Perform Lockout/Tagout (LOTO) on the main breaker.",
            "Verify zero electrical energy with a calibrated multimeter.",
            "Wear insulated rubber gloves and eye protection."
        ]
    },
    {
        # S2: pressurised fittings / drain / valve work
        "keywords": [
            "high pressure", "receiver tank", "blowdown", "pressure relief", "burst",
            "loosen", "disconnect", "pressure line", "safety valve", "drain condensate",
            "drain valve", "loosen a hose", "loosen a fitting",
        ],
        "checklist": [
            "Turn off the unit and vent all air until pressure gauge reads 0 PSI.",
            "Do not loosen any fitting or hose under active pressure.",
            "Wear safety goggles and ear protection."
        ]
    },
    {
        # S3: rotating machinery
        "keywords": ["belt", "pulley", "flywheel", "rotating", "fan blade"],
        "checklist": [
            "Power down and tag out machine.",
            "Ensure drive pulleys have completely stopped rotating.",
            "Do not place fingers between belt and pulley groove."
        ]
    },
    {
        # S4: hot surfaces / hot oil
        "keywords": [
            "hot", "overheat", "overheating", "oil change", "drain oil",
            "very hot", "getting hot", "hot surface", "burn", "scald",
        ],
        "checklist": [
            "Allow the machine to cool completely before touching hot surfaces.",
            "Wear heat-resistant gloves when handling hot oil or components.",
            "Do not drain oil while the machine is hot or pressurised."
        ]
    },
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
    code_match = re.findall(r'\b[A-Za-z]{1,4}[-_\s]?\d{1,4}\b', question)
    if code_match:
        for code in code_match:
            clean_code = code.strip()
            try:
                res = supabase.table("manual_chunks").select("*").ilike("content", f"%{clean_code}%").limit(2).execute()
                if res.data:
                    for row in res.data:
                        row["distance"] = 0.0
                    exact_matches.extend(res.data)
            except Exception as e:
                print(f"[Warning] Error querying manual_chunks table: {e}")

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
    machine_id: Optional[str] = "compressor-01",
    repair_history: Optional[List[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    safety_items = safety_check(question)
    chunks = search_chunks(question)

    top_distance = None
    if chunks:
        distances = [c.get("distance", 0.0) for c in chunks if c.get("distance") is not None]
        top_distance = min(distances) if distances else 0.0

    if not chunks:
        not_found_obj = QueryResponse(
            status="NOT_FOUND",
            problem_type="other",
            summary="This issue or error code was not found in the verified manual.",
            is_dangerous=bool(safety_items),
            safety_checklist=safety_items,
            history_note="",
            steps=[],
            sources=[],
            escalate=True,
            search_score=top_distance
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
- If the chunks do not contain a solution, return status="NOT_FOUND", empty steps list [], and escalate=true.
- Break fixes into short, clear, numbered steps. Each step must have a yes/no verification question.
- Cite the manual and page accurately.
- Categorize problem_type into one of: ['overheating', 'low_pressure', 'oil_leak', 'electrical', 'noise', 'belt', 'other']. Default to 'other'.
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
        parsed_data["search_score"] = top_distance
        parsed_data.setdefault("history_note", "")
        if safety_items:
            existing = parsed_data.get("safety_checklist", [])
            parsed_data["safety_checklist"] = list(dict.fromkeys(existing + safety_items))
            parsed_data["is_dangerous"] = True
            # If safety items were triggered, change status to SAFETY_ALERT
            if parsed_data.get("status") == "SUCCESS":
                parsed_data["status"] = "SAFETY_ALERT"
        else:
            parsed_data.setdefault("is_dangerous", False)
        return parsed_data
    except Exception as e:
        return QueryResponse(
            status="NOT_FOUND",
            summary=f"Failed to parse AI response: {str(e)}",
            is_dangerous=bool(safety_items),
            history_note="",
            steps=[],
            sources=[],
            escalate=True,
            search_score=top_distance
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
    # 1. Fast local keyword fallback (bulletproof for demos if rate-limited)
    low = spoken_reply.lower().strip()
    affirmative = ["yes", "yeah", "yup", "done", "checked", "fine", "ok", "okay", "good", "completed", "looks good"]
    negative = ["no", "nope", "not yet", "failed", "broken", "issue", "problem", "leaking", "stuck"]
    
    if any(re.search(rf"\b{word}\b", low) for word in affirmative):
        return "yes"
    if any(re.search(rf"\b{word}\b", low) for word in negative):
        return "no"

    # 2. Gemini classification for nuanced voice replies
    try:
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
    except Exception as e:
        print(f"[Warning] Rate limit or API error in check_step_reply: {e}")
        return "unclear"