# Version-pinning propagation — analysis and plan

Status: planning. Companion to `docs/structured_recommendations.md`
(which named the requirement), `docs/schemas_changelog.md` (which
implements it for schemas), and `BleakHouse-gfn2` (epic that closed
2026-05-18 consolidating schemas as the first axis).

## The recommendations doc, restated

> "Version-pin prompts, schemas, SDKs, and models. Structured-output
> behavior is not just 'model behavior'; it is also API-mode behavior,
> SDK schema transformation, grammar compilation, and provider-side
> validation. Treat schema changes as breaking API changes."
> — docs/structured_recommendations.md

Schemas are done. Three axes remain (prompts, SDKs, models) and one
cross-cutting concern (propagation through run artefacts → SQL →
webapp).

## The version-pinning matrix

|   | source-of-truth | pinned today? | recorded per run? | in SQL? | in webapp? |
|---|---|---|---|---|---|
| **Schemas** | `enrichment/llm/schemas.py` `schema_version: ClassVar[str]` | ✅ (BleakHouse-gfn2) | ❌ not yet | ❌ | ❌ |
| **Prompts** | scattered across `enrichment/host_prep.py`, `design_segments.py`, `generate_podcast.py`, etc. | ❌ partial (one `prompt_version: int` in `RunConfig`, used by `design_segments.py:V1/V2/V3`; nothing systematic elsewhere) | ❌ inconsistently | ❌ | ❌ |
| **SDKs** | `pyproject.toml` + `uv.lock` | ✅ pinned via lockfile | ❌ not recorded per run | ❌ | ❌ |
| **Models** | `params.yaml:generators[].api_model` | ✅ per-task config | ✅ `config.json:axes.generator` (post-recent-backfill) | partial (experiments.db has it; content.db may not) | partial |
| **Providers** | `params.yaml:generators[].provider` | ✅ | ✅ derived from generator | partial | partial |
| **Provider profile** | `params.yaml:provider_profiles` + CLI `--provider-profile` | ✅ | ✅ `config.json` records it | ❌ | ❌ |

The bottom row is the harder cross-cutting concern: **even the things
that are recorded don't flow all the way to the webapp**. A reader
visiting `/run/bh_trn_literary_hostprep` today can see the run's
generator and some axes but not its schemas, its prompts, or the SDK
versions it ran against. An engineer trying to re-validate a saved
run has to read source files + git log to reconstruct what it took
to make.

## Per-axis status

### 1. Prompts — the messiest axis

Prompts live in **at least** the following sites (audit needed):

- `enrichment/host_prep.py`: `_INTERVIEW_SYSTEM`, `_INTERVIEW_USER`,
  `_INTERVIEW_TOOLS_ADDENDUM`, the structured-parse system prompt
  (inline), `_QUESTION_PLANNING_SYSTEM`, `_QUESTION_PLANNING_USER`,
  `_QUESTION_COUNT_LONG/SHORT`, `_LISTENER_PICK_SYSTEM`.
- `enrichment/design_segments.py`: `SYSTEM_PROMPT_V1/V2/V3` (the only
  place with explicit version numbering today), `_SEGMENT_COUNT_*`,
  `_TOTAL_PASSAGES_*`.
- `enrichment/generate_podcast.py`: the prose-generation system +
  user prompts (long and short variants).
- `enrichment/embedding_podcast.py`: `CURATION_SYSTEM_PROMPT`.
- `enrichment/submit_passages_enriched.py`: the chapter-enrichment
  prompt body.
- Plus the in-flight novel-specific bits via `enrichment.novel_prompts`.

Today:

- `RunConfig.prompt_version: int` exists and records 1/2/3 — but
  it's only consulted by `design_segments.py`. The other prompt
  sites don't read it.
- Edits to prompts get a git commit but no version field; no
  changelog; no per-run record of which prompt revision ran.

What "pinning prompts" should look like, modelled on the schemas work:

- One canonical home (e.g. `enrichment/llm/prompts.py`) OR a
  `prompts.py` adjacent to each schema cluster (host_prep prompts in
  `enrichment/llm/host_prep_prompts.py`, etc.).
- Each prompt template carries a version string (e.g. a module-level
  constant `INTERVIEW_SYSTEM_VERSION = "2026-05-18"`).
- A `docs/prompts_changelog.md` like `docs/schemas_changelog.md`,
  with the same patch/minor/major rules.
- Bump rules will differ from schemas: patch = whitespace/typo;
  minor = clarification that doesn't change outputs; major = changes
  outputs (verifiable via a fixture re-run).
- A `prompts_changelog.md` change without a `prompt_version` bump is
  a lint failure.

**Decision pending**: one file vs many. My lean: split by call site
(`host_prep_prompts.py`, `generation_prompts.py`, etc.) because the
host_prep prompts are tightly coupled to the host_prep code path and
moving them to a central file just creates noise. The schemas case
was different — the schemas are referenced from multiple call sites
each, so consolidation paid off. Prompts are mostly single-use.

### 2. SDKs — pinned but not recorded per-run

