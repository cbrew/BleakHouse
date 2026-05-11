# BleakHouse

Research project that turns Victorian novels — *Bleak House* foremost
among them — into structured podcast scripts via LLM-driven literary
analysis, then renders them to audio. A hand-rolled phase-based
pipeline (`enrichment/run_pipeline.py`) drives Anthropic/Gemini/OpenAI
structured-output calls, persists per-run artefacts as JSON in
`data/runs/`, and rolls up into a single `data/content.db` for the
FastAPI webapp. Audio bytes are stored in R2 via a small
content-addressed store (`cas/`).

The companion docs in [`CLAUDE.md`](./CLAUDE.md) are the deep reference
for architecture, gotchas, and the `bd` (beads) issue-tracker workflow.

## Quickstart (clone → working system)

System deps: `git`, `python` 3.13+, [`uv`](https://astral.sh/uv),
`ffmpeg`, [`bd`](https://github.com/steveyegge/beads). On Debian /
Ubuntu:

```bash
sudo apt install git ffmpeg
curl -LsSf https://astral.sh/uv/install.sh | sh
go install github.com/steveyegge/beads/cmd/bd@latest   # or your usual route
```

Then:

```bash
git clone https://github.com/cbrew/BleakHouse.git
cd BleakHouse
cp .env.example .env
chmod u+w .env && $EDITOR .env && chmod u-w .env       # paste keys; edit/comment BLEAKHOUSE_CAS_ROOT
bash scripts/bootstrap.sh                              # uv sync × 2 + playwright + bd hooks/import + ffmpeg probe
# bash scripts/bootstrap.sh --pull-cas                 # also prefetch ~7 GB CAS bytes from R2 (optional)
bd ready                                               # see what's queued
```

`.env` carries LLM keys (Anthropic / Gemini / OpenAI / Cerebras), the
research-API keys, R2 credentials for `cas.store.{push, pull}`, and
the per-machine `BLEAKHOUSE_CAS_ROOT` override. See
[`.env.example`](./.env.example) for the full annotated template and
the per-machine conventions for `BLEAKHOUSE_CAS_ROOT`.

After bootstrap:

```bash
uv run uvicorn webapp.app:app --reload --port 8080     # webapp + audio player
```

Audio bytes 302-redirect to R2 unless you ran `--pull-cas`; either
path serves the same content.

## Issue tracker

The `bd` issue tree (issues, dependencies, persistent memories) is
committed at `.beads/issues.jsonl`, so a fresh clone sees the full
history. `bash scripts/bootstrap.sh` step 5/6 runs `bd hooks install`
+ `bd import` to wire it up locally. See the **Beads state in git**
section in [`CLAUDE.md`](./CLAUDE.md) for the rationale (why we run
in non-stealth mode, what's tracked vs ignored).

## Project layout

- `webapp/` — FastAPI + uvicorn audio-player webapp (deployed on Fly)
- `enrichment/` — pipeline modules: segment / Phase 0–4 / TTS profiles
- `cas/` — content-addressed store: `put` / `pull` / `push` over R2
- `tools/forced_align/` — separate uv subproject; whisperx-aligned
  per-turn timing for legacy mp3 runs
- `scripts/` — operator entry points: `add_novel.sh`, `deploy_demo.sh`,
  `cas_migrate.py`, `bootstrap.sh`
- `data/runs/<run_id>/` — per-run pipeline outputs (Phase 0 → 3 JSON,
  audio manifests, host-prep transcripts and briefs); committed in git
- `data/novels/<novel_id>/` — per-novel enrichment artefacts
  (`passages_enriched.json`, clusters, etc.)

## License

Research code; not currently licensed for redistribution. See the
project owner.
