# Secondary Literature in the Podcast Pipeline

## Problem

The v1.0-v1.2 pipeline generates literary discussions without reference to
actual scholarship.  Experts "cite" works based on the LLM's training data,
but nobody consults the secondary literature.  This means:

- Citations may be confabulated (the LLM invents plausible-sounding works)
- Experts cannot engage with real scholarly arguments
- There is no reading list for listeners who want to go further

## Solution: Tool-Calling Pre-Interviews with Verification (v1.3)

### Architecture

```
Phase 2.5a: Pre-interviews (Sonnet + tools)
  Expert has access to:
    - search_openalex (scholarly works — returns titles, authors, abstracts)
    - search_wikipedia (background context — returns article extracts)
    - touchstone_works (4-5 canonical works per persona, auto-verified)

  Expert proposes references during interview → stored in proposed_references

Post-interview verification (deterministic, no LLM):
  For each unique proposed reference:
    1. Check touchstone_works → fuzzy match (SequenceMatcher > 0.7) → auto-verify
    2. Search OpenAlex API → title match (> 0.5) → verify with metadata
    3. Search Wikipedia API → page title match (> 0.4) → verify
    4. Otherwise → mark as unverified

  Output: phase2_5_reading_list.json
    - verified: list of VerifiedReference (with source, metadata, citation count)
    - unverified: list of VerifiedReference (verification_source = "unverified")
    - verification_rate: float (typically 60-80%)

Phase 2.5b: Question planning (unchanged, but now receives references)
  Verified references injected into question planning prompt
  Sonnet frames questions around findings, not methods:
    "Levine argues Bleak House is a 'network of networks' — do you agree?"
    not: "Can you tell us about your network analysis methodology?"

Phase 3: Script generation (minor change)
  Final segment host closing includes 1-2 recommended readings
  Drawn from recommended_reading field on HostBrief
```

### Information Flow

```
touchstone_works (per persona, in podcast_types.py)
    ↓
Pre-interview system prompt (expert's "home library")
    ↓
Expert searches OpenAlex/Wikipedia during interview
    ↓ (tool calls return abstracts + article content)
Expert engages with real scholarly arguments
    ↓
proposed_references in PreInterviewResponse
    ↓
Verification (deterministic: OpenAlex + Wikipedia APIs)
    ↓
phase2_5_reading_list.json (verified + unverified)
    ↓
Flows into three places:
  1. plan_questions() — references injected into steering notes
  2. Final segment — host recommends 1-2 works in sign-off
  3. report.html — reading list section with verification badges
```

### Key Design Decisions

**Why tool calling, not RAG?**  The expert decides what to search for based
on the passages they're discussing.  This produces novel-specific,
passage-specific references rather than generic bibliography.

**Why Sonnet, not Haiku, for tool interviews?**  Haiku's tool-calling is
less reliable.  The cost increase is modest (~$0.04/episode) since
pre-interviews are the cheapest phase.

**Why deterministic verification?**  No LLM in the verification loop.
Fixed similarity thresholds on string matching.  Given the same inputs
and API responses, the same classification every time.

**Why touchstone works?**  Each persona has 4-5 canonical works they
"know well."  These are auto-verified (no API call needed) and ground
the expert in real scholarship from the start.

## Content Surfacing (v1.3+)

The search tools return actual content, not just metadata:

- **OpenAlex**: abstracts reconstructed from inverted_index (typically
  100-200 words of the paper's actual argument)
- **Wikipedia**: first ~8 sentences of article via TextExtracts API
  (factual background on institutions, people, concepts)

This means the expert reads and responds to real scholarly arguments
during the pre-interview.  Chen can read Levine's abstract about
"affordances of form" and agree or disagree specifically.

## Options Considered but Not Yet Implemented

### Content access (richer engagement with scholarship)

3. **JSTOR/Project MUSE open-access abstracts** — deeper humanities
   coverage but requires API understanding
4. **Google Books snippet view** — actual book content via Volumes API,
   2-3 decontextualised sentences per keyword match
5. **Semantic Scholar full-text search** — open-access paragraphs from
   published papers, weak humanities coverage
6. **Pre-built passage index of key secondary works** — curated RAG
   over 10-20 critical works per novel, highest quality but manual effort
7. **Internet Archive full-text search** — older criticism (pre-1978)
   fully available, good for Victorian studies specifically
8. **Crossref + Unpaywall for open-access PDFs** — real full-text papers
   where OA versions exist (~30% of recent work)
9. **Author-curated key passages in persona definitions** — hand-picked
   quotes from touchstone works, highest quality, doesn't scale
10. **LLM-mediated literature review as pipeline phase** — automated
    500-word briefing per expert from abstracts, most ambitious

### Report integration (how scholarship appears in output)

5. **Footnote-style references in transcript** — hover/click annotations
   matching expert claims to verified references
9. **Dual-track report** — two-column layout, transcript + scholarship sidebar
10. **Expert attributes claims to real scholars** — "As Levine argues..."
    (sparingly, at most once per expert per episode)
11. **Disagreement grounded in different sources** — two experts cite
    different works, host sets up the tension
12. **Confidence annotation** — badge on turns indicating whether the
    claim is literature-backed or novel insight
13. **State of the criticism note per segment** — Sonnet reads abstracts,
    writes 2-3 sentence summary for host's background knowledge

## Empirical Results (v1.3, 6 runs)

| Condition | Proposed | Verified | Rate |
|-----------|----------|----------|------|
| BH Panel A | 40 | 31 | 78% |
| BH Interdisciplinary | 7 | 5 | 71% |
| PTI Panel A | 51 | 32 | 63% |
| PTI Interdisciplinary | 28 | 16 | 57% |

- Blackstone is the heaviest citer (Acts of Parliament, case law)
- Touchstone matching catches ~40% of verified references
- OpenAlex is strong on journal articles, weak on books
- Wikipedia catches Acts of Parliament and historical events
- Unverified references are often real but too specific for API matching
  (e.g., CLiC Dickens project, specific Hansard debates)

## Files

- `enrichment/reference_tools.py` — tool definitions, execution, verification
- `enrichment/podcast_types.py` — touchstone_works, proposed_references, recommended_reading
- `enrichment/host_prep.py` — tool-calling interview loop, verification orchestration
- `enrichment/run_pipeline.py` — `--reference-tools` CLI flag
- `webapp/build_manifest.py` — reading list in manifest
- `webapp/build_report.py` — reading list section in report.html
- `enrichment/generate_podcast.py` — recommended reading in host sign-off