SDK versions are pinned via `uv.lock`. Today the snapshot is implicit:
"the run that produced phase3_episode.json on 2026-04-15 used whatever
versions `uv.lock` had on disk on 2026-04-15". To recover, you'd `git
log uv.lock` and find the commit nearest the run date.

Gap: per-run metadata doesn't carry SDK versions. If
`anthropic==1.42.0` produced different behaviour from `1.41.0`
(possible — provider SDKs do transform schemas), we can't tell from
a saved run alone which version ran.

What "pinning SDKs end-to-end" should look like:

- Capture the relevant SDK versions in the per-run `config.json`'s
  axes block (e.g. `sdk_versions: {anthropic: "1.42.0", openai:
  "1.40.0", pydantic: "2.11.9"}`).
- Capture which of those versions actually matter (the LLM provider
  SDKs + pydantic; not, say, ffmpeg).
- Surface in the webapp.

This is small work compared to the prompts axis but requires a
decision about which SDKs count.

### 3. Models — mostly done; needs a hardening pass

Already recorded in `config.json:axes.generator` per the recent
backfill. Gaps:

- `params.yaml` may pin a generator id; the on-disk api_model may
  differ if `params.yaml` is edited later (the generator id is
  stable but the api_model behind it can change). Per-run should
  record the api_model + provider + hosting actually used, not just
  the generator id.
- Provider profile overrides + `--provider-override` flags should be
  captured per run (I believe they already are in `config.json` —
  needs verification).

### 4. Cross-cutting: propagation through run → SQL → webapp

Today's flow:

```
run produces config.json + phase{0,1,2,2_5,3}_*.json
       ↓
scripts/build_content_db.py reads selected fields → data/content.db
       ↓
enrichment.expdb scan reads run_manifest.json → data/experiments.db
       ↓
webapp/app.py reads content.db → renders run pages
webapp_v2/ reads experiments.db (and others?) → renders newer UI
```

For version metadata to reach the webapp, each step needs to be
extended:

1. The run-generation code writes version metadata into config.json
   (or a new `versions.json` adjacent to it).
2. `build_content_db.py` reads it, adds columns to `content.db`.
3. `enrichment.expdb` reads it, adds columns to `experiments.db`.
4. The webapp queries the new columns and renders them on run
   detail pages.

The two webapps have different sensibilities; both need touching.

## End-state vision

A reader visiting `webapp/run/bh_trn_literary_hostprep` (or its v2
equivalent) sees a "Versions" section showing:

- Model: anthropic/claude-sonnet-4-6 (api: claude-sonnet-4-6)
- Provider profile: production
- Schemas used: enrichment/llm/schemas.py @ 2026-05-18
- Prompts used: host_prep_prompts @ 2026-05-20, generation_prompts @ 2026-04-15
- SDKs at run time: anthropic 1.42.0, openai 1.40.0, pydantic 2.11.9
- pyproject.toml commit when run was made: abc12345

An engineer can answer:

- "Did this run use the same schemas that production currently uses?"
  → compare schema_version recorded in run vs current.
- "Did the prompt change between the two runs whose outputs differ?"
  → diff prompt versions across the two `config.json` files.
- "If I re-run today with the same schemas + prompts but a newer
  SDK, do the outputs differ?" → record the new run with the new
  SDK version; diff outputs.

## The epic, proposed

`BleakHouse-???` — Propagate version-pinning from source through
run artefacts, SQL, and webapps.

Five children, in dependency order:

1. **Prompts: audit + consolidate + version + changelog.** Mirror
   the schemas work but per-cluster (host_prep, generation,
   curation, segment-design, passage-enrichment). Decide one-file vs
   many during the spec phase. Writes `docs/prompts_changelog.md`
   and per-prompt version constants. Sibling of CLAUDE.md update.
2. **Run artefact: extend config.json with a complete versions
   block.** Schema versions, prompt versions, SDK versions, model
   ids actually used, pyproject.toml commit hash. New runs write
   it; backfill optional.
3. **SQL: extend content.db and experiments.db schemas to carry
   version columns.** Update the build/scan scripts. Backfill from
   existing runs (read config.json into the new columns).
4. **Webapp v1: surface versions on run detail pages.** Simple read
   from content.db; renders a "Versions" section.
5. **Webapp v2: same as 4 for the newer UI.** Same data, different
   templates.

Plus an optional sixth:

6. **Replay tooling: a CLI that takes a run id and re-runs it
   under the recorded versions** (for verifying major schema bumps
   or SDK upgrades). Heavy — defer unless we hit an actual need.

## Decisions sitting on the spec child (for the user)

1. **Prompts file layout: one file or per-cluster?** My lean:
   per-cluster (host_prep_prompts.py, generation_prompts.py, etc.) —
   prompts are mostly single-use; co-locating with their callers is
   readable.
2. **Which SDKs count as version-pinned?** Provider SDKs (anthropic,
   openai, cerebras, google-genai), pydantic, plus what else?
   Suggest: just those four.
3. **Per-run versions: in `config.json` or a new `versions.json`?**
   My lean: extend `config.json` with a `versions` block — fewer
   files, the version info IS part of the config.
4. **Backfill scope:** do we backfill SQL columns from existing
   runs (best effort — schemas+prompts known from git, SDKs would
   be a "from when the file was last modified" approximation), or
   leave older runs with NULL?
5. **Webapp work in v1, v2, or both?** Per CLAUDE.md the project
   runs both in parallel; both should learn this eventually but we
   could stage.

## Out of scope (for this epic; flag for later)

- Quality/preference judgement of how versions affect outputs. That
  belongs in the conformance suite (BleakHouse-8xfe) or in domain
  benchmarks like Tier L.
- Auto-detection of "did anything change?" between two runs. Useful
  but a separate piece of tooling.
- Migration of older saved-run artefacts to the new schema
  versions. Mostly handled by the backward-compat guarantee
  (extra='forbid' + saved-data already satisfies current schemas);
  major bumps would need their own migration scripts case-by-case.

## Relationship to other open work

- **BleakHouse-8xfe (adversarial conformance suite):** complementary.
  This epic captures versions; the conformance suite tests behaviour
  against them. Both should be running before we trust any "this
  schema/prompt is safe to bump" judgement.
- **BleakHouse-rosr (Leviathan trial):** orthogonal. The Leviathan
  trial may produce a run whose new-novel-onboarding prompts are
  Leviathan-specific; those prompts get version-pinned along with
  the others.
