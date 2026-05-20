# qwen-plus realtime chapter run — bleak_house/c10

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c10`
- model: qwen-plus
- chunk_size: 20
- chunks: 4
- started: 2026-05-20T12:22:32.084096+00:00
- wall: 145s

## Verdict

**PASS** — 4/4 chunks ok; 71/71 paragraphs parsed.

## Numbers

- by_status: {'ok': 4}
- input tokens: 8,482
- output tokens: 26,201
- cost: $0.0348 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 142.0s | 4063 | 7781 | 20/20 | $0.0110 | stop | ok |
| `chunk_01` | ok | 145.3s | 1623 | 7955 | 20/20 | $0.0102 | stop | ok |
| `chunk_02` | ok | 118.9s | 1442 | 6491 | 20/20 | $0.0084 | stop | ok |
| `chunk_03` | ok | 74.9s | 1354 | 3974 | 11/11 | $0.0053 | stop | ok |