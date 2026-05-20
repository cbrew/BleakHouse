# qwen-plus realtime chapter run — bleak_house/c61

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c61`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:46:30.059729+00:00
- wall: 143s

## Verdict

**PASS** — 5/5 chunks ok; 81/82 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 8,499
- output tokens: 29,717
- cost: $0.0391 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 131.1s | 1836 | 7234 | 19/20 | $0.0094 | stop | ok |
| `chunk_01` | ok | 135.5s | 2176 | 7392 | 20/20 | $0.0097 | stop | ok |
| `chunk_02` | ok | 142.9s | 2492 | 7831 | 20/20 | $0.0104 | stop | ok |
| `chunk_03` | ok | 117.7s | 1296 | 6400 | 20/20 | $0.0082 | stop | ok |
| `chunk_04` | ok | 17.0s | 699 | 860 | 2/2 | $0.0013 | stop | ok |