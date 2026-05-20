# qwen-plus realtime chapter run — bleak_house/c48

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c48`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:41:03.826824+00:00
- wall: 137s

## Verdict

**PASS** — 7/7 chunks ok; 135/137 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 12,715
- output tokens: 47,658
- cost: $0.0623 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 127.2s | 1674 | 6991 | 20/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 122.8s | 1611 | 6674 | 20/20 | $0.0087 | stop | ok |
| `chunk_02` | ok | 137.2s | 1315 | 7480 | 20/20 | $0.0095 | stop | ok |
| `chunk_03` | ok | 129.1s | 1766 | 7056 | 20/20 | $0.0092 | stop | ok |
| `chunk_04` | ok | 118.3s | 1930 | 6456 | 18/20 | $0.0085 | stop | ok |
| `chunk_05` | ok | 126.9s | 1623 | 6912 | 20/20 | $0.0089 | stop | ok |
| `chunk_06` | ok | 111.7s | 2796 | 6089 | 17/17 | $0.0084 | stop | ok |