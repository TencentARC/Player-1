"""Model transport configuration and generation results."""
from __future__ import annotations
from dataclasses import dataclass, asdict
from typing import Any

@dataclass(frozen=True)
class GenerationResult:
    text: str
    prompt_tokens: int
    completion_tokens: int
    finish_reason: str | None
    tool_calls: tuple[dict[str, Any], ...] = ()
    reasoning: str | None = None
    latency_s: float = 0.0
    request_attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

@dataclass(frozen=True)
class OpenAICompatibleConfig:
    model: str
    endpoint: str = "http://127.0.0.1:8000/v1"
    max_tokens: int = 128
    temperature: float = 0.6
    top_p: float = 0.95
    top_k: int = 20
    timeout_s: float = 180.0
    seed: int = 0
    enable_thinking: bool = False
    api_key_env: str | None = None
    tool_choice: str = "auto"
    max_retries: int = 0
    retry_backoff_s: float = 0.5

    def __post_init__(self) -> None:
        if not self.model.strip():
            raise ValueError("OpenAI-compatible model cannot be empty")
        if not self.endpoint.startswith(("http://", "https://")):
            raise ValueError("OpenAI-compatible endpoint must be an HTTP(S) URL")
        if self.max_tokens <= 0:
            raise ValueError("max_tokens must be positive")
        if self.temperature < 0.0:
            raise ValueError("temperature cannot be negative")
        if not 0.0 < self.top_p <= 1.0:
            raise ValueError("top_p must be in (0, 1]")
        if self.top_k != -1 and self.top_k < 1:
            raise ValueError("top_k must be -1 or positive")
        if self.timeout_s <= 0.0:
            raise ValueError("timeout_s must be positive")
        if self.tool_choice not in {"auto", "required"}:
            raise ValueError("tool_choice must be 'auto' or 'required'")
        if self.max_retries < 0:
            raise ValueError("max_retries cannot be negative")
        if self.retry_backoff_s < 0.0:
            raise ValueError("retry_backoff_s cannot be negative")

    @property
    def chat_completions_url(self) -> str:
        endpoint = self.endpoint.rstrip("/")
        return endpoint if endpoint.endswith("/chat/completions") else f"{endpoint}/chat/completions"
