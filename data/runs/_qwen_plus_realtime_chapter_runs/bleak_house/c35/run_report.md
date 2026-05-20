# qwen-plus realtime chapter run — bleak_house/c35

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c35`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:34:08.808151+00:00
- wall: 141s

## Verdict

**FAIL** — 6/6 chunks ok; 115/119 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,911
- output tokens: 42,453
- cost: $0.0557 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 111.0s | 2234 | 6063 | 17/20 | $0.0082 | stop | ok |
| `chunk_01` | ok | 120.0s | 1920 | 6599 | 20/20 | $0.0087 | stop | ok |
| `chunk_02` | ok | 140.9s | 2323 | 7729 | 20/20 | $0.0102 | stop | ok |
| `chunk_03` | ok | 128.4s | 1783 | 7044 | 20/20 | $0.0092 | stop | ok |
| `chunk_04` | ok | 134.1s | 1826 | 7398 | 20/20 | $0.0096 | stop | ok |
| `chunk_05` | ok | 139.5s | 1825 | 7620 | 18/19 | $0.0099 | stop | ok |