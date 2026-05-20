# qwen-plus realtime chapter run — bleak_house/c16

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c16`
- model: qwen-plus
- chunk_size: 20
- chunks: 4
- started: 2026-05-20T12:24:57.421105+00:00
- wall: 133s

## Verdict

**FAIL** — 4/4 chunks ok; 72/74 paragraphs parsed.

## Numbers

- by_status: {'ok': 4}
- input tokens: 7,089
- output tokens: 26,657
- cost: $0.0348 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.9s | 3593 | 7145 | 20/20 | $0.0100 | stop | ok |
| `chunk_01` | ok | 133.0s | 1090 | 7318 | 20/20 | $0.0092 | stop | ok |
| `chunk_02` | ok | 131.6s | 1066 | 7200 | 19/20 | $0.0091 | stop | ok |
| `chunk_03` | ok | 92.5s | 1340 | 4994 | 13/14 | $0.0065 | stop | ok |