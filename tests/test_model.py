import pytest
from model import get_llm, LLMProvider, score

def test_llm_provider_switching():
    ollama_llm = get_llm(LLMProvider.OLLAMA)
    groq_llm = get_llm(LLMProvider.GROQ)
    assert ollama_llm != groq_llm

def test_score_calculation():
    llm = get_llm(LLMProvider.GROQ)
    result = score(
        llm=llm,
        student_ans="Photosynthesis is the process where plants convert sunlight into energy.",
        expected_ans="Photosynthesis is the process by which plants convert light energy into chemical energy to produce glucose using carbon dioxide and water.",
        total_score=10
    )
    parsed_result = eval(result)
    assert isinstance(parsed_result["score"], int)
    assert isinstance(parsed_result["reason"], str)
    assert 0 <= parsed_result["score"] <= 10

def test_invalid_inputs():
    llm = get_llm(LLMProvider.GROQ)
    with pytest.raises(ValueError):
        score(
            llm=llm,
            student_ans="",
            expected_ans="",
            total_score=-1
        )
