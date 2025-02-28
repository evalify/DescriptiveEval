from .models import ProviderRequest
from app.core.logger import logger
from fastapi import APIRouter, HTTPException, Depends
from app.config.enums import LLMProvider
from app.core.dependencies import get_app

router = APIRouter(prefix="/provider", tags=["Provider"])


@router.get("/get-provider")
async def get_provider(app=Depends(get_app)):
    return {
        "provider": app.state.current_provider.value,
        "model_name": app.state.current_model_name,
        "api_key": app.state.current_api_key,
        "micro_provider": app.state.current_micro_llm_provider.value,
        "micro_model_name": app.state.current_micro_llm_model_name,
        "micro_api_key": app.state.current_micro_llm_api_key,
        "available_providers": [provider.value for provider in LLMProvider],
    }


@router.post("/set-provider")
async def change_provider(request: ProviderRequest):
    app = get_app(request)
    try:
        provider = LLMProvider(request.provider.lower())
        provider_model_name = request.provider_model_name
        provider_api_key = request.provider_api_key

        if request.service == "macro":
            logger.info(
                f"Changing provider to {provider.value} with model {provider_model_name}"
            )
            app.state.current_provider = provider
            app.state.current_model_name = provider_model_name
            app.state.current_api_key = provider_api_key
        elif request.service == "micro":
            logger.info(
                f"Changing micro provider to {provider.value} with model {provider_model_name}"
            )
            app.state.current_micro_llm_provider = provider
            app.state.current_micro_llm_model_name = provider_model_name
            app.state.current_micro_llm_api_key = provider_api_key
        else:
            raise ValueError(f"Invalid service type : {request.service}")

        return {
            "message": f"Successfully switched to {provider.value} provider with model {provider_model_name}"
        }
    except ValueError as e:
        logger.error(f"Error changing provider: {str(e)}")
        raise HTTPException(status_code=400, detail=str(e))
