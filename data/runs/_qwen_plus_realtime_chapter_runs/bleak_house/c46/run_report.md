# qwen-plus realtime chapter run — bleak_house/c46

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c46`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:39:14.060292+00:00
- wall: 136s

## Verdict

**PASS** — 5/5 chunks ok; 88/89 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 7,773
- output tokens: 31,718
- cost: $0.0412 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 125.7s | 1931 | 6896 | 19/20 | $0.0090 | stop | ok |
| `chunk_01` | ok | 136.4s | 1771 | 7463 | 20/20 | $0.0097 | stop | ok |
| `chunk_02` | ok | 122.9s | 1670 | 6700 | 20/20 | $0.0087 | stop | ok |
| `chunk_03` | ok | 133.5s | 1282 | 7298 | 20/20 | $0.0093 | stop | ok |
| `chunk_04` | ok | 62.2s | 1119 | 3361 | 9/9 | $0.0045 | stop | ok |