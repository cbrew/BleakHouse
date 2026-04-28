"""Haiku-driven citation verifier.

Re-assesses unverified entries from `phase2_5_reading_list.json`. The agent
(claude-haiku-4-5) is given source APIs as tools — CrossRef, Semantic Scholar,
Fatcat, CiNii, legislation.gov.uk, CourtListener, GovInfo, faculty pages via
Brave Search — and emits a calibrated odds ratio of "real" vs "confabulated"
for each citation.

System prompt biases toward "confabulated" when in doubt: a fake-verified
pastiche is worse than a missed real citation.
"""

from .agent import (
    DEFAULT_PROMOTE_THRESHOLD,
    Assessment,
    assess_citation,
)

__all__ = ["assess_citation", "Assessment", "DEFAULT_PROMOTE_THRESHOLD"]
