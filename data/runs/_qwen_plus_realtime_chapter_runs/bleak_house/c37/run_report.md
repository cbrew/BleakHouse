# qwen-plus realtime chapter run — bleak_house/c37

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c37`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:35:26.518475+00:00
- wall: 162s

## Verdict

**FAIL** — 7/7 chunks ok; 125/130 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,930
- output tokens: 46,484
- cost: $0.0610 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 117.3s | 1908 | 6426 | 17/20 | $0.0085 | stop | ok |
| `chunk_01` | ok | 118.4s | 1225 | 6474 | 19/20 | $0.0083 | stop | ok |
| `chunk_02` | ok | 141.3s | 2434 | 7430 | 20/20 | $0.0099 | stop | ok |
| `chunk_03` | ok | 131.9s | 2012 | 6920 | 19/20 | $0.0091 | stop | ok |
| `chunk_04` | ok | 125.1s | 1648 | 6853 | 20/20 | $0.0089 | stop | ok |
| `chunk_05` | ok | 162.4s | 2354 | 8574 | 20/20 | $0.0112 | stop | ok |
| `chunk_06` | ok | 76.4s | 1349 | 3807 | 10/10 | $0.0051 | stop | ok |