# qwen-plus realtime chapter run — bleak_house/c34

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c34`
- model: qwen-plus
- chunk_size: 20
- chunks: 8
- started: 2026-05-20T12:34:03.215684+00:00
- wall: 138s

## Verdict

**PASS** — 8/8 chunks ok; 148/150 paragraphs parsed.

## Numbers

- by_status: {'ok': 8}
- input tokens: 13,479
- output tokens: 52,858
- cost: $0.0688 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.5s | 1427 | 7118 | 19/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 130.8s | 2100 | 7214 | 19/20 | $0.0095 | stop | ok |
| `chunk_02` | ok | 137.6s | 2025 | 7511 | 20/20 | $0.0098 | stop | ok |
| `chunk_03` | ok | 125.9s | 1449 | 6868 | 20/20 | $0.0088 | stop | ok |
| `chunk_04` | ok | 117.8s | 1596 | 6465 | 20/20 | $0.0084 | stop | ok |
| `chunk_05` | ok | 132.4s | 1806 | 7256 | 20/20 | $0.0094 | stop | ok |
| `chunk_06` | ok | 126.2s | 1953 | 6910 | 20/20 | $0.0091 | stop | ok |
| `chunk_07` | ok | 65.0s | 1123 | 3516 | 10/10 | $0.0047 | stop | ok |