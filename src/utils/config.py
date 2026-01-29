PROVIDER_DISPLAY_NAMES = {
    "openai": "OpenAI",
    "azure_openai": "Azure OpenAI",
    "anthropic": "Anthropic",
    "google": "Google",
    "mistral": "Mistral",
    "ollama": "Ollama",
    "browser_use": "Browser-Use",
}

# Predefined model names for common providers
model_names = {
    "anthropic": ["claude-3-7-sonnet-latest", "claude-3-5-sonnet-20241022"],
    "openai": ["gpt-4o", "gpt-4", "gpt-3.5-turbo"],
    "google": ["gemini-3-pro-preview", "gemini-2.0-pro-exp-02-05", "gemini-2.0-flash"],
    "ollama": ["qwen2.5:7b", "qwen2.5:14b", "qwen2.5-coder:14b"],
    "azure_openai": ["gpt-4o", "gpt-4"],
    "mistral": ["mistral-large-latest", "mistral-small-latest"],
    "browser_use": ["browser-use"],
}
