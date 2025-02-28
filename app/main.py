import time


from fastapi import FastAPI, Depends, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.openapi.docs import get_swagger_ui_html, get_redoc_html
from fastapi.responses import HTMLResponse


from app.config.enums import LLMProvider
from .core.logger import logger
from .core.lifespan import lifespan
from .core.auth import verify_username, AuthStaticFiles

from .api.evaluation.router import router as evaluation_router
from .api.provider.router import router as provider_router
from .api.scoring.router import router as scoring_router
from .api.workers.router import router as workers_router


# Initialize FastAPI with lifespan manager
logger.info("Initializing FastAPI application")
app = FastAPI(
    lifespan=lifespan,
    docs_url=None,
    redoc_url=None,
    openapi_url="/api/openapi.json",
    title="DescEval",
    description="Evaluation Backend for Evalify",
    version="0.3.4",
)

# Store current provider in app state
app.state.current_provider = LLMProvider.VLLM
app.state.current_model_name = (
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"  # "deepseek-r1:70b"
)
app.state.current_api_key = None

app.state.current_micro_llm_provider = LLMProvider.VLLM  # LLMProvider.GROQ
app.state.current_micro_llm_model_name = (
    "deepseek-ai/DeepSeek-R1-Distill-Llama-8B"  # "llama-3.3-70b-specdec"
)
app.state.current_micro_llm_api_key = None  # os.getenv("GROQ_API_KEY")

# Include routers
app.include_router(evaluation_router)
app.include_router(provider_router)
app.include_router(scoring_router)
app.include_router(workers_router)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: Consider restricting origins in production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


app.mount("/static", AuthStaticFiles(directory="static"), name="static")


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time
    logger.info(
        f"Path: {request.url.path} | "
        f"Method: {request.method} | "
        f"Status: {response.status_code} | "
        f"Duration: {duration:.3f}s"
    )
    return response


@app.get("/")
async def read_index():
    return FileResponse("static/index.html", media_type="text/html")


@app.get("/docs", response_class=HTMLResponse)
async def get_docs(username: str = Depends(verify_username)) -> HTMLResponse:
    return get_swagger_ui_html(openapi_url="/api/openapi.json", title="docs")


@app.get("/redoc", response_class=HTMLResponse)
async def get_redoc(username: str = Depends(verify_username)) -> HTMLResponse:
    return get_redoc_html(openapi_url="/api/openapi.json", title="redoc")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=4040)
