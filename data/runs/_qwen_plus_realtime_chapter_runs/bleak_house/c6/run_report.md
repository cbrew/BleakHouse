# qwen-plus realtime chapter run — bleak_house/c6

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c6`
- model: qwen-plus
- chunk_size: 20
- chunks: 8
- started: 2026-05-20T12:21:26.437641+00:00
- wall: 142s

## Verdict

**PASS** — 8/8 chunks ok; 157/158 paragraphs parsed.

## Numbers

- by_status: {'ok': 8}
- input tokens: 16,754
- output tokens: 57,912
- cost: $0.0762 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 122.1s | 2630 | 6692 | 20/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 133.5s | 1231 | 7376 | 20/20 | $0.0093 | stop | ok |
| `chunk_02` | ok | 132.0s | 2632 | 7190 | 20/20 | $0.0097 | stop | ok |
| `chunk_03` | ok | 126.4s | 2944 | 6895 | 20/20 | $0.0095 | stop | ok |
| `chunk_04` | ok | 138.6s | 1956 | 7519 | 20/20 | $0.0098 | stop | ok |
| `chunk_05` | ok | 142.4s | 1653 | 7684 | 20/20 | $0.0099 | stop | ok |
| `chunk_06` | ok | 133.3s | 1960 | 7230 | 19/20 | $0.0095 | stop | ok |
| `chunk_07` | ok | 134.0s | 1748 | 7326 | 18/18 | $0.0095 | stop | ok |