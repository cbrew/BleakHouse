# qwen-plus realtime chapter run — bleak_house/c12

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c12`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:24:05.858859+00:00
- wall: 160s

## Verdict

**PASS** — 6/6 chunks ok; 115/117 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,287
- output tokens: 42,085
- cost: $0.0550 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 119.6s | 2382 | 6589 | 20/20 | $0.0089 | stop | ok |
| `chunk_01` | ok | 107.0s | 1594 | 5859 | 18/20 | $0.0077 | stop | ok |
| `chunk_02` | ok | 160.2s | 2973 | 8819 | 20/20 | $0.0118 | stop | ok |
| `chunk_03` | ok | 135.6s | 1635 | 7114 | 20/20 | $0.0092 | stop | ok |
| `chunk_04` | ok | 126.0s | 1293 | 6952 | 20/20 | $0.0089 | stop | ok |
| `chunk_05` | ok | 123.9s | 1410 | 6752 | 17/17 | $0.0087 | stop | ok |