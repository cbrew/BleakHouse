# qwen-plus realtime chapter run — bleak_house/c28

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c28`
- model: qwen-plus
- chunk_size: 20
- chunks: 5
- started: 2026-05-20T12:31:20.326755+00:00
- wall: 149s

## Verdict

**FAIL** — 5/5 chunks ok; 86/88 paragraphs parsed.

## Numbers

- by_status: {'ok': 5}
- input tokens: 9,147
- output tokens: 32,239
- cost: $0.0423 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 148.7s | 2611 | 8169 | 20/20 | $0.0108 | stop | ok |
| `chunk_01` | ok | 126.0s | 1705 | 6918 | 20/20 | $0.0090 | stop | ok |
| `chunk_02` | ok | 139.9s | 2082 | 7717 | 19/20 | $0.0101 | stop | ok |
| `chunk_03` | ok | 116.4s | 1607 | 6385 | 19/20 | $0.0083 | stop | ok |
| `chunk_04` | ok | 56.5s | 1142 | 3050 | 8/8 | $0.0041 | stop | ok |