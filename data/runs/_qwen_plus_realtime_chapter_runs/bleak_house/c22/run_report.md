# qwen-plus realtime chapter run — bleak_house/c22

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c22`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:28:29.949927+00:00
- wall: 140s

## Verdict

**FAIL** — 7/7 chunks ok; 135/139 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 11,506
- output tokens: 48,256
- cost: $0.0625 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 139.6s | 2044 | 7683 | 20/20 | $0.0100 | stop | ok |
| `chunk_01` | ok | 139.6s | 1695 | 7623 | 20/20 | $0.0098 | stop | ok |
| `chunk_02` | ok | 116.0s | 2089 | 6345 | 18/20 | $0.0084 | stop | ok |
| `chunk_03` | ok | 105.4s | 1084 | 5764 | 19/20 | $0.0074 | stop | ok |
| `chunk_04` | ok | 130.8s | 1902 | 7176 | 20/20 | $0.0094 | stop | ok |
| `chunk_05` | ok | 131.7s | 1347 | 7199 | 20/20 | $0.0092 | stop | ok |
| `chunk_06` | ok | 118.2s | 1345 | 6466 | 18/19 | $0.0083 | stop | ok |