# qwen-plus realtime chapter run — bleak_house/c29

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c29`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:31:25.633138+00:00
- wall: 158s

## Verdict

**PASS** — 5/5 chunks ok; 81/81 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 8,164
- output tokens: 31,753
- cost: $0.0414 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 146.7s | 2352 | 8081 | 20/20 | $0.0106 | stop | ok |
| `chunk_01` | ok | 157.6s | 1786 | 8636 | 20/20 | $0.0111 | stop | ok |
| `chunk_02` | ok | 136.8s | 1834 | 7486 | 20/20 | $0.0097 | stop | ok |
| `chunk_03` | ok | 131.1s | 1618 | 7121 | 20/20 | $0.0092 | stop | ok |
| `chunk_04` | ok | 9.5s | 574 | 429 | 1/1 | $0.0007 | stop | ok |