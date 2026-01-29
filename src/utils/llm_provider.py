import os
from typing import Optional

from browser_use.llm.anthropic.chat import ChatAnthropic
from browser_use.llm.azure.chat import ChatAzureOpenAI
from browser_use.llm.google.chat import ChatGoogle
from browser_use.llm.mistral.chat import ChatMistral
from browser_use.llm.ollama.chat import ChatOllama
from browser_use.llm.openai.chat import ChatOpenAI
from browser_use.llm.browser_use.chat import ChatBrowserUse

from src.utils import config


def _require_api_key(provider: str, api_key: Optional[str]) -> str:
    env_var = f"{provider.upper()}_API_KEY"
    key = api_key or os.getenv(env_var, "")
    if not key:
        provider_display = config.PROVIDER_DISPLAY_NAMES.get(provider, provider.upper())
        raise ValueError(
            f"💥 {provider_display} API key not found! 🔑 Please set `{env_var}` or provide it in the UI."
        )
    return key


def get_llm_model(
    provider: str,
    model_name: Optional[str] = None,
    temperature: float = 0.2,
    base_url: Optional[str] = None,
    api_key: Optional[str] = None,
    num_ctx: Optional[int] = None,
):
    if provider == "google":
        key = _require_api_key(provider, api_key)
        return ChatGoogle(model=model_name or "gemini-3-pro-preview", temperature=temperature, api_key=key)
    if provider == "openai":
        key = _require_api_key(provider, api_key)
        return ChatOpenAI(model=model_name or "gpt-4o", temperature=temperature, api_key=key, base_url=base_url)
    if provider == "azure_openai":
        key = _require_api_key(provider, api_key)
        azure_endpoint = base_url or os.getenv("AZURE_OPENAI_ENDPOINT", "")
        api_version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-12-01-preview")
        return ChatAzureOpenAI(
            model=model_name or "gpt-4o",
            temperature=temperature,
            api_key=key,
            azure_endpoint=azure_endpoint,
            api_version=api_version,
        )
    if provider == "anthropic":
        key = _require_api_key(provider, api_key)
        base = base_url or os.getenv("ANTHROPIC_ENDPOINT", None)
        return ChatAnthropic(model=model_name or "claude-3-7-sonnet-latest", api_key=key, base_url=base)
    if provider == "mistral":
        key = _require_api_key(provider, api_key)
        return ChatMistral(
            model=model_name or "mistral-large-latest",
            temperature=temperature,
            api_key=key,
            base_url=base_url or "https://api.mistral.ai/v1",
        )
    if provider == "ollama":
        host = base_url or os.getenv("OLLAMA_ENDPOINT", "http://localhost:11434")
        ollama_options = {"num_ctx": num_ctx} if num_ctx else None
        return ChatOllama(model=model_name or "qwen2.5:7b", host=host, ollama_options=ollama_options)
    if provider == "browser_use":
        key = _require_api_key("browser_use", api_key or os.getenv("BROWSER_USE_API_KEY", ""))
        return ChatBrowserUse(api_key=key)

    raise ValueError(f"Unsupported provider: {provider}")
