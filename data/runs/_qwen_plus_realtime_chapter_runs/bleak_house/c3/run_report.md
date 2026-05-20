# qwen-plus realtime chapter run — bleak_house/c3

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c3`
- model: qwen-plus
- chunk_size: 20
- chunks: 9
- started: 2026-05-20T12:19:16.176224+00:00
- wall: 143s

## Verdict

**PASS** — 9/9 chunks ok; 163/165 paragraphs parsed.

## Numbers

- by_status: {'ok': 9}
- input tokens: 15,751
- output tokens: 58,785
- cost: $0.0768 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 131.7s | 2884 | 7196 | 20/20 | $0.0098 | stop | ok |
| `chunk_01` | ok | 132.4s | 1763 | 7141 | 20/20 | $0.0093 | stop | ok |
| `chunk_02` | ok | 130.6s | 2032 | 7139 | 20/20 | $0.0094 | stop | ok |
| `chunk_03` | ok | 130.4s | 1303 | 7077 | 20/20 | $0.0090 | stop | ok |
| `chunk_04` | ok | 143.3s | 2348 | 7821 | 20/20 | $0.0103 | stop | ok |
| `chunk_05` | ok | 130.1s | 1762 | 7097 | 20/20 | $0.0092 | stop | ok |
| `chunk_06` | ok | 132.8s | 1436 | 7212 | 20/20 | $0.0092 | stop | ok |
| `chunk_07` | ok | 107.9s | 1451 | 5849 | 18/20 | $0.0076 | stop | ok |
| `chunk_08` | ok | 42.4s | 772 | 2253 | 5/5 | $0.0030 | stop | ok |