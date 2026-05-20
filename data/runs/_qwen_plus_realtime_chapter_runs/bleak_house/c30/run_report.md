# qwen-plus realtime chapter run — bleak_house/c30

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c30`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:31:42.463257+00:00
- wall: 146s

## Verdict

**PASS** — 6/6 chunks ok; 118/118 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 12,409
- output tokens: 43,968
- cost: $0.0577 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 124.6s | 1808 | 6796 | 20/20 | $0.0089 | stop | ok |
| `chunk_01` | ok | 142.5s | 2002 | 7793 | 20/20 | $0.0102 | stop | ok |
| `chunk_02` | ok | 133.9s | 2563 | 7301 | 20/20 | $0.0098 | stop | ok |
| `chunk_03` | ok | 130.5s | 1996 | 7157 | 20/20 | $0.0094 | stop | ok |
| `chunk_04` | ok | 146.3s | 2667 | 8026 | 20/20 | $0.0107 | stop | ok |
| `chunk_05` | ok | 125.7s | 1373 | 6895 | 18/18 | $0.0088 | stop | ok |