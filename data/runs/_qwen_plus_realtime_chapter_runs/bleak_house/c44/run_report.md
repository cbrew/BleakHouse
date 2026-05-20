# qwen-plus realtime chapter run — bleak_house/c44

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c44`
- model: qwen-plus
- chunk_size: 20
- chunks: 3
- started: 2026-05-20T12:38:54.490209+00:00
- wall: 145s

## Verdict

**FAIL** — 3/3 chunks ok; 56/58 paragraphs parsed.

## Numbers

- by_status: {'ok': 3}
- input tokens: 5,737
- output tokens: 21,188
- cost: $0.0277 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 123.4s | 1575 | 6791 | 19/20 | $0.0088 | stop | ok |
| `chunk_01` | ok | 144.9s | 2501 | 7994 | 20/20 | $0.0106 | stop | ok |
| `chunk_02` | ok | 117.0s | 1661 | 6403 | 17/18 | $0.0083 | stop | ok |