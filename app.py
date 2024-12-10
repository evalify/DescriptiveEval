from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware
from model import score, llm, LLMProvider, set_llm_provider

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class QueryRequest(BaseModel):
    question: str
    student_ans: str
    expected_ans: str
    total_score: int

class ProviderRequest(BaseModel):
    provider: str

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
    response_json = score(
        llm=llm,
        student_ans=request.student_ans,
        expected_ans=request.expected_ans,
        total_score=request.total_score
    )
    return response_json

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8020)





