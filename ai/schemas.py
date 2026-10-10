from pydantic import BaseModel, Field
from typing import List, Optional

class StepItem(BaseModel):
    step_number: int
    instruction: str
    check_question: str

class SourceReference(BaseModel):
    manual_title: str
    page_number: int
    section: Optional[str] = ""

class QueryResponse(BaseModel):
    status: str = Field(description="'SUCCESS', 'NOT_FOUND', or 'SAFETY_ALERT'")
    problem_type: Optional[str] = "general"
    summary: str
    safety_checklist: List[str] = Field(default_factory=list)
    steps: List[StepItem] = Field(default_factory=list)
    sources: List[SourceReference] = Field(default_factory=list)
    escalate_to_engineer: bool = False