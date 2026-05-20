# qwen-plus realtime chapter run — bleak_house/c63

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c63`
- model: qwen-plus
- chunk_size: 20
- chunks: 3
- started: 2026-05-20T12:47:57.519937+00:00
- wall: 152s

## Verdict

**PASS** — 3/3 chunks ok; 58/59 paragraphs parsed.

## Numbers

- by_status: {'ok': 3}
- input tokens: 5,673
- output tokens: 21,090
- cost: $0.0276 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 113.0s | 1605 | 6200 | 19/20 | $0.0081 | stop | ok |
| `chunk_01` | ok | 152.2s | 2213 | 8348 | 20/20 | $0.0109 | stop | ok |
| `chunk_02` | ok | 119.5s | 1855 | 6542 | 19/19 | $0.0086 | stop | ok |