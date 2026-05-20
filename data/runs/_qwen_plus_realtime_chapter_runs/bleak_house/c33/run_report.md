# qwen-plus realtime chapter run — bleak_house/c33

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c33`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:33:49.029495+00:00
- wall: 148s

## Verdict

**PASS** — 5/5 chunks ok; 89/89 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 9,162
- output tokens: 33,668
- cost: $0.0441 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 148.2s | 2492 | 8119 | 20/20 | $0.0107 | stop | ok |
| `chunk_01` | ok | 142.4s | 1812 | 7804 | 20/20 | $0.0101 | stop | ok |
| `chunk_02` | ok | 124.0s | 1408 | 6786 | 20/20 | $0.0087 | stop | ok |
| `chunk_03` | ok | 136.7s | 1738 | 7499 | 20/20 | $0.0097 | stop | ok |
| `chunk_04` | ok | 63.4s | 1712 | 3460 | 9/9 | $0.0048 | stop | ok |