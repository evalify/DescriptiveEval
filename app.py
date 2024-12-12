from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from model import score, llm, LLMProvider, set_llm_provider
from typing import Optional

app = FastAPI()

# Mount static files directory
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Consider restricting origins in production
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


@app.get("/")
async def read_index():
    return FileResponse('static/index.html')


@app.post("/set-provider")
async def change_provider(request: ProviderRequest):
    try:
        provider = LLMProvider(request.provider.lower())
        set_llm_provider(provider)
        return {"message": f"Successfully switched to {provider.value}"}
    except ValueError as e:
        return {"error": str(e)}


@app.post("/score")
async def get_response(request: QueryRequest):
    result = score(
        llm=llm,
        student_ans=request.student_ans,
        expected_ans=request.expected_ans,
        total_score=request.total_score,
        question=request.question,
        guidelines=request.guidelines  # Pass guidelines if provided
    )
    return result


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8020)
