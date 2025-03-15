from pydantic import BaseModel
from typing import Optional, Dict, List


class EvalRequest(BaseModel):
    quiz_id: str
    override_evaluated: bool = False
    override_locked: bool = False
    override_cache: bool = True
    types_to_evaluate: Optional[Dict[str, bool]] = {
        "MCQ": True,
        "DESCRIPTIVE": True,
        "CODING": True,
        "TRUE_FALSE": True,
        "FILL_IN_BLANK": True,
    }


class ReEvalRequest(EvalRequest):
    student_ids: List[str]
    # question_ids : List[str] # Also make above optional
