# forced_align

One-shot migration tool: cuts legacy `podcast.mp3` runs into per-turn shards by forced-aligning the rendered audio against the script in `phase3_episode.json`. See `docs/superpowers/specs/2026-05-05-forced-alignment-shards-design.md`.

## Setup

Has its own venv (heavy torch deps; never deployed to Fly):

```bash
cd tools/forced_align
uv sync --all-extras
```

## Usage

```bash
uv run -m forced_align --run bh_trn_literary_hostprep
uv run -m forced_align --all
uv run -m forced_align --run X --force   # overwrite existing shards
```
