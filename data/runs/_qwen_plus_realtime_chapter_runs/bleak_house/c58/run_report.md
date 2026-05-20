# qwen-plus realtime chapter run — bleak_house/c58

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c58`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:45:31.291777+00:00
- wall: 146s

## Verdict

**PASS** — 6/6 chunks ok; 106/106 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,110
- output tokens: 39,399
- cost: $0.0517 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 132.7s | 2468 | 7253 | 20/20 | $0.0097 | stop | ok |
| `chunk_01` | ok | 137.6s | 1916 | 7493 | 20/20 | $0.0098 | stop | ok |
| `chunk_02` | ok | 129.7s | 1356 | 7062 | 20/20 | $0.0090 | stop | ok |
| `chunk_03` | ok | 146.2s | 2200 | 7720 | 20/20 | $0.0101 | stop | ok |
| `chunk_04` | ok | 137.1s | 2450 | 7491 | 20/20 | $0.0100 | stop | ok |
| `chunk_05` | ok | 49.3s | 720 | 2380 | 6/6 | $0.0031 | stop | ok |