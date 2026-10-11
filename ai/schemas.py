from pydantic import BaseModel, Field
from typing import List, Optional


class StepItem(BaseModel):
    step_no: int
    instruction: str
    check_question: str


class SourceReference(BaseModel):
    manual: str
    page: int


class QueryResponse(BaseModel):
    status: str = Field(description="'OK' or 'NOT_FOUND'")
    problem_type: Optional[str] = "other"
    summary: str
    is_dangerous: bool = False
    safety_checklist: List[str] = Field(default_factory=list)
    history_note: str = ""
    steps: List[StepItem] = Field(default_factory=list)
    sources: List[SourceReference] = Field(default_factory=list)
    escalate: bool = False
