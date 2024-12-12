import json
from model import LLMProvider
from utils.logger import log_evaluation


def print_api_result(test_name, response):
    print(f"\n=== {test_name} API Response ===")
    print(f"Status Code: {response.status_code}")
    print("Response Data:")
    print(json.dumps(response.json(), indent=2))
    print("=" * 50)


def test_switch_to_groq(client):
    response = client.post(
        "/set-provider",
        json={"provider": "groq"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully switched to groq"


def test_switch_to_ollama(client):
    response = client.post(
        "/set-provider",
        json={"provider": "ollama"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully switched to ollama"


def test_invalid_provider(client):
    response = client.post(
        "/set-provider",
        json={"provider": "invalid"}
    )
    assert response.status_code == 200
    assert "error" in response.json()


def test_scoring_endpoint(client, sample_answer):
    response = client.post(
        "/score",
        json=sample_answer
    )
    result = response.json()
    log_evaluation(
        "API Scoring Endpoint",
        {"request": sample_answer, "status_code": response.status_code},
        result
    )
    print_api_result("Scoring Endpoint", response)
    assert response.status_code == 200

    result = response.json()
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], int)
    assert isinstance(result["reason"], str)
    assert 0 <= result["score"] <= sample_answer["total_score"]


def test_scoring_empty_answer(client, sample_answer):
    sample_answer["student_ans"] = ""
    response = client.post(
        "/score",
        json=sample_answer
    )
    result = response.json()
    log_evaluation(
        "API Empty Answer",
        {"request": sample_answer, "status_code": response.status_code},
        result
    )
    print_api_result("Empty Answer", response)
    assert response.status_code == 200
    result = response.json()
    assert result["score"] == 0
    assert isinstance(result["reason"], str)


def test_scoring_with_question(client, sample_answer):
    sample_answer["question"] = "Explain the process of photosynthesis."
    response = client.post(
        "/score",
        json=sample_answer
    )
    print_api_result("Score With Question", response)
    assert response.status_code == 200

    result = response.json()
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], int)
    assert isinstance(result["reason"], str)


def test_scoring_without_question(client, sample_answer):
    if "question" in sample_answer:
        del sample_answer["question"]
    response = client.post(
        "/score",
        json=sample_answer
    )
    assert response.status_code == 200

    result = response.json()
    assert "score" in result
    assert "reason" in result
