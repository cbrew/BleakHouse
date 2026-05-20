# qwen-plus realtime chapter run — bleak_house/c13

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c13`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:24:06.376067+00:00
- wall: 149s

## Verdict

**PASS** — 7/7 chunks ok; 133/133 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,430
- output tokens: 49,105
- cost: $0.0639 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 134.6s | 2285 | 7417 | 20/20 | $0.0098 | stop | ok |
| `chunk_01` | ok | 140.7s | 2560 | 7470 | 20/20 | $0.0100 | stop | ok |
| `chunk_02` | ok | 142.6s | 1600 | 7561 | 20/20 | $0.0097 | stop | ok |
| `chunk_03` | ok | 128.3s | 1636 | 6736 | 20/20 | $0.0087 | stop | ok |
| `chunk_04` | ok | 137.0s | 1443 | 7239 | 20/20 | $0.0093 | stop | ok |
| `chunk_05` | ok | 149.2s | 1690 | 7943 | 20/20 | $0.0102 | stop | ok |
| `chunk_06` | ok | 91.7s | 1216 | 4739 | 13/13 | $0.0062 | stop | ok |