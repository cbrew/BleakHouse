# qwen-plus realtime chapter run — bleak_house/c20

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c20`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:26:46.018751+00:00
- wall: 147s

## Verdict

**PASS** — 7/7 chunks ok; 125/126 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,329
- output tokens: 46,325
- cost: $0.0605 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 125.7s | 1992 | 6920 | 19/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 133.1s | 2052 | 7292 | 20/20 | $0.0096 | stop | ok |
| `chunk_02` | ok | 124.3s | 1539 | 6754 | 20/20 | $0.0087 | stop | ok |
| `chunk_03` | ok | 129.9s | 1454 | 7127 | 20/20 | $0.0091 | stop | ok |
| `chunk_04` | ok | 146.8s | 2122 | 8075 | 20/20 | $0.0105 | stop | ok |
| `chunk_05` | ok | 141.2s | 1418 | 7760 | 20/20 | $0.0099 | stop | ok |
| `chunk_06` | ok | 44.8s | 1752 | 2397 | 6/6 | $0.0036 | stop | ok |