# qwen-plus realtime chapter run — bleak_house/c45

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c45`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:38:58.791207+00:00
- wall: 142s

## Verdict

**PASS** — 6/6 chunks ok; 101/101 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 10,522
- output tokens: 38,015
- cost: $0.0498 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 140.6s | 2233 | 7753 | 20/20 | $0.0102 | stop | ok |
| `chunk_01` | ok | 140.6s | 2231 | 7663 | 20/20 | $0.0101 | stop | ok |
| `chunk_02` | ok | 138.1s | 2102 | 7570 | 20/20 | $0.0099 | stop | ok |
| `chunk_03` | ok | 142.1s | 1905 | 7756 | 20/20 | $0.0101 | stop | ok |
| `chunk_04` | ok | 125.4s | 1462 | 6864 | 20/20 | $0.0088 | stop | ok |
| `chunk_05` | ok | 9.3s | 589 | 409 | 1/1 | $0.0007 | stop | ok |