# qwen-plus realtime chapter run — bleak_house/c62

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c62`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:47:37.556326+00:00
- wall: 143s

## Verdict

**PASS** — 5/5 chunks ok; 92/93 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 7,910
- output tokens: 34,066
- cost: $0.0440 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 121.3s | 1496 | 6639 | 19/20 | $0.0086 | stop | ok |
| `chunk_01` | ok | 139.1s | 1647 | 7648 | 20/20 | $0.0098 | stop | ok |
| `chunk_02` | ok | 143.4s | 2040 | 7852 | 20/20 | $0.0102 | stop | ok |
| `chunk_03` | ok | 136.6s | 1517 | 7472 | 20/20 | $0.0096 | stop | ok |
| `chunk_04` | ok | 82.7s | 1210 | 4455 | 13/13 | $0.0058 | stop | ok |