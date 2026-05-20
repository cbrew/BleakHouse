# qwen-plus realtime chapter run — bleak_house/c18

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c18`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:26:29.936253+00:00
- wall: 151s

## Verdict

**PASS** — 6/6 chunks ok; 116/116 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 13,168
- output tokens: 44,452
- cost: $0.0586 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 133.2s | 3111 | 7347 | 20/20 | $0.0101 | stop | ok |
| `chunk_01` | ok | 133.8s | 3151 | 7303 | 20/20 | $0.0100 | stop | ok |
| `chunk_02` | ok | 149.7s | 2406 | 8256 | 20/20 | $0.0109 | stop | ok |
| `chunk_03` | ok | 151.4s | 1996 | 8324 | 20/20 | $0.0108 | stop | ok |
| `chunk_04` | ok | 129.8s | 1244 | 7135 | 20/20 | $0.0091 | stop | ok |
| `chunk_05` | ok | 110.5s | 1260 | 6087 | 16/16 | $0.0078 | stop | ok |