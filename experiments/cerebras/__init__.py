"""Experimental Cerebras access via Simon Willison's `llm` library.

Standalone: does not import from the rest of the project.
"""

from .client import DEFAULT_MODEL, call_with_schema, list_models

__all__ = ["DEFAULT_MODEL", "call_with_schema", "list_models"]
