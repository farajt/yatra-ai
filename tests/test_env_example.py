"""Guard: .env.example is committed to GitHub, so it must never contain real keys."""
from pathlib import Path

ENV_EXAMPLE = Path(__file__).resolve().parent.parent / ".env.example"
KEY_PREFIXES = ("gsk_", "tvly-", "sk-", "pk-lf-", "sk-lf-")   # Groq, Tavily, OpenAI-style, Langfuse


def test_env_example_has_no_secrets():
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        name, value = (part.strip() for part in line.split("=", 1))
        if name.endswith(("_KEY", "_SECRET", "_TOKEN")):
            assert value == "", f"{name} has a value in .env.example. Put real keys only in .env"
    for prefix in KEY_PREFIXES:
        assert prefix not in text, f"Something that looks like a real key ({prefix}...) is in .env.example"
