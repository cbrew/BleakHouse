# qwen-plus realtime chapter run — bleak_house/c17

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c17`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:26:10.306360+00:00
- wall: 140s

## Verdict

**PASS** — 7/7 chunks ok; 128/128 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 11,758
- output tokens: 46,162
- cost: $0.0601 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 124.1s | 1973 | 6810 | 20/20 | $0.0090 | stop | ok |
| `chunk_01` | ok | 125.1s | 1488 | 6863 | 20/20 | $0.0088 | stop | ok |
| `chunk_02` | ok | 139.1s | 1625 | 7587 | 20/20 | $0.0098 | stop | ok |
| `chunk_03` | ok | 139.6s | 2131 | 7551 | 20/20 | $0.0099 | stop | ok |
| `chunk_04` | ok | 129.7s | 1681 | 7150 | 20/20 | $0.0093 | stop | ok |
| `chunk_05` | ok | 136.8s | 1989 | 7446 | 20/20 | $0.0097 | stop | ok |
| `chunk_06` | ok | 51.9s | 871 | 2755 | 8/8 | $0.0037 | stop | ok |