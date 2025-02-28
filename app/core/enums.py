from enum import Enum

class LLMProvider(Enum):
    OLLAMA = "ollama"
    GROQ = "groq"
    VLLM = "vllm"


class EvaluationStatus(Enum):
    SUCCESS = 200  # Successful evaluation
    INVALID_INPUT = 400  # Invalid input parameters
    EMPTY_ANSWER = 422  # Empty or missing student answer
    LLM_ERROR = 500  # LLM processing error
    PARSE_ERROR = 502  # Response parsing error
