# qwen-plus realtime chapter run — bleak_house/c2

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c2`
- model: qwen-plus
- chunk_size: 20
- chunks: 2
- started: 2026-05-20T12:19:16.175943+00:00
- wall: 130s

## Verdict

**FAIL** — 2/2 chunks ok; 34/35 paragraphs parsed.

## Numbers

- by_status: {'ok': 2}
- input tokens: 5,134
- output tokens: 12,597
- cost: $0.0172 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 130.1s | 3897 | 7114 | 19/20 | $0.0101 | stop | ok |
| `chunk_01` | ok | 101.1s | 1237 | 5483 | 15/15 | $0.0071 | stop | ok |