# qwen-plus realtime chapter run — bleak_house/c31

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c31`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:31:54.346969+00:00
- wall: 153s

## Verdict

**PASS** — 7/7 chunks ok; 139/139 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,941
- output tokens: 51,787
- cost: $0.0673 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 133.4s | 1494 | 7361 | 20/20 | $0.0094 | stop | ok |
| `chunk_01` | ok | 140.4s | 1796 | 7711 | 20/20 | $0.0100 | stop | ok |
| `chunk_02` | ok | 128.0s | 1882 | 7021 | 20/20 | $0.0092 | stop | ok |
| `chunk_03` | ok | 153.2s | 1899 | 8386 | 20/20 | $0.0108 | stop | ok |
| `chunk_04` | ok | 128.6s | 1857 | 7023 | 20/20 | $0.0092 | stop | ok |
| `chunk_05` | ok | 143.6s | 2595 | 7866 | 20/20 | $0.0105 | stop | ok |
| `chunk_06` | ok | 117.2s | 1418 | 6419 | 19/19 | $0.0083 | stop | ok |