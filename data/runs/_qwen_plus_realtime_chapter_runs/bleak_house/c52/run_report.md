# qwen-plus realtime chapter run — bleak_house/c52

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c52`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:42:55.233889+00:00
- wall: 141s

## Verdict

**PASS** — 6/6 chunks ok; 103/103 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 9,501
- output tokens: 38,824
- cost: $0.0504 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 128.9s | 2076 | 7087 | 20/20 | $0.0093 | stop | ok |
| `chunk_01` | ok | 137.3s | 1273 | 7551 | 20/20 | $0.0096 | stop | ok |
| `chunk_02` | ok | 140.8s | 2158 | 7636 | 20/20 | $0.0100 | stop | ok |
| `chunk_03` | ok | 137.6s | 1702 | 7492 | 20/20 | $0.0097 | stop | ok |
| `chunk_04` | ok | 140.8s | 1615 | 7713 | 20/20 | $0.0099 | stop | ok |
| `chunk_05` | ok | 26.1s | 677 | 1345 | 3/3 | $0.0019 | stop | ok |