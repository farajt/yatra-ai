"""Checkpoint serializer with an explicit allowlist of our own types.

LangGraph 1.x warns when it loads an unregistered class from a checkpoint and will
block it in a future version. Blocking matters for security (a tampered checkpoint
must not be able to construct arbitrary objects), so we opt in to strict mode now and
register exactly the domain models that live in graph state.
"""
from enum import Enum
from functools import lru_cache

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer
from pydantic import BaseModel

from yatra import schemas


def allowed_types() -> list[tuple[str, str]]:
    return sorted(
        (obj.__module__, obj.__name__)
        for obj in vars(schemas).values()
        if isinstance(obj, type)
        and issubclass(obj, (BaseModel, Enum))
        and obj.__module__ == schemas.__name__
    )


@lru_cache
def get_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=allowed_types())
