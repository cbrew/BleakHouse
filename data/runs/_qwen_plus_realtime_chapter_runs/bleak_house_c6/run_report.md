# qwen-plus realtime chapter run — bleak_house/c6

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house_c6`
- model: qwen-plus
- chunk_size: 20
- chunks: 8
- started: 2026-05-20T11:01:25.963087+00:00
- wall: 140s

## Verdict

**PASS** — 8/8 chunks ok; 158/158 paragraphs parsed.

## Numbers

- by_status: {'ok': 8}
- input tokens: 16,754
- output tokens: 58,117
- cost: $0.0764 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 139.7s | 2630 | 7525 | 20/20 | $0.0101 | stop | ok |
| `chunk_01` | ok | 131.2s | 1231 | 7183 | 20/20 | $0.0091 | stop | ok |
| `chunk_02` | ok | 129.3s | 2632 | 7022 | 20/20 | $0.0095 | stop | ok |
| `chunk_03` | ok | 138.5s | 2944 | 7531 | 20/20 | $0.0102 | stop | ok |
| `chunk_04` | ok | 135.5s | 1956 | 7412 | 20/20 | $0.0097 | stop | ok |
| `chunk_05` | ok | 136.1s | 1653 | 7447 | 20/20 | $0.0096 | stop | ok |
| `chunk_06` | ok | 125.5s | 1960 | 6841 | 20/20 | $0.0090 | stop | ok |
| `chunk_07` | ok | 131.7s | 1748 | 7156 | 18/18 | $0.0093 | stop | ok |