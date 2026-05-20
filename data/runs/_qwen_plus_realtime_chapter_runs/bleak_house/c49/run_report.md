# qwen-plus realtime chapter run — bleak_house/c49

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c49`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:41:19.394290+00:00
- wall: 147s

## Verdict

**PASS** — 6/6 chunks ok; 113/115 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,292
- output tokens: 41,391
- cost: $0.0542 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 118.7s | 2106 | 6531 | 19/20 | $0.0087 | stop | ok |
| `chunk_01` | ok | 121.5s | 1864 | 6648 | 20/20 | $0.0087 | stop | ok |
| `chunk_02` | ok | 133.6s | 2065 | 7337 | 20/20 | $0.0096 | stop | ok |
| `chunk_03` | ok | 142.7s | 1616 | 7831 | 20/20 | $0.0100 | stop | ok |
| `chunk_04` | ok | 147.4s | 2191 | 8116 | 20/20 | $0.0106 | stop | ok |
| `chunk_05` | ok | 90.4s | 1450 | 4928 | 14/15 | $0.0065 | stop | ok |