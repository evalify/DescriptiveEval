from fastapi import FastAPI, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from typing import Optional
from model import LLMProvider, get_llm, score, generate_guidelines, enhance_question_and_answer
from evaluation import bulk_evaluate_quiz_responses
from database import get_postgres_cursor, get_mongo_client, get_redis_client

app = FastAPI()
# Store current provider in app state
app.state.current_provider = LLMProvider.GROQ

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Consider restricting origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class QueryRequest(BaseModel):
    question: Optional[str] = None
    student_ans: str
    expected_ans: str
    total_score: int
    guidelines: Optional[str] = None  # Added guidelines field


class ProviderRequest(BaseModel):
    provider: str


class GuidelinesRequest(BaseModel):
    question: Optional[str] = None
    expected_ans: Optional[str] = None
    total_score: Optional[int] = 10


class QAEnhancementRequest(BaseModel):
    question: str
    expected_ans: str


class BulkEvalRequest(BaseModel):
    quiz_id: str


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


def get_llm_dependency():
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(provider=app.state.current_provider)

@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())    #TODO: Add model_name and api_key support
        # Update the app state
        app.state.current_provider = provider
        return {"message": f"Successfully switched to {provider.value}"}
    except ValueError as e:
        return {"error": str(e)}

@app.post("/score")
async def get_response(
    request: QueryRequest,
    llm = Depends(get_llm_dependency)
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
    llm = Depends(get_llm_dependency)
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
    llm = Depends(get_llm_dependency)
):
    result = await enhance_question_and_answer(
        llm,
        question=request.question,
        expected_ans=request.expected_ans
    )
    return result


@app.post("/evaluate") #TODO: Implement Queueing
async def evaluate_bulk(
    request: BulkEvalRequest,
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
            save_to_file=True
        )
        return {"message": "Evaluation complete", "results": results} #TODO: Give more detailed response
    finally:
        postgres_cursor.close()
        postgres_conn.close()


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4040)
