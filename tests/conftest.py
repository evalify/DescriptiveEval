import sys
from pathlib import Path
import logging
from datetime import datetime

# Create logs directory if it doesn't exist
log_dir = Path(__file__).parent.parent / "logs"
log_dir.mkdir(exist_ok=True)


def pytest_configure(config):
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler(log_dir / f"eval_{datetime.now().strftime('%Y%m%d')}.log"),
            logging.StreamHandler(sys.stdout)
        ]
    )


sys.path.append(str(Path(__file__).parent.parent))

import pytest
from httpx import AsyncClient
from app import app
import subprocess


@pytest.fixture(scope="session", autouse=True)
def start_server():
    # Start the FastAPI server
    process = subprocess.Popen(["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "4040"])
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
        "total_score": 10
    }
