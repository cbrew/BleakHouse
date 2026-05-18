# Tier L (and Tier M-Sonnet) judge methodology

**Status:** decision, 2026-05-16. Resolves BleakHouse-bi7w; unblocks
BleakHouse-dll8 (Tier L prose benchmark) and BleakHouse-ubpm
(Tier M-Sonnet host_prep_brief benchmark).

## Decision

**Human inspection is primary for prose quality at this stage.** No LLM
judge for Tier L. The benchmark produces audio (and / or rendered
script) per candidate; a listener compares against the Sonnet 4.6
baseline directly.

LLM-as-judge for prose may become useful later — when the candidate
count grows beyond what a person can listen through, or when we want
a reproducible CI-style quality gate. Not today. The infrastructure
to support it is in place (`enrichment/llm/eval/judge.py` for Tier S
listener_pick) and can be extended when needed.

## Why human-primary now

Three things made the LLM-judge framing wrong at this stage:

1. **Candidate count is small.** Tier L benchmarks three open-weight
   candidates against one Sonnet baseline. Five episode samples per
   candidate. Twenty audio passages to listen to. That's a
   single-afternoon task for a listener, not the kind of N where
   reproducible automated scoring earns its complexity cost.

2. **The bias problem doesn't have a clean answer.** Sonnet-judges-Sonnet
   is biased one way; a cross-family judge (Gemini, Llama) is biased
   the other way; an ensemble is biased in a combined way. Every LLM
   judge introduces an interpretive framework that has to be defended.
   A listener listens. The output is a preference; the bias caveats
   are the listener's known taste, which is documented when results
   are reported.

3. **The 0rtg quality floor was already human.** The
   "≥45% blinded preference vs Sonnet" threshold from 0rtg was
   specified as a human listening test all along; the LLM-judge layer
   above it would have been a screen we don't yet need.

## Tier L protocol (prose comparison)

**Update 2026-05-17 (dll8 execution):** three protocol changes from
the original spec:

1. **Text, not audio.** Audio rendering is deferred — it adds wall
   time and TTS cost without changing the judgment signal (the
   comparison is about prose quality, fully captured in the script).
2. **Symmetric N-way, no presumed baseline.** Sonnet competes on
   equal footing with the open-weight candidates rather than being
   the "default to beat". All pairs of candidates are tested; each
   unordered pair is presented twice with sides swapped to control
   for left/right reading bias. There is no pass-threshold gate;
   the report is a ranking + consistency caveat, and the routing
   decision (BleakHouse-9k9n) weighs cost and other criteria on top.
