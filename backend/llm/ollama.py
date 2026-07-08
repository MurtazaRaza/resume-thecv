import httpx

from backend import config
from backend.llm.provider import LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, base_url: str = None, model: str = None):
        self.base_url = (base_url or config.OLLAMA_URL).rstrip("/")
        self.model = model or config.MODEL

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, max_tokens: int = 800) -> str:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            "stream": False,
            "options": {
                "num_ctx": config.NUM_CTX,
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"
        try:
            resp = httpx.post(f"{self.base_url}/api/chat", json=payload,
                              timeout=config.LLM_TIMEOUT_S)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(
                f"Ollama request failed ({e}). Is `ollama serve` running and "
                f"is the model `{self.model}` pulled?")
        return resp.json().get("message", {}).get("content", "")

    def is_up(self) -> bool:
        try:
            return httpx.get(f"{self.base_url}/api/tags", timeout=3).status_code == 200
        except httpx.HTTPError:
            return False
