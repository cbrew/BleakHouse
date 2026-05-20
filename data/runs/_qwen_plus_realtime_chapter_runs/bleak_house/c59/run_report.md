# qwen-plus realtime chapter run — bleak_house/c59

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c59`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:46:13.890881+00:00
- wall: 155s

## Verdict

**PASS** — 6/6 chunks ok; 110/111 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 10,372
- output tokens: 41,991
- cost: $0.0545 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.0s | 2004 | 7134 | 20/20 | $0.0094 | stop | ok |
| `chunk_01` | ok | 136.8s | 1557 | 7493 | 20/20 | $0.0096 | stop | ok |
| `chunk_02` | ok | 143.2s | 1827 | 7842 | 20/20 | $0.0101 | stop | ok |
| `chunk_03` | ok | 155.0s | 1789 | 8476 | 20/20 | $0.0109 | stop | ok |
| `chunk_04` | ok | 128.0s | 1683 | 6993 | 19/20 | $0.0091 | stop | ok |
| `chunk_05` | ok | 75.0s | 1512 | 4053 | 11/11 | $0.0055 | stop | ok |