3. **Panel adjustments.** gemma-4-26b-a4b was ruled out on
   structural grounds before the listener step (vLLM #40080 / PR
   #40099 Gemma 4 + xgrammar repetition-loop bug). gpt-5.4 was
   added 2026-05-17 as an additional candidate so we don't conflate
   "Sonnet vs open-weights" with "frontier-tier vs open-weights".
   Final panel of 5 listener-eligible candidates: **sonnet,
   gemma-4-31b, deepseek-v3-2, qwen3-235b-a22b, gpt-5-4**.

### Fixture

Per dll8: 5 prose-generation inputs sampled from `bh_trn_literary_hostprep_short`
and `wh_trn_literary_short`. For each input, produce four prose
outputs — Sonnet baseline plus three open-weight candidates. Originally
specified as Gemma 4 26B-A4B-it / Gemma 4 31B-it / DeepSeek-V3.2;
dll8 added qwen3-235b-a22b late, then 26B-A4B was eliminated for
structural reasons (vLLM #40080 / PR #40099 Gemma 4 + xgrammar
repetition-loop bug). Final panel: gemma-4-31b + deepseek-v3-2 +
qwen3-235b-a22b. 20 prose samples total (5 fixture × 4 sources).

### Schema validity (mechanical pre-check)

Before listening, the runner records schema validity per sample (does
the output parse as the expected Segment / Turn structure?). This is
the only automated gate: a candidate with <100% schema validity is
recorded as failing the tier on structural grounds and no listening
time is spent on it. Schema validity is cheap, reproducible, and
genuinely needs no judge.

### Blinded human preference (text, symmetric N-way)

With N=5 candidates on equal footing:

1. **All C(N,2) = 10 unordered candidate pairs per fixture entry.**
   With 5 fixture inputs × 10 pairs = 50 unordered pairs.
2. **Each unordered pair presented twice with sides swapped** — one
   presentation has model X as A and Y as B, the other has Y as A
   and X as B. Controls for order/position bias. **Total: 100
   ordered presentations.**
3. **pair_id labels are shuffled** under a recorded seed so the
   listener cannot infer fixture or model identity from the numeric
   order. The canonical (run_id, seg_idx, a_is, b_is) tuple per
   pair_id is recorded in the manifest.
4. **Strip identifying surface cues** before rendering:
   - Replace `title` with `[Segment N]` (Sonnet writes more
     elaborate titles than the open-weight candidates — diagnostic).
   - Render each turn as `**Speaker** (role): utterance text` only.
     Drop all TTS delivery metadata (rate, pause_*_ms,
     emphasis_words, passage_ref, sentence_type, quote_mode,
     is_quote) — none of that is prose signal and several fields
     correlate with model fingerprints.
5. **Persist the blinding manifest** in
   `data/eval/stage2_tier_l_prose/blinding_manifest.json`. The
   listener does not see this file during scoring; the scorer joins
   it with the listener's choices after the fact.
6. Listener reports preference per pair: A, B, or tie.
7. **No pass-threshold gate.** Output is a per-model ranking by
   win-rate over decided pairs, an order-bias check (% of A-
   preferences over decided trials), and a per-unordered-pair
   consistency report (did the two orderings agree on a winner?).
   Routing decisions (BleakHouse-9k9n) consume this alongside cost
   and other criteria.

### Running the listener session (Potato workflow)

The canonical workflow uses **Potato** — a Flask-based annotation web
UI built for this kind of pairwise task
(https://github.com/davidjurgens/potato; BleakHouse-kl4f epic). Compared
with the older "edit preferences.json by hand" path, Potato gives the
listener a proper A/B layout, keyboard shortcuts (1=A, 2=B, 0=tie),
sequential navigation with persisted progress, and a clean TSV export.

**Setup (one-time):**

```bash
cd tools/potato_listener && uv sync   # installs Potato in isolated venv
```

**Render the Potato-format pairs (after `render_eval_pairings.py`):**

```bash
uv run python scripts/render_eval_pairings_potato.py
# Produces data/eval/stage2_tier_l_prose/potato/pairs.jsonl
```

**Launch and annotate:**

```bash
bash scripts/start_potato_listener.sh        # port 9001 by default
# Open http://localhost:9001 — register a user the first time,
# then walk through the 100 pairs (1=A, 2=B, 0=tie).
```

**Score:**

```bash
uv run python scripts/score_eval_pairings_potato.py \
    --tsv data/eval/stage2_tier_l_prose/potato/annotation_output/exports/tsv/annotations.tsv
# Writes data/eval/stage2_tier_l_prose/preference_summary.json
```

The `/exports/tsv/` segment in the path above is hard-coded in
Potato's `user_state_management.py:_run_auto_export` and cannot be
moved upstream. See the scorer's docstring for full detail.

Scripts checked in for end-to-end auditability:

- `scripts/render_eval_pairings.py` — builds the blinding manifest
  + preferences.json template + per-pair markdown files (pre-Potato
  artefacts; the manifest is still consumed by the Potato renderer
  and scorer).
- `scripts/render_eval_pairings_potato.py` — emits pairs.jsonl from
  the manifest, reusing the same `_render_blind_segment` rules so
  the listener sees identical text either way.
- `data/eval/stage2_tier_l_prose/potato/config.yaml` — Potato config
  (annotation_type: pairwise, mode: binary, allow_tie: true, labels
  ["A", "B"]).
- `scripts/start_potato_listener.sh` — cd-and-launch wrapper that
  satisfies Potato's "config must live inside CWD" security check.
- `scripts/score_eval_pairings_potato.py` — reads the Potato TSV
  passed via `--tsv` (see "Why the scorer takes an explicit --tsv"
  below); emits preference_summary.json.

### Why the scorer takes an explicit `--tsv`

The scorer is a separate process from Potato, so the on-disk path
where Potato writes annotations is a contract between them. Potato
**does not include any built-in scoring, aggregation, win-rate, or
summary functionality for pairwise comparison annotations** (verbatim
from `docs/annotation-types/comparison/pairwise_annotation.md` on the
upstream master branch, fetched 2026-05-17), so this contract is
unavoidable. Three upstream alternatives were investigated and ruled
out before settling on "explicit TSV path argument":

- **Custom exporter** writing `preference_summary.json` directly:
  upstream supports `export_registry.register(MyExporter())` but has
  no config-time plugin discovery, so calling `register()` requires a
  launcher wrapper that imports Potato before `flask_server.main()`
  runs — fragile because any wrapper living inside
  `tools/potato_listener/.venv/` is wiped by `uv sync`.
- **Webhooks** (config-only wiring on `annotation.created`): requires
  running a long-lived HTTP receiver that owns scoring state. More
  machinery than a TSV.
- **`python -m potato.bws_scoring`**: only handles Best-Worst Scaling
  tuples, not pairwise A/B. Different annotation shape.

A previous iteration tried to derive the TSV path automatically by
reading `config.yaml` and appending Potato's hard-coded
`/exports/tsv/` suffix. It worked, but the indirection didn't earn
its keep. Making the path an explicit `--tsv` argument trades a few
characters of typing for zero hidden state — the caller can see what
file is being scored, and any future change to Potato's auto-export
layout is a one-line edit to the documented command.

The path to pass is always:

    data/eval/stage2_tier_l_prose/potato/annotation_output/exports/tsv/annotations.tsv

(driven by `export_annotation_format: tsv` in
`data/eval/stage2_tier_l_prose/potato/config.yaml`; the
`/exports/tsv/` segment is hard-coded in
`potato/user_state_management.py:_run_auto_export` and is NOT
configurable upstream).

If a candidate clears the threshold, its open-weight ModelSpec
becomes eligible for the per-task routing decision in BleakHouse-9k9n.
Eligibility ≠ promotion; the routing ticket still chooses the
production default. Anthropic Sonnet 4.6 remains the production
default for prose generation until 9k9n explicitly flips it.

### Recording

Per-pair record: `{pair_id, input_id, candidate_id, listener_choice,
note}`. Per-candidate summary: `{candidate_id, n_pairs, n_prefer_candidate,
n_prefer_baseline, n_no_preference, pass}`.

Files:
- `data/eval/stage2_tier_l_prose/blind_pairs/pair_<id>.md` —
  the rendered pair the listener reads.
- `data/eval/stage2_tier_l_prose/blinding_manifest.json` —
  pair_id → (run_id, seg_idx, candidate_id, A_is, B_is, rng_seed).
- `data/eval/stage2_tier_l_prose/preferences.json` — listener-filled
  pair_id → "A" | "B" | "tie".
- `data/eval/stage2_tier_l_prose/preference_summary.json` — scorer
  output, joins the above into per-candidate rolls.

The single listener is documented in `preference_summary.json` so
results carry the known-bias caveat.

### Panel disposition (dll8, 2026-05-17)

| candidate | first-try valid | listener eligible | notes |
|---|---|---|---|
| sonnet | 5/5 reused | yes | One candidate among many — not a privileged baseline (per the methodology correction above). |
| gemma-4-26b-a4b | 4/5 | **NO** | vLLM #40080 / PR #40099 — Gemma 4 + xgrammar repetition-loop bug. Opening-segment fail rate ~27% at default sampler; no mitigation worked (list_field_caps no-op, simpler directive no-op, frequency_penalty + stop + extra_body went 0/5). Re-probe when PR #40099 lands at DeepInfra. |
| gemma-4-31b | 5/5 | yes | Same bug family per #40080 but empirically much lower rate; flag for re-probing if routed to production. |
| deepseek-v3-2 | 5/5 | yes | |
| qwen3-235b-a22b | 5/5 | yes | Added to panel 2026-05-16. |
| gpt-5-4 | 5/5 | yes | Added to panel 2026-05-17 alongside the Sonnet-as-equal-candidate correction; OpenAI prose-tier frontier-quality pick at Sonnet-equivalent pricing (docs/openai_pipeline_plan.md). |

## Tier M-Sonnet protocol (host_prep_brief)

host_prep_brief is **structured intermediate output**, not audible
prose. Different judging shape.

### Fixture

Per ubpm: 5 real host_prep_brief inputs sampled from existing runs.
For each input, produce three brief outputs — Sonnet baseline plus
two candidates (Qwen 2.5-72B, DeepSeek-V3.2). 15 brief outputs total.

### Mechanical checks

- Schema validity (HostBrief parses; questions and
  cross_engagement_targets present): 100% required.
- Field-presence match against the baseline (no missing required
  fields where the baseline filled them): ≥95% per 0rtg's structured-output
  floor.

### Human inspection

The remaining quality questions — content depth, question quality,
cross-engagement coverage — are sample-by-sample human read of the 15
briefs. Same principle as Tier L: at this candidate count, a
reviewer reading 15 short structured outputs is more informative than
designing an LLM-judge rubric for them.

Pass threshold: reviewer's per-candidate verdict is `viable` or
`not viable`, with one-sentence rationale per sample. A candidate is
viable for routing if the reviewer rates ≥3 of 5 samples as
"as-good-as-baseline-or-better." Subjective; the reviewer's identity
and rationale are recorded.

### Recording

Files at `data/eval/stage2_tier_m_sonnet_host_prep_brief/<candidate_id>/inspection.json`
with per-sample reviewer notes and a roll-up summary.

## When LLM-judge would change this

A future where LLM-judge matters:

- Candidate count grows past ~6–8 (multi-provider × multi-model
  sweep, e.g. evaluating 12 candidates across DeepInfra + Together +
  Cerebras + Modal-vLLM combinations).
- We want a CI-style regression check that flags routing-default
  candidates whose quality drifts after a model-version bump.
- We add a "panel-style" axis where listener-pick-style picks are
  scored on dialogue dimensions and 20 picks per evaluation makes
  human review impractical.

When that happens, the Tier S judge (`enrichment/llm/eval/judge.py`)
is the obvious starting point — extend it with the multi-criterion
rubric + cross-family ensemble that was originally proposed in this
doc's earlier draft. Until then, the listener is the judge.

## See also

- `enrichment/llm/eval/judge.py` — Tier S judge (LLM-based, kept for
  listener_pick where the rubric is mechanical enough).
- `data/eval/stage2_tier_s_listener_pick/` — precedent for the eval
  persistence layout.
- bd: BleakHouse-dll8 (Tier L prose), BleakHouse-ubpm (Tier
  M-Sonnet host_prep_brief), BleakHouse-1aav (Tier S precedent),
  BleakHouse-0rtg (quality floors), BleakHouse-9k9n (per-task routing
  decision — final default-flip step).
