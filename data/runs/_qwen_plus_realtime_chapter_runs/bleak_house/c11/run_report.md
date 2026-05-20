# qwen-plus realtime chapter run — bleak_house/c11

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c11`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:23:48.891521+00:00
- wall: 141s

## Verdict

**PASS** — 6/6 chunks ok; 101/101 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,680
- output tokens: 34,919
- cost: $0.0466 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 121.5s | 1332 | 6669 | 20/20 | $0.0085 | stop | ok |
| `chunk_01` | ok | 125.2s | 1663 | 6892 | 20/20 | $0.0089 | stop | ok |
| `chunk_02` | ok | 124.5s | 2446 | 6773 | 20/20 | $0.0091 | stop | ok |
| `chunk_03` | ok | 141.4s | 3055 | 7465 | 20/20 | $0.0102 | stop | ok |
| `chunk_04` | ok | 121.9s | 2585 | 6696 | 20/20 | $0.0091 | stop | ok |
| `chunk_05` | ok | 14.3s | 599 | 424 | 1/1 | $0.0007 | stop | ok |