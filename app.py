from typing import Optional

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from utils.database import get_postgres_cursor, get_mongo_client, get_redis_client
from evaluation import bulk_evaluate_quiz_responses
from model import LLMProvider, get_llm, score, generate_guidelines, enhance_question_and_answer

app = FastAPI()
# Store current provider in app state
app.state.current_provider = LLMProvider.OLLAMA
app.state.current_model_name = "deepseek-r1:70b"
app.state.current_api_key = None

app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Consider restricting origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: str = None
    student_ans: str
    expected_ans: str
    total_score: int
    guidelines: Optional[str] = None  # Added guidelines field


class ProviderRequest(BaseModel):
    provider: str
    provider_model_name: str = None
    provider_api_key: str = None


class GuidelinesRequest(BaseModel):
    question: str = None
    expected_ans: str = None
    total_score: int = 10


class QAEnhancementRequest(BaseModel):
    question: str
    expected_ans: str


class EvalRequest(BaseModel):
    quiz_id: str


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


def get_llm_dependency():
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(provider=app.state.current_provider, model_name=app.state.current_model_name, api_key=app.state.current_api_key)


@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())
        provider_model_name = request.provider_model_name
        provider_api_key = request.provider_api_key
        # Update the app state
        app.state.current_provider = provider
        app.state.current_model_name = provider_model_name
        app.state.current_api_key = provider_api_key

        return {"message": f"Successfully switched to {provider.value} provider with model {provider_model_name}"}
    except ValueError as e:
        return {"error": str(e)}


@app.post("/score")
async def get_response(
        request: QueryRequest,
        llm=Depends(get_llm_dependency)
):
    result = await score(
        llm=llm,
        student_ans=request.student_ans,
        expected_ans=request.expected_ans,
        total_score=request.total_score,
        question=request.question,
        guidelines=request.guidelines  # Pass guidelines if provided
    )
    return result


@app.post("/generate-guidelines")
async def generate_guidelines_api(
        request: GuidelinesRequest,
        llm=Depends(get_llm_dependency)
):
    guidelines_result = await generate_guidelines(
        llm,
        question=request.question or "",
        expected_ans=request.expected_ans or "",
        total_score=request.total_score or 10
    )
    return guidelines_result


@app.post("/enhance-qa")
async def enhance_qa(
        request: QAEnhancementRequest,
        llm=Depends(get_llm_dependency)
):
    result = await enhance_question_and_answer(
        llm,
        question=request.question,
        expected_ans=request.expected_ans
    )
    return result


@app.post("/evaluate")  # TODO: Implement Queueing
async def evaluate_bulk(
        request: EvalRequest,
        llm=Depends(get_llm_dependency)
):
    postgres_cursor, postgres_conn = get_postgres_cursor()
    mongo_db = get_mongo_client()
    redis_client = get_redis_client()
    try:
        results = await bulk_evaluate_quiz_responses(
            request.quiz_id,
            postgres_cursor,
            postgres_conn,
            mongo_db,
            redis_client,
            save_to_file=True,
            llm = llm
        )
        return {"message": "Evaluation complete", "results": results}  # TODO: Give more detailed response
    finally:
        postgres_cursor.close()
        postgres_conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4040)
