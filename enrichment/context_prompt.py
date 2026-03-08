"""Prompt builder for contextual retrieval context generation.

Produces system blocks with cache_control for Anthropic prompt caching,
so the chapter text is cached and reused across all passages in the chapter.
"""

from anthropic.types import TextBlockParam


def build_context_messages(
    chapter_text: str, chunk_text: str
) -> tuple[list[TextBlockParam], str]:
    """Build system blocks and user message for context generation.

    Returns:
        (system_blocks, user_message) — system blocks include cache_control
        for prompt caching of the chapter text.
    """
    system: list[TextBlockParam] = [
        TextBlockParam(
            type="text",
            text=f"<document>\n{chapter_text}\n</document>",
            cache_control={"type": "ephemeral"},
        )
    ]
    user_msg = (
        "Here is the chunk we want to situate within this chapter of "
        "Bleak House by Charles Dickens:\n"
        f"<chunk>{chunk_text}</chunk>\n"
        "Please give a short succinct context to situate this chunk within "
        "the overall chapter for the purposes of improving search retrieval "
        "of the chunk. Answer only with the succinct context and nothing else."
    )
    return system, user_msg
