# qwen-plus realtime chapter run — bleak_house/c38

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c38`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:36:17.215975+00:00
- wall: 141s

## Verdict

**PASS** — 5/5 chunks ok; 87/88 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 8,752
- output tokens: 32,913
- cost: $0.0430 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 138.5s | 1767 | 7628 | 20/20 | $0.0099 | stop | ok |
| `chunk_01` | ok | 141.0s | 2530 | 7759 | 20/20 | $0.0103 | stop | ok |
| `chunk_02` | ok | 129.4s | 1545 | 7077 | 19/20 | $0.0091 | stop | ok |
| `chunk_03` | ok | 136.4s | 1982 | 7474 | 20/20 | $0.0098 | stop | ok |
| `chunk_04` | ok | 54.7s | 928 | 2975 | 8/8 | $0.0039 | stop | ok |