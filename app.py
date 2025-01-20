from fastapi import FastAPI, Depends
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from model import LLMProvider, get_llm, score, generate_guidelines, enhance_question_and_answer
from typing import Optional

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


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


def get_llm_dependency():
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(provider=app.state.current_provider)

@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())
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


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8020)
