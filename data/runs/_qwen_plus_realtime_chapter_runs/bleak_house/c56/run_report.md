# qwen-plus realtime chapter run — bleak_house/c56

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c56`
- model: qwen-plus
- chunk_size: 20
- chunks: 3
- started: 2026-05-20T12:43:54.942508+00:00
- wall: 139s

## Verdict

**PASS** — 3/3 chunks ok; 55/55 paragraphs parsed.

## Numbers

- by_status: {'ok': 3}
- input tokens: 6,168
- output tokens: 21,620
- cost: $0.0284 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 136.8s | 2224 | 7510 | 20/20 | $0.0099 | stop | ok |
| `chunk_01` | ok | 138.9s | 1985 | 7604 | 20/20 | $0.0099 | stop | ok |
| `chunk_02` | ok | 124.7s | 1959 | 6506 | 15/15 | $0.0086 | stop | ok |