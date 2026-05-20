# qwen-plus realtime chapter run — bleak_house/c64

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c64`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:48:35.924661+00:00
- wall: 148s

## Verdict

**PASS** — 5/5 chunks ok; 85/85 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 8,855
- output tokens: 31,474
- cost: $0.0413 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.1s | 2291 | 7169 | 20/20 | $0.0095 | stop | ok |
| `chunk_01` | ok | 148.2s | 2387 | 8125 | 20/20 | $0.0107 | stop | ok |
| `chunk_02` | ok | 125.9s | 1758 | 6875 | 20/20 | $0.0090 | stop | ok |
| `chunk_03` | ok | 134.3s | 1625 | 7354 | 20/20 | $0.0095 | stop | ok |
| `chunk_04` | ok | 36.9s | 794 | 1951 | 5/5 | $0.0027 | stop | ok |