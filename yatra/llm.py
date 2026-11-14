"""LLM factory. All agents get their model from here — never instantiate ChatGroq directly."""
import json
import logging
from functools import lru_cache
from typing import Any, TypeVar

import groq
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from langchain_core.runnables import Runnable
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from yatra.config import get_settings
from yatra.errors import ConfigError, LLMOutputError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


def _chat(model: str) -> BaseChatModel:
    s = get_settings()
    extra = {}
    if "gpt-oss" in model and s.llm_reasoning_effort:
        extra["reasoning_effort"] = s.llm_reasoning_effort
    return ChatGroq(
        model=model,
        api_key=s.groq_api_key,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
        max_tokens=s.llm_max_tokens,
        **extra,
    )


@lru_cache(maxsize=4)
def get_llm(fast: bool = False) -> Runnable:
    """Return a configured Groq chat model.

    fast=True  -> smaller model for extraction/routing (cheaper, quicker)
    fast=False -> main model for planning, itinerary writing and critique; if Groq rate-limits
                  it (free tier: 200k tokens/day), calls fall back to GROQ_FALLBACK_MODEL.
    """
    s = get_settings()
    if not s.groq_api_key:
        raise ConfigError("GROQ_API_KEY is not set. Add it to your .env file.")
    if fast:
        return _chat(s.groq_fast_model)
    main = _chat(s.groq_model)
    if s.groq_fallback_model and s.groq_fallback_model != s.groq_model:
        return main.with_fallbacks([_chat(s.groq_fallback_model)],
                                   exceptions_to_handle=(groq.RateLimitError,))
    return main


def _drop_nulls(value: Any) -> Any:
    """Remove null fields so Pydantic defaults apply (models often send null for 'nothing')."""
    if isinstance(value, dict):
        return {k: _drop_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_drop_nulls(v) for v in value if v is not None]
    return value


def salvage_tool_call(error: Exception, schema: type[T]) -> T | None:
    """Recover structured output from a Groq 'tool_use_failed' error.

    When the model's arguments don't exactly match the JSON schema, Groq rejects the call
    but returns what the model generated in `failed_generation`. Usually the answer is right
    and only the shape is off (e.g. null instead of []), so we clean it and validate it ourselves.
    """
    body = getattr(error, "body", None)
    if not isinstance(body, dict):
        return None
    err = body.get("error", body)
    if not isinstance(err, dict) or err.get("code") != "tool_use_failed":
        return None
    try:
        generated = json.loads(err.get("failed_generation") or "")
        args = generated.get("arguments", generated) if isinstance(generated, dict) else None
        if isinstance(args, str):
            args = json.loads(args)
        if not isinstance(args, dict):
            return None
        return schema.model_validate(_drop_nulls(args))
    except (ValueError, ValidationError, AttributeError) as e:
        log.debug("Could not salvage failed tool call: %s", e)
        return None


# Tried in order. Tool calling is the most reliable on Groq, but gpt-oss sometimes answers in
# prose, names the tool "functions.X", or truncates the JSON; a JSON-schema response is a
# different code path that usually succeeds when tool calling just failed.
STRUCTURED_METHODS = ("function_calling", "json_schema")


def invoke_structured(
    schema: type[T], messages: list[BaseMessage], *, fast: bool = False, attempts: int = 2
) -> T:
    """Call the LLM and parse its output into `schema`.

    Robustness ladder: 1) tool call  2) salvage a rejected tool call  3) retry with a JSON-schema
    response instead of a tool call.
    """
    llm = get_llm(fast=fast)
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        method = STRUCTURED_METHODS[min(attempt, len(STRUCTURED_METHODS)) - 1]
        model = llm.with_structured_output(schema, method=method)
        try:
            result = model.invoke(messages)
            if result is not None:
                return result
            last_error = LLMOutputError("model returned no structured output")
        except ConfigError:
            raise
        except Exception as e:  # noqa: BLE001 — provider errors vary; we retry or salvage
            salvaged = salvage_tool_call(e, schema)
            if salvaged is not None:
                log.info("Recovered %s from a rejected tool call", schema.__name__)
                return salvaged
            last_error = e
        log.warning("Structured output attempt %d/%d (%s) failed: %s", attempt, attempts, method,
                    str(last_error)[:300])
    raise LLMOutputError(f"{schema.__name__}: {last_error}")
