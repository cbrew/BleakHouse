# qwen-plus realtime chapter run — bleak_house/c65

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c65`
- model: qwen-plus
- chunk_size: 20
- chunks: 4
- started: 2026-05-20T12:48:48.927436+00:00
- wall: 130s

## Verdict

**FAIL** — 4/4 chunks ok; 66/69 paragraphs parsed.

## Numbers

- by_status: {'ok': 4}
- input tokens: 6,306
- output tokens: 23,868
- cost: $0.0312 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 124.3s | 2125 | 6820 | 19/20 | $0.0090 | stop | ok |
| `chunk_01` | ok | 118.7s | 1936 | 6514 | 18/20 | $0.0086 | stop | ok |
| `chunk_02` | ok | 130.5s | 1375 | 7141 | 20/20 | $0.0091 | stop | ok |
| `chunk_03` | ok | 62.6s | 870 | 3393 | 9/9 | $0.0044 | stop | ok |