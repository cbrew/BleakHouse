# qwen-plus realtime chapter run — bleak_house/c57

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c57`
- model: qwen-plus
- chunk_size: 20
- chunks: 8
- started: 2026-05-20T12:45:16.036263+00:00
- wall: 142s

## Verdict

**PASS** — 8/8 chunks ok; 142/142 paragraphs parsed.

## Numbers

- by_status: {'ok': 8}
- input tokens: 14,584
- output tokens: 50,431
- cost: $0.0664 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 141.5s | 2910 | 7786 | 20/20 | $0.0105 | stop | ok |
| `chunk_01` | ok | 118.2s | 1586 | 6487 | 20/20 | $0.0084 | stop | ok |
| `chunk_02` | ok | 138.9s | 2188 | 7608 | 20/20 | $0.0100 | stop | ok |
| `chunk_03` | ok | 129.5s | 1882 | 7124 | 20/20 | $0.0093 | stop | ok |
| `chunk_04` | ok | 133.8s | 1303 | 7394 | 20/20 | $0.0094 | stop | ok |
| `chunk_05` | ok | 116.7s | 2711 | 6361 | 20/20 | $0.0087 | stop | ok |
| `chunk_06` | ok | 128.2s | 1426 | 6959 | 20/20 | $0.0089 | stop | ok |
| `chunk_07` | ok | 13.4s | 578 | 712 | 2/2 | $0.0011 | stop | ok |