# qwen-plus realtime chapter run — bleak_house/c7

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c7`
- model: qwen-plus
- chunk_size: 20
- chunks: 4
- started: 2026-05-20T12:21:39.631138+00:00
- wall: 147s

## Verdict

**PASS** — 4/4 chunks ok; 72/72 paragraphs parsed.

## Numbers

- by_status: {'ok': 4}
- input tokens: 8,153
- output tokens: 26,407
- cost: $0.0349 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 146.7s | 3293 | 8045 | 20/20 | $0.0110 | stop | ok |
| `chunk_01` | ok | 123.8s | 1828 | 6801 | 20/20 | $0.0089 | stop | ok |
| `chunk_02` | ok | 131.3s | 2100 | 7210 | 20/20 | $0.0095 | stop | ok |
| `chunk_03` | ok | 79.8s | 932 | 4351 | 12/12 | $0.0056 | stop | ok |