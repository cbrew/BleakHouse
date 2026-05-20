# qwen-plus realtime chapter run — bleak_house/c21

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c21`
- model: qwen-plus
- chunk_size: 20
- chunks: 9
- started: 2026-05-20T12:27:10.383994+00:00
- wall: 141s

## Verdict

**PASS** — 9/9 chunks ok; 168/168 paragraphs parsed.

## Numbers

- by_status: {'ok': 9}
- input tokens: 14,984
- output tokens: 59,963
- cost: $0.0779 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 124.7s | 2209 | 6860 | 20/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 120.7s | 1471 | 6656 | 20/20 | $0.0086 | stop | ok |
| `chunk_02` | ok | 137.1s | 2128 | 7500 | 20/20 | $0.0099 | stop | ok |
| `chunk_03` | ok | 127.8s | 1595 | 7001 | 20/20 | $0.0090 | stop | ok |
| `chunk_04` | ok | 128.2s | 1417 | 7075 | 20/20 | $0.0091 | stop | ok |
| `chunk_05` | ok | 138.0s | 1810 | 7531 | 20/20 | $0.0098 | stop | ok |
| `chunk_06` | ok | 140.6s | 1624 | 7718 | 20/20 | $0.0099 | stop | ok |
| `chunk_07` | ok | 126.7s | 1915 | 6876 | 20/20 | $0.0090 | stop | ok |
| `chunk_08` | ok | 50.9s | 815 | 2746 | 8/8 | $0.0036 | stop | ok |