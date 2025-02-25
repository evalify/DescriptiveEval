from pydantic import BaseModel
from typing import Optional, Dict


class QueryRequest(BaseModel):
    question: str = None
    student_ans: str
    expected_ans: str
    total_score: int
    guidelines: Optional[str] = None  # Added guidelines field


class ProviderRequest(BaseModel):
    provider: str
    provider_model_name: str = None
    provider_api_key: str = None
    service: str = "macro"


class GuidelinesRequest(BaseModel):
    question: str = None
    expected_ans: str = None
    total_score: int = 10


class QAEnhancementRequest(BaseModel):
    question: str
    expected_ans: str


class EvalRequest(BaseModel):
    quiz_id: str
    override_evaluated: bool = False
    override_locked: bool = False
    override_cache: bool = False
    types_to_evaluate: Optional[Dict[str, bool]] = {
        "MCQ": True,
        "DESCRIPTIVE": True,
        "CODING": True,
        "TRUE_FALSE": True,
        "FILL_IN_BLANK": True,
    }