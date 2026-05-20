# DashScope batch probe — bleak_house/c6

- batch_id: `batch_ebbf8818-0a36-43c8-af1f-3cb6fbc95458`
- model: qwen-plus
- submitted: 2026-05-20T10:10:35.991114+00:00
- completed: 2026-05-20T10:15:57.219161+00:00
- wall: 321s

## Verdict

**FAIL** — validity 0.0% (threshold ≥95%); repetition defects 0 (threshold 0). Wall-time 321s (informational).

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