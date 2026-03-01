from typing import Any, Optional
from langchain_openai import ChatOpenAI
from .base_client import BaseLLMClient
from .validators import validate_model
from .lm_studio_api_management.connection_manager import lm_studio_manager

class LMStudioClient(BaseLLMClient):
    """Client for local LM Studio instance using a shared connection."""

    def __init__(self, model: str, base_url: Optional[str] = None, **kwargs):
        super().__init__(model, base_url, **kwargs)
        # Initialize the shared connection manager if a URL is provided
        if base_url:
            lm_studio_manager.configure(base_url)

    def get_llm(self) -> Any:
        """Return configured ChatOpenAI instance pointing to LM Studio."""
        
        # Get the persistent HTTP client
        http_client = lm_studio_manager.get_client()

        llm_kwargs = {
            "model": self.model,
            "api_key": "lm-studio", # Placeholder key required by library
            "base_url": str(http_client.base_url),
            "http_client": http_client, # Inject the shared connection
            "temperature": 0.7,
        }

        # Pass through optional args
        for key in ("timeout", "max_retries", "callbacks", "max_tokens"):
            if key in self.kwargs:
                llm_kwargs[key] = self.kwargs[key]

        return ChatOpenAI(**llm_kwargs)

    def validate_model(self) -> bool:
        """LM Studio accepts any loaded model, so we return True."""
        return True