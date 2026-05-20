# qwen-plus realtime chapter run — bleak_house/c8

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c8`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:21:41.078940+00:00
- wall: 145s

## Verdict

**PASS** — 6/6 chunks ok; 118/118 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 14,758
- output tokens: 45,650
- cost: $0.0607 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 144.8s | 3100 | 7966 | 20/20 | $0.0108 | stop | ok |
| `chunk_01` | ok | 139.4s | 1704 | 7691 | 20/20 | $0.0099 | stop | ok |
| `chunk_02` | ok | 138.8s | 2850 | 7616 | 20/20 | $0.0103 | stop | ok |
| `chunk_03` | ok | 143.5s | 2752 | 7866 | 20/20 | $0.0105 | stop | ok |
| `chunk_04` | ok | 137.9s | 2493 | 7526 | 20/20 | $0.0100 | stop | ok |
| `chunk_05` | ok | 127.6s | 1859 | 6985 | 18/18 | $0.0091 | stop | ok |