"""Multi-source citation verifier with high-precision LLM judging.

Used as a post-processing step on `phase2_5_reading_list.json` files to lift
recall on the existing OpenAlex/Wikipedia/touchstone verifier. Chains free,
no-auth APIs (CrossRef, Semantic Scholar, Fatcat, HathiTrust, CiNii,
legislation.gov.uk) with optional auth APIs (CourtListener, GovInfo) read
from .env.

Each source returns candidate matches; an LLM judge (Haiku) decides whether
any candidate confirms the citation. Defaults to NO MATCH when in doubt —
the goal is to lift recall *without* compromising precision, so we'd rather
miss a real citation than fake-verify a pastiche.
"""
