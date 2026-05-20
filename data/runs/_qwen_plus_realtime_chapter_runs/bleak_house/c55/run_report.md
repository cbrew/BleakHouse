# qwen-plus realtime chapter run — bleak_house/c55

- run_dir: `data/runs/_qwen_plus_realtime_chapter_runs/bleak_house/c55`
- model: qwen-plus
- chunk_size: 20
- chunks: 6
- started: 2026-05-20T12:43:46.944313+00:00
- wall: 148s

## Verdict

**PASS** — 6/6 chunks ok; 110/110 paragraphs parsed.

## Numbers

- by_status: {'ok': 6}
- input tokens: 11,855
- output tokens: 41,064
- cost: $0.0540 (at $0.4/M in, $1.2/M out)

## Per-chunk

| chunk | status | elapsed | in | out | parsed/expected | cost | finish | validation |
|---|---|---:|---:|---:|---|---:|---|---|
| `chunk_00` | ok | 139.7s | 3032 | 7689 | 20/20 | $0.0104 | stop | ok |
| `chunk_01` | ok | 148.2s | 2252 | 8054 | 20/20 | $0.0106 | stop | ok |
| `chunk_02` | ok | 131.8s | 1629 | 7173 | 20/20 | $0.0093 | stop | ok |
| `chunk_03` | ok | 136.9s | 1689 | 7440 | 20/20 | $0.0096 | stop | ok |
| `chunk_04` | ok | 130.8s | 1971 | 7087 | 20/20 | $0.0093 | stop | ok |
| `chunk_05` | ok | 68.0s | 1282 | 3621 | 10/10 | $0.0049 | stop | ok |