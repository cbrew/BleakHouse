import os
from typing import Dict, Any, List
import json
import anthropic
import dotenv
from hamilton.function_modifiers import config


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


@config.when(input_choice="plaintext")
def lengths__plaintext(plaintext: Dict[str,Any]) -> Dict[str,Any]:
    return {
        "tokens": _get_tokens(plaintext['text']),
        "characters": len(plaintext['text'])}

@config.when(input_choice="chapters")
def lengths__chapters(chapters: Dict[str,Any]) -> Dict[str,Any]:
    result = {}
    for doc_key in chapters:
        this_doc = chapters[doc_key]
        result[doc_key] = _get_chapter_lengths(this_doc)
    return result

def _get_chapter_lengths(chapters: List[Dict[str,Any]]) -> Dict[str,Any]:
    return {"tokens": sum(_get_tokens(chapter['text']) for chapter in chapters),
            "characters": sum(len(chapter['text']) for chapter in chapters)}