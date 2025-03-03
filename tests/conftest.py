import logging
import sys
from datetime import datetime
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

import pytest
from httpx import AsyncClient
import subprocess
from app.api.scoring.service import get_llm, LLMProvider
from .fixtures import mock_questions, mock_responses, mock_evaluation_settings

# Create logs directory if it doesn't exist
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)


def pytest_configure(config):
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(
                log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.log"
            ),
            logging.StreamHandler(sys.stdout),
        ],
    )


@pytest.fixture(scope="session")
def llm():
    """Provide a configured LLM instance for tests"""
    return get_llm(
        provider=LLMProvider.GROQ,
        model_name="llama-3.3-70b-specdec",  # Default model
        api_key=None,  # Will use environment variable
    )


@pytest.fixture
def mock_quiz_questions():
    """Provide mock quiz questions for testing"""
    return mock_questions


@pytest.fixture
def mock_quiz_responses():
    """Provide mock quiz responses for testing"""
    return mock_responses


@pytest.fixture
def mock_quiz_settings():
    """Provide mock evaluation settings for testing"""
    return mock_evaluation_settings


@pytest.fixture(scope="session", autouse=True)
def start_server():
    # Start the FastAPI server
    process = subprocess.Popen(
        ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "4040"]
    )
    import requests
    import time

    timeout = 30
    start_time = time.time()
    while True:
        try:
            response = requests.get("http://localhost:4040")
            if response.status_code == 200:
                break
        except requests.ConnectionError:
            pass
        if time.time() - start_time > timeout:
            raise RuntimeError("Server did not start within the timeout period")
        time.sleep(1)
    yield
    process.terminate()  # Terminate the server after tests are done


@pytest.fixture
async def client():
    async with AsyncClient(base_url="http://localhost:4040") as ac:
        yield ac


@pytest.fixture
def sample_answer():
    return {
        "question": "What is photosynthesis?",
        "guidelines": "Focus on: 1) Basic concept 2) Energy conversion 3) Raw materials needed",
        "student_ans": "Photosynthesis is the process where plants convert sunlight into energy.",
        "expected_ans": "Photosynthesis is the process by which plants convert light energy into chemical energy to produce glucose using carbon dioxide and water.",
        "total_score": 10,
    }
