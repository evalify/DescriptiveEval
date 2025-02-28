from pydantic import BaseModel


class ProviderRequest(BaseModel):
    provider: str
    provider_model_name: str = None
    provider_api_key: str = None
    service: str = "macro"
