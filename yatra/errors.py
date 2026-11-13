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


class LLMOutputError(RuntimeError):
    """Raised when the LLM fails to return valid structured output after retries."""
