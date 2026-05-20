# qwen-plus realtime chapter run — bleak_house/c32

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c32`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:33:14.055986+00:00
- wall: 132s

## Verdict

**PASS** — 7/7 chunks ok; 132/133 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 11,782
- output tokens: 45,279
- cost: $0.0590 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 118.3s | 2619 | 6498 | 19/20 | $0.0088 | stop | ok |
| `chunk_01` | ok | 132.5s | 1477 | 7243 | 20/20 | $0.0093 | stop | ok |
| `chunk_02` | ok | 130.7s | 1626 | 7139 | 20/20 | $0.0092 | stop | ok |
| `chunk_03` | ok | 116.4s | 1543 | 6343 | 20/20 | $0.0082 | stop | ok |
| `chunk_04` | ok | 128.7s | 1430 | 6993 | 20/20 | $0.0090 | stop | ok |
| `chunk_05` | ok | 125.1s | 1716 | 6833 | 20/20 | $0.0089 | stop | ok |
| `chunk_06` | ok | 78.9s | 1371 | 4230 | 13/13 | $0.0056 | stop | ok |