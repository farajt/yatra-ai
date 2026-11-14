"""Example plans shown to visitors (always available, cost nothing to view).

Generated with `python -m scripts.make_examples` and stored as JSON in examples/.
Each file is the same payload the live app renders, plus the query and generation date.
"""
import json
from pathlib import Path

from yatra.config import PROJECT_ROOT

EXAMPLES_DIR = PROJECT_ROOT / "examples"


def load_examples(folder: Path = EXAMPLES_DIR) -> list[dict]:
    if not folder.exists():
        return []
    plans = []
    for path in sorted(folder.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if data.get("status") == "planned" and data.get("request"):
            plans.append(data)
    return plans
