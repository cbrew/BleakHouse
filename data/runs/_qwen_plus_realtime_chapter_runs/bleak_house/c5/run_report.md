# qwen-plus realtime chapter run — bleak_house/c5

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c5`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:20:03.655908+00:00
- wall: 148s

## Verdict

**PASS** — 5/5 chunks ok; 98/99 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 10,727
- output tokens: 37,314
- cost: $0.0491 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 131.1s | 1947 | 7182 | 20/20 | $0.0094 | stop | ok |
| `chunk_01` | ok | 144.0s | 2506 | 7945 | 20/20 | $0.0105 | stop | ok |
| `chunk_02` | ok | 137.3s | 1970 | 7541 | 19/20 | $0.0098 | stop | ok |
| `chunk_03` | ok | 148.4s | 2505 | 8164 | 20/20 | $0.0108 | stop | ok |
| `chunk_04` | ok | 118.9s | 1799 | 6482 | 19/19 | $0.0085 | stop | ok |