# qwen-plus realtime diagnostic — bleak_house/c6

Run dir: `data/runs/_qwen_plus_realtime_enrichment_probe/bleak_house_c6`

## Hypothesis assessment

Call B (with response_format) succeeded; Call A (no response_format) did not. Schema enforcement is helping the model. Batch path may be filtering something realtime allows through.

## Call A — no response_format

- status: ok
- elapsed: 6.685411234037019
- input_tokens: 756
- output_tokens: 258
- finish_reason: stop
- content_length: 1010
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
    "interest": 2,
    "characters": ["Esther Summerson"],
    "narrator": "Esther Summerson (first-person, past tense)",
    "plot_function": "setting establishment / transitional journey",
    "emotional_register": "cheerful, wonder-struck, serene",
    
```

### content (last 300 chars)

```
    "provision": {
      "setting": "strong",
      "characterization": "weak",
      "plot_advancement": "weak",
      "thematic_exposition": "medium",
      "emotional_atmosphere": "strong",
      "social_commentary": "weak",
      "symbolic_resonance": "medium"
    },
    "best_quote": null
  }
}
```

## Call B — response_format=json_schema strict=True

- status: ok
- elapsed: 7.9872816830175
- input_tokens: 758
- output_tokens: 399
- finish_reason: stop
- content_length: 1535
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
        "best_quote": "I believe we could all three have sung to the bells, so cheerful were the influences around.",
        "characters_present": ["Esther Summerson", "Ada Clare", "Richard 
```

### content (last 300 chars)

```
ountryside, experiencing a vivid, sun-drenched transition from urban density to rural charm—marked by sensory abundance, communal cheer, and symbolic musicality.",
        "themes": ["landscape", "journey", "innocence", "freedom", "sensory experience"]
      },
      "paragraph_index": 0
    }
  ]
}
```
