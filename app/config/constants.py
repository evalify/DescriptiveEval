import os
from dotenv import load_dotenv

load_dotenv()

# -------------------------------
# Evaluation Constants
# -------------------------------

CACHE_EX = int(os.getenv("CACHE_EX", 3600))  # Cache expiry time in seconds
MAX_RETRIES = int(
    os.getenv("MAX_RETRIES", 10)
)  # Maximum number of retries for LLM evaluation

# Maximum Timeout => max(n * EVAL_TIME, BATCH_TIMEOUT)
DESC_EVAL_TIME = float(os.getenv("DESC_EVAL_TIME", 20))
FITB_EVAL_TIME = float(os.getenv("FITB_EVAL_TIME", 20))

# Batch Size Controls
MAX_BATCH_SIZE = int(
    os.getenv("MAX_BATCH_SIZE", 200)
)  # Max number of students per batch

# For Batching student responses
DYNAMIC_BATCH_SIZE: bool = os.getenv("DYNAMIC_BATCH_SIZE", "False") == "True"

# Follows this if DYNAMIC_BATCH_SIZE is True
MAX_PARALLEL_LLM_REQUESTS_PER_QUIZ = int(
    os.getenv("MAX_PARALLEL_LLM_REQUESTS_PER_QUIZ", 25)
)

# Follows this if DYNAMIC_BATCH_SIZE is False
EVAL_BATCH_SIZE = int(os.getenv("EVAL_BATCH_SIZE", 5))


BATCH_TIMEOUT = int(os.getenv("BATCH_TIMEOUT", 300))  # 5 minutes timeout per batch
EVAL_MAX_RETRIES = int(os.getenv("EVAL_MAX_RETRIES", 10))

WORKER_TTL = int(os.getenv("WORKER_TTL", "3600"))
DB_MAX_RETRIES = int(os.getenv("DB_MAX_RETRIES", 3))

# Coding Questions
JUDGE_URL = os.getenv("JUDGE_API")
JUDGE_LANGUAGE_MAP = {
    "python": 71,
    "octave": 66,
    "java": 62,
}


# -------------------------------
# Provider Constants
# -------------------------------

VLLM_HOST = os.getenv("VLLM_HOST", "http://localhost:8000")
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")
GROQ_API_KEY = os.getenv("GROQ_API_KEY")

LLM_TEMP = float(os.getenv("LLM_TEMP", 0.2))


# -------------------------------
# Database Constants
# -------------------------------

MONGODB_URI = os.getenv("MONGODB_URI")
COCKROACH_DB = os.getenv("COCKROACH_DB")

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", 6379))
REDIS_DB = int(os.getenv("REDIS_DB", 2))
# -------------------------------
# Worker Constants
# -------------------------------

WORKER_COUNT = int(os.getenv("WORKER_COUNT", "4"))
