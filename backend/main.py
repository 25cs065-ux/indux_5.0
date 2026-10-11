
import os

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from supabase import create_client, Client

from ai.brain import ask as ai_ask

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
