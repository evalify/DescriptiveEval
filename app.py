from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from model import llm, LLMProvider, set_llm_provider, score, generate_guidelines, enhance_question_and_answer
from typing import Optional

app = FastAPI()

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


@app.post("/set-provider")
async def change_provider(request: ProviderRequest):  # TODO: Fix - Can't change provider
    try:
        provider = LLMProvider(request.provider.lower())
        set_llm_provider(provider)
        print(llm.__repr_name__())
        return {"message": f"Successfully switched to {provider.value}"}
    except ValueError as e:
        return {"error": str(e)}


@app.post("/score")
async def get_response(request: QueryRequest):
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
async def generate_guidelines_api(request: GuidelinesRequest):
    guidelines_result = await generate_guidelines(
        llm,
        question=request.question or "",
        expected_ans=request.expected_ans or "",
        total_score=request.total_score or 10
    )
    return guidelines_result


@app.post("/enhance-qa")
async def enhance_qa(request: QAEnhancementRequest):
    result = await enhance_question_and_answer(
        llm,
        question=request.question,
        expected_ans=request.expected_ans
    )
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8020)
