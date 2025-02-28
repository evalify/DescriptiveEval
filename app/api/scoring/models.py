from typing import Optional
from pydantic import BaseModel


class QueryRequest(BaseModel):
    question: str = None
    student_ans: str
    expected_ans: str
    total_score: int
    guidelines: Optional[str] = None


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
