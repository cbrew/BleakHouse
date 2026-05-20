# qwen-plus realtime chapter run — bleak_house/c43

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c43`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:38:38.208894+00:00
- wall: 146s

## Verdict

**PASS** — 7/7 chunks ok; 129/130 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,704
- output tokens: 48,172
- cost: $0.0629 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 127.9s | 2039 | 6993 | 20/20 | $0.0092 | stop | ok |
| `chunk_01` | ok | 135.4s | 2002 | 7399 | 20/20 | $0.0097 | stop | ok |
| `chunk_02` | ok | 135.4s | 2239 | 7422 | 20/20 | $0.0098 | stop | ok |
| `chunk_03` | ok | 139.3s | 2211 | 7598 | 20/20 | $0.0100 | stop | ok |
| `chunk_04` | ok | 145.6s | 1925 | 8005 | 20/20 | $0.0104 | stop | ok |
| `chunk_05` | ok | 129.7s | 1211 | 7141 | 19/20 | $0.0091 | stop | ok |
| `chunk_06` | ok | 66.1s | 1077 | 3614 | 10/10 | $0.0048 | stop | ok |