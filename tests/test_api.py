import json
import pytest
from model import LLMProvider
from utils.logger import log_evaluation
from httpx import AsyncClient
from app import app
from httpx import AsyncClient
from app import app
import asyncio
import time


def print_api_result(test_name, response):
    print(f"\n=== {test_name} API Response ===")
    print(f"Status Code: {response.status_code}")
    print("Response Data:")
    print(json.dumps(response.json(), indent=2))
    print("=" * 50)


@pytest.mark.asyncio
async def test_switch_to_groq(client):
    response = await client.post(
        "/set-provider",
        json={"provider": "groq"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully switched to groq"


@pytest.mark.asyncio
async def test_switch_to_ollama(client):
    response = await client.post(
        "/set-provider",
        json={"provider": "ollama"}
    )
    assert response.status_code == 200
    assert response.json()["message"] == "Successfully switched to ollama"


@pytest.mark.asyncio
async def test_invalid_provider(client):
    response = await client.post(
        "/set-provider",
        json={"provider": "invalid"}
    )
    assert response.status_code == 200
    assert "error" in response.json()


@pytest.mark.asyncio
async def test_scoring_endpoint(client, sample_answer):
    response = await client.post(
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
    assert isinstance(result["score"], float)
    assert isinstance(result["reason"], str)
    assert 0 <= result["score"] <= sample_answer["total_score"]


@pytest.mark.asyncio
async def test_scoring_empty_answer(client, sample_answer):
    sample_answer["student_ans"] = ""
    response = await client.post(
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


@pytest.mark.asyncio
async def test_scoring_with_question(client, sample_answer):
    sample_answer["question"] = "Explain the process of photosynthesis."
    response = await client.post(
        "/score",
        json=sample_answer
    )
    print_api_result("Score With Question", response)
    assert response.status_code == 200

    result = response.json()
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], float)
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_scoring_without_question(client, sample_answer):
    if "question" in sample_answer:
        del sample_answer["question"]
    response = await client.post(
        "/score",
        json=sample_answer
    )
    assert response.status_code == 200

    result = response.json()
    assert "score" in result
    assert "reason" in result


@pytest.mark.asyncio
async def test_scoring_with_guidelines(client, sample_answer):
    sample_answer["guidelines"] = "Focus on technical accuracy and completeness"
    response = await client.post(
        "/score",
        json=sample_answer
    )
    result = response.json()
    log_evaluation(
        "API Scoring With Guidelines",
        {"request": sample_answer, "status_code": response.status_code},
        result
    )
    print_api_result("Score With Guidelines", response)
    assert response.status_code == 200
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], float)
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_scoring_with_empty_guidelines(client, sample_answer):
    sample_answer["guidelines"] = ""
    response = await client.post(
        "/score",
        json=sample_answer
    )
    result = response.json()
    log_evaluation(
        "API Scoring With Empty Guidelines",
        {"request": sample_answer, "status_code": response.status_code},
        result
    )
    print_api_result("Score With Empty Guidelines", response)
    assert response.status_code == 200
    assert "score" in result
    assert "reason" in result
    assert isinstance(result["score"], float)
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_concurrent_vs_sequential_scoring(client, sample_answer):
    # Prepare four different questions
    queries = [
        {
            **sample_answer,
            "question": "What is photosynthesis?",
            "expected_ans": "Photosynthesis is the process by which plants convert light energy into chemical energy to produce glucose using carbon dioxide and water."
        },
        {
            **sample_answer,
            "question": "What is cellular respiration?",
            "expected_ans": "Cellular respiration is the process by which cells break down glucose to produce ATP, using oxygen and releasing carbon dioxide and water."
        },
        {
            **sample_answer,
            "question": "What is mitosis?",
            "expected_ans": "Mitosis is a type of cell division where one cell divides into two identical daughter cells, each containing the same number of chromosomes as the parent cell."
        },
        {
            **sample_answer,
            "question": "What is meiosis?",
            "expected_ans": "Meiosis is a type of cell division that produces four daughter cells, each with half the number of chromosomes as the parent cell, essential for sexual reproduction."
        }
    ]
    
    # Test sequential execution
    start_time = time.time()
    sequential_responses = []
    for query in queries:
        response = await client.post("/score", json=query)
        sequential_responses.append(response)
    sequential_time = time.time() - start_time
    
    # Test concurrent execution
    start_time = time.time()
    concurrent_responses = await asyncio.gather(
        *[client.post("/score", json=query) for query in queries]
    )
    concurrent_time = time.time() - start_time
    
    # Log results
    performance_data = {
        "sequential_time": sequential_time,
        "concurrent_time": concurrent_time,
        "improvement": f"{(sequential_time - concurrent_time) / sequential_time * 100:.2f}%",
        "num_queries": len(queries)
    }
    
    log_evaluation("Performance Comparison", performance_data, {"status": "completed"})
    
    print(f"\n=== Performance Test Results ({len(queries)} queries) ===")
    print(f"Sequential Time: {sequential_time:.2f}s")
    print(f"Concurrent Time: {concurrent_time:.2f}s")
    print(f"Improvement: {(sequential_time - concurrent_time) / sequential_time * 100:.2f}%")
    print("=" * 50)
    
    # Verify all responses
    for response in sequential_responses + list(concurrent_responses):
        assert response.status_code == 200
        result = response.json()
        assert "score" in result
        assert "reason" in result
    
    # Verify concurrent execution was faster
    assert concurrent_time < sequential_time, "Concurrent execution should be faster than sequential"


