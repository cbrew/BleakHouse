# qwen-plus realtime chapter run — bleak_house/c50

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c50`
- model: qwen-plus
- chunk_size: 20
- chunks: 4
- started: 2026-05-20T12:41:20.862568+00:00
- wall: 146s

## Verdict

**PASS** — 4/4 chunks ok; 74/75 paragraphs parsed.

## Numbers

- by_status: {'ok': 4}
- input tokens: 7,669
- output tokens: 28,441
- cost: $0.0372 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 131.6s | 1721 | 7214 | 20/20 | $0.0093 | stop | ok |
| `chunk_01` | ok | 146.1s | 3019 | 8064 | 20/20 | $0.0109 | stop | ok |
| `chunk_02` | ok | 137.1s | 1487 | 7529 | 19/20 | $0.0096 | stop | ok |
| `chunk_03` | ok | 103.0s | 1442 | 5634 | 15/15 | $0.0073 | stop | ok |