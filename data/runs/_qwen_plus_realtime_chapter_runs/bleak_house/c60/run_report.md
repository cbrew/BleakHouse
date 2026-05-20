# qwen-plus realtime chapter run — bleak_house/c60

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c60`
- model: qwen-plus
- chunk_size: 20
- chunks: 7
- started: 2026-05-20T12:46:15.141478+00:00
- wall: 141s

## Verdict

**PASS** — 7/7 chunks ok; 127/127 paragraphs parsed.

## Numbers

- by_status: {'ok': 7}
- input tokens: 10,999
- output tokens: 45,626
- cost: $0.0592 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 127.6s | 1514 | 7039 | 20/20 | $0.0091 | stop | ok |
| `chunk_01` | ok | 130.3s | 1394 | 7197 | 20/20 | $0.0092 | stop | ok |
| `chunk_02` | ok | 131.5s | 1796 | 7162 | 20/20 | $0.0093 | stop | ok |
| `chunk_03` | ok | 125.4s | 1500 | 6850 | 20/20 | $0.0088 | stop | ok |
| `chunk_04` | ok | 140.8s | 2156 | 7708 | 20/20 | $0.0101 | stop | ok |
| `chunk_05` | ok | 130.7s | 1755 | 7145 | 20/20 | $0.0093 | stop | ok |
| `chunk_06` | ok | 47.0s | 884 | 2525 | 7/7 | $0.0034 | stop | ok |