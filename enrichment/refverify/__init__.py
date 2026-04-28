"""Citation verifier — OpenAlex + Wikipedia.

Per citation:
  1. Haiku formulates a query and calls search_openalex / search_wikipedia.
  2. A deterministic match gate (title-Jaccard, author surname, year ±1)
     decides whether any candidate is a real match.
  3. If a candidate passes, Haiku composes a 1-2 sentence description from
     the candidate's actual metadata. Verdict (verified yes/no) is the
     gate's output, never Haiku's opinion.
"""

from .agent import ReadingListEntry, assess_citation

__all__ = ["assess_citation", "ReadingListEntry"]