@pytest.mark.asyncio
async def test_generate_guidelines_endpoint(client: AsyncClient):
    """Test the /generate-guidelines endpoint"""
    request_data = {
        "question": "Explain the process of photosynthesis.",
        "expected_ans": "Photosynthesis is the process by which plants convert light energy into chemical energy.",
        "total_score": 10
    }
    response = await client.post("/generate-guidelines", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "guidelines" in result


@pytest.mark.asyncio
async def test_enhance_qa_endpoint(client: AsyncClient):
    """Test the /enhance-qa endpoint"""
    request_data = {
        "question": "What is photosynthesis?",
        "expected_ans": "Process where plants make food"
    }
    response = await client.post("/enhance-qa", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "enhanced_question" in result
    assert "enhanced_expected_ans" in result


@pytest.mark.asyncio
async def test_evaluate_endpoint(client: AsyncClient):
    """Test the /evaluate endpoint for bulk evaluation"""
    request_data = {
        "quiz_id": "test_quiz_id"
    }
    response = await client.post("/evaluate", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "message" in result
    assert "results" in result


@pytest.mark.asyncio
async def test_invalid_quiz_id(client: AsyncClient):
    """Test bulk evaluation with invalid quiz ID"""
    request_data = {
        "quiz_id": "invalid_quiz_id"
    }
    response = await client.post("/evaluate", json=request_data)
    assert response.status_code == 200
    # Even with invalid quiz ID, the endpoint should return a valid response format
    result = response.json()
    assert "message" in result
    assert "results" in result


@pytest.mark.asyncio
async def test_empty_quiz(client: AsyncClient):
    """Test bulk evaluation with empty quiz"""
    request_data = {
        "quiz_id": ""
    }
    response = await client.post("/evaluate", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "message" in result
    assert "results" in result


@pytest.mark.asyncio
async def test_score_endpoint(client: AsyncClient):
    """Test the /score endpoint"""
    request_data = {
        "question": "Explain photosynthesis.",
        "student_ans": "Plants convert sunlight to energy.",
        "expected_ans": "Photosynthesis is the process where plants convert sunlight into chemical energy.",
        "total_score": 10,
        "guidelines": "Focus on accuracy and completeness."
    }
    response = await client.post("/score", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "score" in result
    assert "reason" in result
    assert "rubric" in result
    assert "breakdown" in result

@pytest.mark.asyncio
async def test_root_endpoint(client: AsyncClient):
    """Test the root endpoint"""
    response = await client.get("/")
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_score_invalid_input(client: AsyncClient):
    """Test the /score endpoint with invalid input"""
    request_data = {
        "student_ans": "",
        "expected_ans": "",
        "total_score": -1
    }
    response = await client.post("/score", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert result["score"] == 0
    assert isinstance(result["reason"], str)


@pytest.mark.asyncio
async def test_enhance_qa_empty_input(client: AsyncClient):
    """Test the /enhance-qa endpoint with empty input"""
    request_data = {
        "question": "",
        "expected_ans": ""
    }
    response = await client.post("/enhance-qa", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "enhanced_question" in result
    assert "enhanced_expected_ans" in result


@pytest.mark.asyncio
async def test_guidelines_empty_input(client: AsyncClient):
    """Test the /generate-guidelines endpoint with empty input"""
    request_data = {
        "question": "",
        "expected_ans": "",
        "total_score": 10
    }
    response = await client.post("/generate-guidelines", json=request_data)
    assert response.status_code == 200
    result = response.json()
    assert "guidelines" in result
