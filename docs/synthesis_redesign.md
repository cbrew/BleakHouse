# Webapp redesign: surfacing TTS synthesis as an axis

Recorded after the Qwen renders shipped (PR #2) but before any UI work. This doc describes
the current state, the shape of the gap, and the redesign in three tiers — small enough that
each tier can ship on its own and each leaves the app in a working state.

## Current state, by user journey

The app is laid out around **generation** axes: novel × pipeline × panel × hostprep ×
generator (the LLM that produced the script). Synthesis (the TTS engine that produced the
audio) is not represented.

| # | Journey | Today |
|---|---|---|
| **J1** | Land at `/`, get oriented | Static landing page; links to `/tracker`. Fine. |
| **J2** | Browse the matrix at `/tracker` | 18-column grid (3 pipelines × 6 panel/hostprep combinations). Cell shows quote-verification rate + ♫ if any audio exists. **No synthesis indicator.** Top-level "Generator:" dropdown filters by LLM; nothing similar for TTS. |
| **J3** | Read a run's report | `/report/<id>` works. |
| **J4** | Read a run's script | `/script/<id>` works. |
| **J5** | Listen to a run | `/player?run=<id>`. Default version is `classic` (Gemini). |
| **J6** | Switch the synthesis engine on a run | Pills inside `/player`. Hidden when `available_versions.length <= 1` — which broke reaching Qwen on 2 of the 3 Qwen-rendered runs (`bh_trn_literary_hostprep` had 'qwen' in the list but not 'classic'; `bh_trn_alternatives_hostprep` had only 'qwen' and was hidden entirely). **Tier 1 fix in flight.** |
| **J7** | Compare versions of the same script | `/versions` exists but compares **script-name-suffix versions** (`v1.0`, `v1.1`, …) — not synthesis variants. Two different things share the word "version" in this code. |
| **J8** | Find runs that have Qwen | Nowhere. No way to filter or browse by synthesis. |
| **J9** | See host prep | `/prep?run=<id>` — works, orthogonal to synthesis. |
| **J10–J13** | About / blog / metrics / examples | Static pages. Should re-check internal links after the recent transparency-blog edit. |

The most important holes for a Qwen-aware user are **J2** (no badge), **J6** (broken — Tier 1
addresses), and **J8** (doesn't exist).

## Why this happened

The audio code grew up around a single rendering convention (`podcast.mp3` + `manifest.json`
in the run's audio dir). When Qwen was introduced, we added profile-suffix files
(`podcast_<profile>.mp3` + `manifest_<profile>.json`) but the **discovery** of "what's
playable" was still keyed on classic file presence. Three different broken states arose
because the convention's invariants only loosely matched what's actually on disk.

Beyond the discovery bug, **the matrix has no dimension for synthesis** at all. The user can
filter by which LLM generated the script but cannot ask "which runs have Qwen audio". The
data model treats synthesis as a renaming convention rather than a first-class axis.

## Tier 1 — discovery + player UX (in flight)

Goal: make the existing UI honest. Land what we already have without introducing new
concepts.

1. **`_available_versions`** detects from audio file presence (`podcast.mp3` for `'classic'`,
   `podcast_<X>.mp3` paired with `manifest_<X>.json` for `'<X>'`). No more "manifest must
   exist in audio dir to be reachable".
2. **`has_audio`** uses the same rule (`bool(_available_versions(run_id))`). Cells light up
   ♫ if *any* synthesis exists, not just classic.
3. **Player switcher** shows pills whenever there's ≥1 version (was: hide at ≤1). Single-pill
   case acts as a label telling the user which engine they're hearing.
4. **Player fallback**: if `?version=<X>` is requested but X isn't in `available_versions`,
   silently load the first available and update the URL.

**Status**: implemented in this branch; needs Playwright verification (the browser kept
serving cached `player.js` even after `Cache-Control: no-store` fetches; cache-busting via a
versioned query string in the script tag is what'll make this test reliably).

**What this doesn't fix**: matrix still doesn't tell you which runs have Qwen until you click
into one.

## Tier 2 — synthesis as a first-class axis

Goal: parity between "generator" (already a top-level filter) and "synthesis" (currently
hidden).

1. **Top-level synthesis selector** at `/tracker`, next to the existing Generator dropdown:
   `Synthesis: [Any | Gemini classic | Qwen]`. Cells show ♫ only for runs that have audio
   matching the selection. `Any` keeps current behaviour.
2. **Per-cell synthesis badge** in addition to ♫ — a small `G`, `Q`, or `G+Q` letter so the
   info is visible without changing the filter.
3. **`run_id_audio` index** in `runs.yaml` becomes per-synthesis: `run_ids_audio_classic`,
   `run_ids_audio_qwen`, etc. (Already partly there with `run_ids_qwen_audio`.) Driven by
   filesystem inspection in `generate_runs_yaml.py`.
4. **Matrix data API** (`/tracker/data`) gains a per-cell `synthesis: ['gemini', 'qwen']`
   field. The frontend uses it for the badge and the filter.

**Status**: not started. Estimated ~150 lines across `webapp/app.py` (data model + UI),
`scripts/generate_runs_yaml.py` (per-synthesis indices), and the tracker JS in `app.py`.

**What this doesn't fix**: comparing the same run's Gemini vs Qwen requires switching pills
inside the player; no side-by-side.

## Tier 3 — first-class synthesis comparison

Goal: a dedicated page where users can listen to the **same script** rendered with different
TTS engines, side by side, sharing scrub state.

1. **`/compare?run=<id>`** new page. Two (or more) audio columns, each with its own
   waveform/playhead but a shared "play from this paragraph" trigger.
2. **Diff highlighting**: paragraphs where the two manifests have different
   `audio_seconds` get a small marker — useful for spotting drift between engines.
3. **Linked from `/player`** ("Compare with Qwen →") and from the tracker cell when both
   engines are available.

**Status**: not started. ~half a day. Real value but not on the critical path; a power-user
view.

## Cross-cutting hygiene

These come up regardless of tier:

- **Rename the URL `/versions`** to `/script-versions` or fold into `/tracker` itself —
  reusing "versions" for both script-name-suffix and synthesis is the same overload that
  caused the J6 bug.
- **Cache-bust static assets** by appending a query string with the git short-SHA to the
  script tags in player.html / tracker.html. Otherwise tests-via-Playwright are unreliable
  and so is anyone visiting after a deploy.
- **Audit every page's internal links** after the recent transparency-blog "next post" edit;
  one already pointed elsewhere. Trivial diff but easy to leave bitrotting.

## Recommendation

Ship Tier 1 (~landing today, post user verification). Ship Tier 2 next (the cell badge alone
is high value). Ship Tier 3 only if a user explicitly asks for cross-engine comparison.

The hygiene items (rename, cache-bust, link audit) are worth doing in the Tier 1 PR — they're
small and prevent the same class of bug in future iterations.
