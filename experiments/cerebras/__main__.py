"""Demo: `uv run python -m experiments.cerebras`"""

from __future__ import annotations

import json

from pydantic import BaseModel

from .client import DEFAULT_MODEL, call_with_schema, list_models


class _Sentiment(BaseModel):
    label: str
    confidence: float
    rationale: str


def main() -> None:
    print("Available Cerebras models:")
    for mid in list_models():
        marker = " <- default" if mid == DEFAULT_MODEL else ""
        print(f"  {mid}{marker}")

    print(f"\nCalling {DEFAULT_MODEL} with a JSON schema...")
    result = call_with_schema(
        "Classify the sentiment of: 'The fog is everywhere, and yet I feel at home in it.'",
        _Sentiment,
        system="You are a literary sentiment classifier. Respond only via the schema.",
    )
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
