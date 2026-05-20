# qwen-plus realtime chapter run — bleak_house/c15

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c15`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:24:15.413409+00:00
- wall: 135s

## Verdict

**PASS** — 7/7 chunks ok; 120/121 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,809
- output tokens: 42,894
- cost: $0.0566 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 134.5s | 2757 | 7407 | 20/20 | $0.0100 | stop | ok |
| `chunk_01` | ok | 134.0s | 1480 | 7331 | 20/20 | $0.0094 | stop | ok |
| `chunk_02` | ok | 123.5s | 1603 | 6719 | 19/20 | $0.0087 | stop | ok |
| `chunk_03` | ok | 130.5s | 1153 | 7112 | 20/20 | $0.0090 | stop | ok |
| `chunk_04` | ok | 134.1s | 2017 | 7329 | 20/20 | $0.0096 | stop | ok |
| `chunk_05` | ok | 119.3s | 3128 | 6506 | 20/20 | $0.0091 | stop | ok |
| `chunk_06` | ok | 10.4s | 671 | 490 | 1/1 | $0.0009 | stop | ok |