# qwen-plus realtime chapter run — bleak_house/c40

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c40`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:36:29.700780+00:00
- wall: 145s

## Verdict

**PASS** — 5/5 chunks ok; 98/99 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 9,306
- output tokens: 36,312
- cost: $0.0473 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 136.2s | 3068 | 7450 | 20/20 | $0.0102 | stop | ok |
| `chunk_01` | ok | 124.4s | 1540 | 6848 | 19/20 | $0.0088 | stop | ok |
| `chunk_02` | ok | 129.1s | 1349 | 7065 | 20/20 | $0.0090 | stop | ok |
| `chunk_03` | ok | 129.7s | 1356 | 7040 | 20/20 | $0.0090 | stop | ok |
| `chunk_04` | ok | 144.8s | 1993 | 7909 | 19/19 | $0.0103 | stop | ok |