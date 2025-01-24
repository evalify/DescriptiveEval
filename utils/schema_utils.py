from typing import Any, Dict, Optional
from functools import partial

class QuizResponseSchema:
    VALID_ATTRIBUTES = {
        'student_answer',
        'score',
        'remarks',
        'breakdown'
    }

    @staticmethod
    def get_student_answer(response_data: Dict[str, Any], question_id: str) -> Any:
        return response_data.get("responses", {}).get(question_id, {}).get("student_answer")

    @staticmethod
    def get_score(response_data: Dict[str, Any], question_id: str) -> Optional[float]:
        return response_data.get("responses", {}).get(question_id, {}).get("score")

    @staticmethod
    def get_remarks(response_data: Dict[str, Any], question_id: str) -> str:
        return response_data.get("responses", {}).get(question_id, {}).get("remarks", "")

    @staticmethod
    def get_breakdown(response_data: Dict[str, Any], question_id: str) -> str:
        return response_data.get("responses", {}).get(question_id, {}).get("breakdown", "")

    @staticmethod
    def set_student_answer(response_data: Dict[str, Any], question_id: str, value: Any) -> None:
        if "responses" not in response_data:
            response_data["responses"] = {}
        if question_id not in response_data["responses"]:
            response_data["responses"][question_id] = {}
        response_data["responses"][question_id]["student_answer"] = value

    @staticmethod
    def set_score(response_data: Dict[str, Any], question_id: str, value: float) -> None:
        if "responses" not in response_data:
            response_data["responses"] = {}
        if question_id not in response_data["responses"]:
            response_data["responses"][question_id] = {}
        response_data["responses"][question_id]["score"] = value

    @staticmethod
    def set_remarks(response_data: Dict[str, Any], question_id: str, value: str) -> None:
        if "responses" not in response_data:
            response_data["responses"] = {}
        if question_id not in response_data["responses"]:
            response_data["responses"][question_id] = {}
        response_data["responses"][question_id]["remarks"] = value

    @staticmethod
    def set_breakdown(response_data: Dict[str, Any], question_id: str, value: str) -> None:
        if "responses" not in response_data:
            response_data["responses"] = {}
        if question_id not in response_data["responses"]:
            response_data["responses"][question_id] = {}
        response_data["responses"][question_id]["breakdown"] = value

    @classmethod
    def get_attribute(cls, response_data: Dict[str, Any], question_id: str, attribute: str) -> Any:
        """Router function for getting attributes"""
        if attribute not in cls.VALID_ATTRIBUTES:
            raise ValueError(f"Invalid attribute: {attribute}")
        
        getter_map = {
            'student_answer': cls.get_student_answer,
            'score': cls.get_score,
            'remarks': cls.get_remarks,
            'breakdown': cls.get_breakdown
        }
        return getter_map[attribute](response_data, question_id)

    @classmethod
    def set_attribute(cls, response_data: Dict[str, Any], question_id: str, attribute: str, value: Any) -> None:
        """Router function for setting attributes"""
        if attribute not in cls.VALID_ATTRIBUTES:
            raise ValueError(f"Invalid attribute: {attribute}")
        
        setter_map = {
            'student_answer': cls.set_student_answer,
            'score': cls.set_score,
            'remarks': cls.set_remarks,
            'breakdown': cls.set_breakdown
        }
        setter_map[attribute](response_data, question_id, value)