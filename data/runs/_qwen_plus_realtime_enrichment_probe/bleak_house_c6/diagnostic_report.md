# qwen-plus realtime diagnostic — bleak_house/c6

Run dir: `data/runs/_qwen_plus_realtime_enrichment_probe/bleak_house_c6`

## Hypothesis assessment

Call B (with response_format) succeeded; Call A (no response_format) did not. Schema enforcement is helping the model. Batch path may be filtering something realtime allows through.

## Call A — no response_format

- status: ok
- elapsed: 9.143212107999716
- input_tokens: 2628
- output_tokens: 384
- finish_reason: stop
- content_length: 1574
- has_think_tags: False
- has_markdown_fence: False
- repetition_loop: False
- was_truncated: False
- json_parse: ok
- schema_validate: failed: 4 errors

### content (first 300 chars)

```
{
  "paragraph_index": 0,
  "enrichment": {
    "interest": 3,
    "characters": ["Esther Summerson", "Ada Clare", "Richard Carstone"],
    "narrator": "Esther Summerson",
    "plot_function": "setting establishment / journey motif / tonal transition from urban to rural",
    "emotional_register": "
```

### content (last 300 chars)

```
e the green landscape before us and the immense metropolis behind; and when a waggon with a train of beautiful horses, furnished with red trappings and clear-sounding bells, came by us with its music, I believe we could all three have sung to the bells, so cheerful were the influences around."
  }
}
```

## Call B — response_format=json_schema strict=True

- status: ok
- elapsed: 134.75749028503196
- input_tokens: 2630
- output_tokens: 7418
- finish_reason: stop
- content_length: 28947
- has_think_tags: False
- has_markdown_fence: False
- repetition_loop: False
- was_truncated: False
- json_parse: ok
- schema_validate: ok

### content (first 300 chars)

```
{
  "chapter_id": "c6",
  "enrichments": [
    {
      "enrichment": {
        "accessibility": 	"moderate",
        "best_quote": "It was delightful to see the green landscape before us and the immense metropolis behind; and when a waggon with a train of beautiful horses, furnished with red trappin
```

### content (last 300 chars)

```
ral assessment of Mrs. Jellyby’s Africa-focused charity — marking her first verbal contribution to the household and signaling her incipient critical awareness.",
        "themes": ["charity", "satire", "social critique", "observation", "colonialism"]
      },
      "paragraph_index": 19
    }
  ]
}
```
