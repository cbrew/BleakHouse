# qwen-plus realtime chapter run — bleak_house/c9

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c9`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:21:49.358580+00:00
- wall: 138s

## Verdict

**PASS** — 6/6 chunks ok; 112/112 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 12,010
- output tokens: 41,342
- cost: $0.0544 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 131.1s | 2161 | 7173 | 20/20 | $0.0095 | stop | ok |
| `chunk_01` | ok | 133.1s | 2467 | 7246 | 20/20 | $0.0097 | stop | ok |
| `chunk_02` | ok | 138.2s | 2365 | 7567 | 20/20 | $0.0100 | stop | ok |
| `chunk_03` | ok | 129.8s | 1833 | 7105 | 20/20 | $0.0093 | stop | ok |
| `chunk_04` | ok | 132.2s | 1576 | 7233 | 20/20 | $0.0093 | stop | ok |
| `chunk_05` | ok | 92.2s | 1608 | 5018 | 12/12 | $0.0067 | stop | ok |