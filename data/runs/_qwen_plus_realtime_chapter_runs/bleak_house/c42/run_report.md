# qwen-plus realtime chapter run — bleak_house/c42

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c42`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:38:08.921216+00:00
- wall: 143s

## Verdict

**PASS** — 5/5 chunks ok; 80/81 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 6,910
- output tokens: 28,644
- cost: $0.0371 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 110.2s | 1993 | 6011 | 20/20 | $0.0080 | stop | ok |
| `chunk_01` | ok | 121.4s | 1500 | 6633 | 20/20 | $0.0086 | stop | ok |
| `chunk_02` | ok | 141.1s | 1447 | 7734 | 20/20 | $0.0099 | stop | ok |
| `chunk_03` | ok | 143.4s | 1375 | 7853 | 19/20 | $0.0100 | stop | ok |
| `chunk_04` | ok | 9.1s | 595 | 413 | 1/1 | $0.0007 | stop | ok |