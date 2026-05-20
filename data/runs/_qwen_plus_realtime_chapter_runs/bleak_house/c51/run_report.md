# qwen-plus realtime chapter run — bleak_house/c51

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c51`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:41:30.445957+00:00
- wall: 144s

## Verdict

**PASS** — 6/6 chunks ok; 101/101 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 9,624
- output tokens: 37,212
- cost: $0.0485 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 120.0s | 1794 | 6572 | 20/20 | $0.0086 | stop | ok |
| `chunk_01` | ok | 128.4s | 1731 | 7054 | 20/20 | $0.0092 | stop | ok |
| `chunk_02` | ok | 135.0s | 1849 | 7396 | 20/20 | $0.0096 | stop | ok |
| `chunk_03` | ok | 144.5s | 1841 | 7935 | 20/20 | $0.0103 | stop | ok |
| `chunk_04` | ok | 142.7s | 1848 | 7829 | 20/20 | $0.0101 | stop | ok |
| `chunk_05` | ok | 9.0s | 561 | 426 | 1/1 | $0.0007 | stop | ok |