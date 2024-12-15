import os
from typing import Dict,Any
import json
import anthropic
import dotenv


def _get_tokens(text: str) -> Dict[str,Any]:
    if os.environ.get("ANTHROPIC_API_KEY") is None:
        dotenv.load_dotenv()
    client = anthropic.Anthropic()

    response = client.beta.messages.count_tokens(
        betas=["token-counting-2024-11-01"],
        model="claude-3-5-sonnet-20241022",
        system="You are an AI assistant tasked with analyzing literary documents.",
        messages=[{"role":"user", "content": "Here is the text to be analyzed."},
                {"role": "user",
                 "content": text}])

    return json.loads(response.model_dump_json())

def lengths(text: Dict[str,Any]) -> Dict[str,Any]:
    return {
        "tokens": _get_tokens(text['text']),
        "characters": len(text['text'])}