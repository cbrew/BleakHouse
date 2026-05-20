# qwen-plus realtime chapter run — bleak_house/c19

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c19`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:26:35.568513+00:00
- wall: 147s

## Verdict

**PASS** — 6/6 chunks ok; 109/110 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,320
- output tokens: 40,924
- cost: $0.0536 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.3s | 2894 | 7126 | 20/20 | $0.0097 | stop | ok |
| `chunk_01` | ok | 124.9s | 1808 | 6780 | 19/20 | $0.0089 | stop | ok |
| `chunk_02` | ok | 141.5s | 1800 | 7719 | 20/20 | $0.0100 | stop | ok |
| `chunk_03` | ok | 147.5s | 1913 | 8074 | 20/20 | $0.0105 | stop | ok |
| `chunk_04` | ok | 135.4s | 1432 | 7292 | 20/20 | $0.0093 | stop | ok |
| `chunk_05` | ok | 72.9s | 1473 | 3933 | 10/10 | $0.0053 | stop | ok |