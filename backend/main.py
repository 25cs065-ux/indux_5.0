
import os

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

from ai.brain import ask as ai_ask, diagnose_photo as ai_diagnose_photo

# ---------- Supabase ----------
supabase_url = os.getenv("SUPABASE_URL")
supabase_key = os.getenv("SUPABASE_KEY")

if not supabase_url or not supabase_key:
    raise RuntimeError("Supabase environment variables are missing.")

supabase: Client = create_client(supabase_url, supabase_key)

# ---------- FastAPI ----------
app = FastAPI(
    title="Indux Assistant API",
    description="Backend for the Industrial Maintenance Assistant",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AskRequest(BaseModel):
    question: str
    machine_id: str = "compressor_01"


class RepairRequest(BaseModel):
    machine_id: str
    problem: str
    action: str
    outcome: str = ""


class VoiceAskRequest(BaseModel):
    transcript: str
    machine_id: str = "compressor_01"


@app.get("/")
def home():
    return {"message": "Indux Assistant Backend is running!"}


@app.get("/health")
def health_check():
    return {"status": "ok"}


@app.post("/ask")
def ask_question(request: AskRequest):
    try:
        history_result = (
            supabase.table("repair_history")
            .select("created_at, problem, action, outcome")
            .eq("machine_id", request.machine_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )

        repair_history = [
            {
                "date": item["created_at"],
                "problem": item["problem"],
                "action": item["action"],
                "outcome": item["outcome"]
            }
            for item in (history_result.data or [])
        ]

        result = ai_ask(
            question=request.question,
            machine_id=request.machine_id,
            repair_history=repair_history
        )

        return {
            "status": "success",
            "machine_id": request.machine_id,
            "question": request.question,
            "answer": result,
            "is_demo": False
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="The AI or database service is temporarily unavailable."
        )


@app.post("/voice-ask")
def voice_ask(request: VoiceAskRequest):
    transcript = request.transcript.strip()
    if not transcript:
        raise HTTPException(
            status_code=422,
            detail="transcript must not be empty."
        )
    # Reuse the identical ask logic: fetch repair history then call ai_ask.
    try:
        history_result = (
            supabase.table("repair_history")
            .select("created_at, problem, action, outcome")
            .eq("machine_id", request.machine_id)
            .order("created_at", desc=True)
            .limit(5)
            .execute()
        )

        repair_history = [
            {
                "date": item["created_at"],
                "problem": item["problem"],
                "action": item["action"],
                "outcome": item["outcome"]
            }
            for item in (history_result.data or [])
        ]

        result = ai_ask(
            question=transcript,
            machine_id=request.machine_id,
            repair_history=repair_history
        )

        return {
            "status": "success",
            "machine_id": request.machine_id,
            "question": transcript,
            "answer": result,
            "is_demo": False
        }
    except HTTPException:
        raise
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="The AI or database service is temporarily unavailable."
        )


@app.post("/history")
def save_repair(request: RepairRequest):
    try:
        result = (
            supabase.table("repair_history")
            .insert(request.model_dump())
            .execute()
        )

        return {
            "status": "success",
            "repair": result.data[0]
        }

    except Exception as e:
        print("Repair save error:", type(e).__name__, str(e))

        raise HTTPException(
            status_code=503,
            detail="Could not save the repair record. Check backend terminal."
        )

# Accepted MIME types and their magic-byte signatures for photo uploads.
_ALLOWED_IMAGE_TYPES: dict[bytes, str] = {
    b"\xff\xd8\xff": "image/jpeg",
    b"\x89PNG":      "image/png",
}
_MAX_IMAGE_BYTES = 5 * 1024 * 1024   # 5 MB


@app.post("/diagnose-photo")
async def diagnose_photo_endpoint(image: UploadFile = File(...)):
    """
    Accept a JPEG or PNG photograph and return Gemini's visual diagnosis.

    Response:
        {
          "status": "success",
          "observed_condition": "...",
          "suggested_query":    "...",
          "detected_problem_type": "..."
        }
    """
    # 1. Reject obviously wrong content-types early (browsers set this).
    content_type = (image.content_type or "").lower()
    if content_type and content_type not in ("image/jpeg", "image/png",
                                              "image/jpg", "application/octet-stream"):
        raise HTTPException(
            status_code=415,
            detail="Only JPEG and PNG images are accepted."
        )

    # 2. Read bytes (capped at limit + 1 to detect oversized files).
    image_bytes = await image.read(_MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise HTTPException(status_code=422, detail="Uploaded image is empty.")
    if len(image_bytes) > _MAX_IMAGE_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"Image exceeds the {_MAX_IMAGE_BYTES // (1024*1024)} MB limit."
        )

    # 3. Validate magic bytes — reject files that are not actually JPEG or PNG.
    mime_type: str | None = None
    for magic, mime in _ALLOWED_IMAGE_TYPES.items():
        if image_bytes.startswith(magic):
            mime_type = mime
            break
    if mime_type is None:
        raise HTTPException(
            status_code=415,
            detail="File does not appear to be a valid JPEG or PNG image."
        )

    # 4. Call the AI helper.
    try:
        result = ai_diagnose_photo(image_bytes, mime_type=mime_type)
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="The photo diagnosis service is temporarily unavailable."
        )

    return {
        "status": "success",
        "observed_condition":    result.get("observed_condition", ""),
        "suggested_query":       result.get("suggested_query", ""),
        "detected_problem_type": result.get("detected_problem_type", "other"),
    }


@app.get("/history/{machine_id}")
def get_repair_history(machine_id: str):
    try:
        result = (
            supabase.table("repair_history")
            .select("*")
            .eq("machine_id", machine_id)
            .order("created_at", desc=True)
            .limit(50)
            .execute()
        )
        return {
            "status": "success",
            "machine_id": machine_id,
            "history": result.data or []
        }
    except Exception:
        raise HTTPException(
            status_code=503,
            detail="Could not retrieve repair history."
        )
