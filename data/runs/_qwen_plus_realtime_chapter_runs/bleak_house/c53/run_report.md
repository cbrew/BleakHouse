# qwen-plus realtime chapter run — bleak_house/c53

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c53`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:43:21.059318+00:00
- wall: 130s

## Verdict

**PASS** — 6/6 chunks ok; 109/111 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 9,650
- output tokens: 38,405
- cost: $0.0499 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 113.9s | 2412 | 6258 | 18/20 | $0.0085 | stop | ok |
| `chunk_01` | ok | 129.1s | 1918 | 7085 | 20/20 | $0.0093 | stop | ok |
| `chunk_02` | ok | 122.4s | 1834 | 6695 | 20/20 | $0.0088 | stop | ok |
| `chunk_03` | ok | 126.4s | 1369 | 6912 | 20/20 | $0.0088 | stop | ok |
| `chunk_04` | ok | 130.2s | 1189 | 7154 | 20/20 | $0.0091 | stop | ok |
| `chunk_05` | ok | 78.7s | 928 | 4301 | 11/11 | $0.0055 | stop | ok |