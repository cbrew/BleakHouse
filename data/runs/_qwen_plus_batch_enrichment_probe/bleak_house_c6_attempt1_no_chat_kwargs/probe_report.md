# DashScope batch probe — bleak_house/c6

- batch_id: `batch_1c8cde8f-12d8-42b7-b122-9bf53a5b1754`
- model: qwen-plus
- submitted: 2026-05-20T09:44:27.828479+00:00
- completed: 2026-05-20T09:59:19.223689+00:00
- wall: 2s

## Verdict

**FAIL** — validity 0.0% (threshold ≥95%); repetition defects 0 (threshold 0). Wall-time 2s (informational).

## Numbers

- requests: 1
- valid: 0
- validity_rate: 0.0%
- input tokens: 0
- output tokens: 0
- cost: $0.0000 (at $0.2/M in, $0.6/M out)

## Defects

- api_error: 1

## Per-request

| custom_id | validation | finish | in | out | cost | defect |
|---|---|---|---:|---:|---:|---|
| `enrich-c6` | failed: entry-level error internal_serve… | - | 0 | 0 | $0.0000 | api_error |