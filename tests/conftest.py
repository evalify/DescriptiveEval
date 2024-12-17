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


@pytest.fixture
async def client():
    async with AsyncClient(app=app, base_url="http://test") as ac:
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
