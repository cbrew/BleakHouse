# qwen-plus realtime chapter run — bleak_house/c4

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c4`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:19:25.898179+00:00
- wall: 143s

## Verdict

**PASS** — 6/6 chunks ok; 108/109 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 10,222
- output tokens: 38,632
- cost: $0.0504 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 126.5s | 1722 | 6943 | 20/20 | $0.0090 | stop | ok |
| `chunk_01` | ok | 143.5s | 2111 | 7802 | 20/20 | $0.0102 | stop | ok |
| `chunk_02` | ok | 134.4s | 2765 | 7327 | 20/20 | $0.0099 | stop | ok |
| `chunk_03` | ok | 121.5s | 1282 | 6641 | 19/20 | $0.0085 | stop | ok |
| `chunk_04` | ok | 127.4s | 1182 | 6930 | 20/20 | $0.0088 | stop | ok |
| `chunk_05` | ok | 55.8s | 1160 | 2989 | 9/9 | $0.0041 | stop | ok |