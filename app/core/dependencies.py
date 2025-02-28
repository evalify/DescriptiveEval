from app.api.scoring.scoring import get_llm
from fastapi import Request, Depends, FastAPI

def get_app(request : Request) -> FastAPI:
    """Retrieve the FastAPI application from the request context."""
    return request.app

def get_llm_dependency(app=Depends(get_app)):
    """Dependency to provide LLM instance based on current provider"""
    return get_llm(
        provider=app.state.current_provider,
        model_name=app.state.current_model_name,
        api_key=app.state.current_api_key,
    )


def get_micro_llm_dependency(app=Depends(get_app)):
    return get_llm(
        provider=app.state.current_micro_llm_provider,
        model_name=app.state.current_micro_llm_model_name,
        api_key=app.state.current_micro_llm_api_key,
    )