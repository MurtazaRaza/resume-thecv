import httpx

from backend import config
from backend.llm.provider import LLMError, LLMProvider

_API_BASE = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str = None, model: str = None):
        self.api_key = api_key or config.GEMINI_API_KEY
        self.model = model or config.GEMINI_MODEL
        if not self.api_key:
            raise LLMError(
                "GEMINI_API_KEY is not set. Add it to .env or export it, "
                "or switch CVE_PROVIDER back to ollama.")

    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, max_tokens: int = 800) -> str:
        payload = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": user}]}],
            "generationConfig": {
                "temperature": temperature,
                "maxOutputTokens": max_tokens,
            },
        }
        if json_mode:
            payload["generationConfig"]["responseMimeType"] = "application/json"
        url = f"{_API_BASE}/{self.model}:generateContent"
        try:
            resp = httpx.post(url, params={"key": self.api_key}, json=payload,
                              timeout=config.LLM_TIMEOUT_S)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise LLMError(f"Gemini request failed ({e}).")
        data = resp.json()
        candidates = data.get("candidates") or []
        if not candidates:
            block_reason = data.get("promptFeedback", {}).get("blockReason")
            raise LLMError(
                f"Gemini returned no candidates"
                f"{f' (blocked: {block_reason})' if block_reason else ''}.")
        parts = candidates[0].get("content", {}).get("parts") or []
        return "".join(p.get("text", "") for p in parts)

    def is_up(self) -> bool:
        try:
            resp = httpx.get(f"{_API_BASE}/{self.model}",
                             params={"key": self.api_key}, timeout=5)
            return resp.status_code == 200
        except httpx.HTTPError:
            return False
