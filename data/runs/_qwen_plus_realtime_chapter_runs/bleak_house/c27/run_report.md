# qwen-plus realtime chapter run — bleak_house/c27

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c27`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:30:49.522990+00:00
- wall: 145s

## Verdict

**PASS** — 6/6 chunks ok; 118/118 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 10,615
- output tokens: 42,043
- cost: $0.0547 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 112.1s | 1495 | 6107 | 20/20 | $0.0079 | stop | ok |
| `chunk_01` | ok | 130.7s | 1284 | 7207 | 20/20 | $0.0092 | stop | ok |
| `chunk_02` | ok | 144.5s | 2143 | 7917 | 20/20 | $0.0104 | stop | ok |
| `chunk_03` | ok | 136.7s | 1947 | 7492 | 20/20 | $0.0098 | stop | ok |
| `chunk_04` | ok | 134.0s | 2171 | 7334 | 20/20 | $0.0097 | stop | ok |
| `chunk_05` | ok | 110.0s | 1575 | 5986 | 18/18 | $0.0078 | stop | ok |