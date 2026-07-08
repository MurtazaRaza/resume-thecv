"""LLM provider abstraction. OllamaProvider is the default; AnthropicProvider
is a stub so switching to a cloud model later is a config change, not a rewrite."""
import json
from abc import ABC, abstractmethod
from typing import Any


class LLMError(Exception):
    """Raised when the provider is unreachable or returns unusable output.
    Routes catch this and surface a friendly message — never a crash."""


class LLMProvider(ABC):
    @abstractmethod
    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, max_tokens: int = 800) -> str:
        ...

    def complete_json(self, system: str, user: str, *,
                      temperature: float = 0.3, max_tokens: int = 800) -> Any:
        """complete() with json_mode, parsed; one retry with the error appended."""
        raw = self.complete(system, user, json_mode=True,
                            temperature=temperature, max_tokens=max_tokens)
        try:
            return json.loads(raw)
        except json.JSONDecodeError as e:
            retry_user = (f"{user}\n\nYour previous reply was not valid JSON "
                          f"({e}). Respond again with ONLY valid JSON.")
            raw = self.complete(system, retry_user, json_mode=True,
                                temperature=temperature, max_tokens=max_tokens)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                raise LLMError("Model returned invalid JSON twice; try again "
                               "or switch to a stronger model in config.")


class AnthropicProvider(LLMProvider):
    def complete(self, system: str, user: str, *, json_mode: bool = False,
                 temperature: float = 0.3, max_tokens: int = 800) -> str:
        raise NotImplementedError(
            "AnthropicProvider is a placeholder — set CVE_PROVIDER=ollama.")


def get_provider() -> LLMProvider:
    from backend import config
    if config.LLM_PROVIDER == "anthropic":
        return AnthropicProvider()
    from backend.llm.ollama import OllamaProvider
    return OllamaProvider()
