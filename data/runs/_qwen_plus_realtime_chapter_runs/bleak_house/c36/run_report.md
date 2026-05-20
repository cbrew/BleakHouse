# qwen-plus realtime chapter run — bleak_house/c36

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c36`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:34:27.531474+00:00
- wall: 137s

## Verdict

**PASS** — 5/5 chunks ok; 81/81 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 11,433
- output tokens: 29,295
- cost: $0.0397 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 127.9s | 4073 | 7001 | 20/20 | $0.0100 | stop | ok |
| `chunk_01` | ok | 133.0s | 1951 | 7251 | 20/20 | $0.0095 | stop | ok |
| `chunk_02` | ok | 129.7s | 1492 | 7075 | 20/20 | $0.0091 | stop | ok |
| `chunk_03` | ok | 137.4s | 3322 | 7446 | 20/20 | $0.0103 | stop | ok |
| `chunk_04` | ok | 11.8s | 595 | 522 | 1/1 | $0.0009 | stop | ok |