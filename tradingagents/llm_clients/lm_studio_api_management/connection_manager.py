import httpx
from typing import Optional

class LMStudioConnectionManager:
    _instance = None
    _client: Optional[httpx.Client] = None
    _base_url: str = "http://127.0.0.1:1234/v1"

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super(LMStudioConnectionManager, cls).__new__(cls)
        return cls._instance

    def configure(self, base_url: str):
        """Set the base URL and initialize the persistent connection."""
        self._base_url = base_url
        if self._client:
            self._client.close()
        # Create a single persistent HTTP client
        self._client = httpx.Client(base_url=base_url, timeout=120.0)

    def get_client(self) -> httpx.Client:
        """Returns the active persistent HTTP client."""
        if self._client is None:
            self._client = httpx.Client(base_url=self._base_url, timeout=120.0)
        return self._client

    def close(self):
        """Close the connection."""
        if self._client:
            self._client.close()
            self._client = None

# Global singleton instance
lm_studio_manager = LMStudioConnectionManager()