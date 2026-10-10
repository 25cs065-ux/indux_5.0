from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(
    title="Indux Assistant API",
    description="Backend for the Industrial Maintenance Assistant",
    version="1.0.0"
)

# Allow the worker app to communicate with the backend.
# Credentials remain disabled as required by the project workflow.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {
        "message": "Indux Assistant Backend is running!"
    }


@app.get("/health")
def health_check():
    return {
        "status": "ok"
    }
    from pydantic import BaseModel


class AskRequest(BaseModel):
    question: str
    machine_id: str = "compressor_01"


@app.post("/ask")
def ask_question(request: AskRequest):
    return {
        "status": "success",
        "machine_id": request.machine_id,
        "question": request.question,
        "answer": {
            "status": "ANSWER_FOUND",
            "steps": [
                {
                    "step": 1,
                    "instruction": "Check whether the air intake filter is blocked.",
                    "check_question": "Is the air intake filter blocked?"
                },
                {
                    "step": 2,
                    "instruction": "Check whether the cooling vents are obstructed.",
                    "check_question": "Are the cooling vents clear?"
                }
            ],
            "source": {
                "manual": "Sample Compressor Manual",
                "page": 5
            }
        },
        "is_demo": True
    }