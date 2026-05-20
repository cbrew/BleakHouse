# qwen-plus realtime chapter run — bleak_house/c1

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c1`
- model: qwen-plus
- chunk_size: 20
- chunks: 2
- started: 2026-05-20T12:19:16.175727+00:00
- wall: 145s

## Verdict

**PASS** — 2/2 chunks ok; 28/28 paragraphs parsed.

## Numbers

- by_status: {'ok': 2}
- input tokens: 4,832
- output tokens: 11,045
- cost: $0.0152 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 144.8s | 3769 | 7864 | 20/20 | $0.0109 | stop | ok |
| `chunk_01` | ok | 60.4s | 1063 | 3181 | 8/8 | $0.0042 | stop | ok |