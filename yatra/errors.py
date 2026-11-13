"""Project-wide exceptions."""


class ToolError(RuntimeError):
    """Raised when an external tool (API) fails. Agents catch this and degrade gracefully
    instead of crashing the whole graph run."""

    def __init__(self, tool: str, message: str):
        self.tool = tool
        self.message = message
        super().__init__(f"[{tool}] {message}")


class ConfigError(RuntimeError):
    """Raised when a required setting (API key, DB URL) is missing."""


_QUOTA_MARKERS = ("ratelimiterror", "rate limit reached", "rate_limit_exceeded", "error code: 429")


def is_quota_error(error: Exception | str) -> bool:
    """True when an LLM provider refused a call because a rate/usage limit was hit."""
    text = f"{type(error).__name__}: {error}" if isinstance(error, Exception) else str(error)
    return any(m in text.lower() for m in _QUOTA_MARKERS)


class LLMOutputError(RuntimeError):
    """Raised when the LLM fails to return valid structured output after retries."""
