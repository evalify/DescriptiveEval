from pydantic import BaseModel
from typing import Optional, Dict, List
from pydantic import Field
from typing import Annotated


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
    override_evaluated: Annotated[
        bool, Field(default=False, exclude=True)
    ]  # This field is permanently set to False and excluded from the model
    # question_ids: Optional[List[str]] = None  # Also make above optional
