"""LLM factory. All agents get their model from here — never instantiate ChatGroq directly."""
import json
import logging
from functools import lru_cache
from typing import Any, TypeVar

from langchain_core.messages import BaseMessage
from langchain_groq import ChatGroq
from pydantic import BaseModel, ValidationError

from yatra.config import get_settings
from yatra.errors import ConfigError, LLMOutputError

log = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


@lru_cache(maxsize=4)
def get_llm(fast: bool = False) -> ChatGroq:
    """Return a configured Groq chat model.

    fast=True  -> smaller model for extraction/routing (cheaper, quicker)
    fast=False -> main model for planning, itinerary writing and critique
    """
    s = get_settings()
    if not s.groq_api_key:
        raise ConfigError("GROQ_API_KEY is not set. Add it to your .env file.")
    return ChatGroq(
        model=s.groq_fast_model if fast else s.groq_model,
        api_key=s.groq_api_key,
        temperature=s.llm_temperature,
        timeout=s.llm_timeout_s,
        max_retries=s.llm_max_retries,
    )


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


def invoke_structured(
    schema: type[T], messages: list[BaseMessage], *, fast: bool = False, attempts: int = 2
) -> T:
    """Call the LLM and parse its output into `schema` (via tool calling).

    Robustness ladder: 1) normal call  2) salvage a rejected tool call  3) retry once.
    """
    model = get_llm(fast=fast).with_structured_output(schema, method="function_calling")
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
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
        log.warning("Structured output attempt %d/%d failed: %s", attempt, attempts, last_error)
    raise LLMOutputError(f"{schema.__name__}: {last_error}")
