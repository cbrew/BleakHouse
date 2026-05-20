# qwen-plus realtime chapter run — bleak_house/c41

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c41`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:36:44.954004+00:00
- wall: 149s

## Verdict

**PASS** — 5/5 chunks ok; 89/89 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 7,520
- output tokens: 31,562
- cost: $0.0409 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 120.4s | 1640 | 6637 | 20/20 | $0.0086 | stop | ok |
| `chunk_01` | ok | 115.4s | 1509 | 6333 | 20/20 | $0.0082 | stop | ok |
| `chunk_02` | ok | 128.0s | 1550 | 7011 | 20/20 | $0.0090 | stop | ok |
| `chunk_03` | ok | 149.1s | 1415 | 8185 | 20/20 | $0.0104 | stop | ok |
| `chunk_04` | ok | 62.1s | 1406 | 3396 | 9/9 | $0.0046 | stop | ok |