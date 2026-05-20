# qwen-plus realtime chapter run — bleak_house/c25

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c25`
- model: qwen-plus
- chunk_size: 20
- chunks: 3
- started: 2026-05-20T12:29:12.856823+00:00
- wall: 150s

## Verdict

**PASS** — 3/3 chunks ok; 59/59 paragraphs parsed.

## Numbers

- by_status: {'ok': 3}
- input tokens: 6,838
- output tokens: 22,411
- cost: $0.0296 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 149.6s | 3432 | 8162 | 20/20 | $0.0112 | stop | ok |
| `chunk_01` | ok | 135.6s | 1785 | 7475 | 20/20 | $0.0097 | stop | ok |
| `chunk_02` | ok | 124.7s | 1621 | 6774 | 19/19 | $0.0088 | stop | ok |