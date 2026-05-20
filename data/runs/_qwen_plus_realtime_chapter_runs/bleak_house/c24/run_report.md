# qwen-plus realtime chapter run — bleak_house/c24

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c24`
- model: qwen-plus
- chunk_size: 20
- chunks: 8
- started: 2026-05-20T12:29:03.048757+00:00
- wall: 143s

## Verdict

**PASS** — 8/8 chunks ok; 155/156 paragraphs parsed.

## Numbers

- by_status: {'ok': 8}
- input tokens: 15,014
- output tokens: 54,964
- cost: $0.0720 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 128.9s | 2242 | 7063 | 19/20 | $0.0094 | stop | ok |
| `chunk_01` | ok | 142.6s | 2127 | 7821 | 20/20 | $0.0102 | stop | ok |
| `chunk_02` | ok | 125.3s | 1198 | 6869 | 20/20 | $0.0087 | stop | ok |
| `chunk_03` | ok | 121.8s | 1379 | 6664 | 20/20 | $0.0085 | stop | ok |
| `chunk_04` | ok | 135.4s | 2422 | 7375 | 20/20 | $0.0098 | stop | ok |
| `chunk_05` | ok | 115.5s | 1671 | 6323 | 20/20 | $0.0083 | stop | ok |
| `chunk_06` | ok | 129.2s | 2197 | 7072 | 20/20 | $0.0094 | stop | ok |
| `chunk_07` | ok | 105.6s | 1778 | 5777 | 16/16 | $0.0076 | stop | ok |