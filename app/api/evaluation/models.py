from pydantic import BaseModel
from typing import Optional, Dict, List
from pydantic import Field


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
    override_evaluated: Optional[bool] = Field(
        default=None, exclude=True
    )  # This field is excluded from the model
    # question_ids: Optional[List[str]] = None  # Also make above optional
