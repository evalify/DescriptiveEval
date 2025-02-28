from app.config.enums import LLMProvider
from app.core.exceptions import InvalidProviderError
from app.config.constants import VLLM_HOST, OLLAMA_HOST, GROQ_API_KEY, LLM_TEMP
from langchain_groq import ChatGroq
from langchain_ollama import ChatOllama
from langchain_openai import ChatOpenAI


def get_llm(provider: LLMProvider = LLMProvider.GROQ, api_key=None, model_name=None):
    """
    Get an LLM instance with the specified provider

    :param provider: The LLM provider to use
    :param api_key: The API key for the provider (optional)
    :param model_name: The model name for the provider (optional)
    """
    if provider.value == LLMProvider.VLLM.value:
        return ChatOpenAI(
            model_name=model_name or "meta-llama/Meta-Llama-3.1-8B-Instruct",
            base_url=VLLM_HOST,
            temperature=LLM_TEMP,
            api_key=api_key or "123",
        )

    elif provider.value == LLMProvider.OLLAMA.value:
        return ChatOllama(
            model=model_name if model_name else "llama3.3",
            base_url=OLLAMA_HOST,
            temperature=LLM_TEMP,
        )
    elif provider.value == LLMProvider.GROQ.value:
        return ChatGroq(
            model_name=model_name if model_name else "llama-3.3-70b-specdec",
            temperature=LLM_TEMP,
            api_key=api_key if api_key else GROQ_API_KEY,
        )
    else:
        raise InvalidProviderError(provider)
