The reliable approach is to track provider docs for hard guarantees and use a thin validation/evaluation layer of your own for portability.

The best current sources are:

Provider documentation
OpenAI Structured Outputs: strongest public documentation for schema-constrained responses; OpenAI distinguishes JSON mode from schema adherence and notes important edge cases such as refusals, max_tokens, unsupported schema subsets, schema-cache latency, and parallel tool-call incompatibility.
Anthropic Structured Outputs / strict tool use: now has explicit JSON-output support and strict: true tool-input validation, but also documents schema limitations, grammar compilation/caching, refusal and max_tokens exceptions, and SDK behavior that may simplify schemas before sending them.
Gemini Structured Outputs: Google documents response_mime_type: application/json plus response_json_schema, supported JSON Schema subset, model support, and best practices such as clear field descriptions, strong typing, enums, app-side validation, and error handling.
Cross-provider libraries
Instructor is probably the most practical cross-provider reference implementation for “Pydantic-first structured extraction.” It supports OpenAI, Anthropic, Gemini, Vertex, Mistral, Ollama, DeepSeek and others, with validation, retries, and streaming support.
Guardrails AI is useful when you want structured generation plus explicit validators and streaming validation, although I would treat it as a validation framework rather than a guarantee that all providers behave the same.

The key conclusion: JSON Schema is not yet a portable contract across LLM providers. Providers expose things that look similar—JSON schema, Pydantic/Zod helpers, strict tools—but they enforce different subsets, reject different patterns, and sometimes move unsupported constraints into descriptions or client-side validation. Anthropic’s docs explicitly say some SDKs remove unsupported constraints such as minimum, maximum, minLength, and maxLength, add them to descriptions, and then validate locally. Google likewise says Gemini supports only a subset of JSON Schema and that unsupported properties may be ignored.

My practical recommendation:

Use the provider’s native structured-output mechanism whenever available. Do not rely on “please output JSON” prompting except as a fallback. For OpenAI, use Structured Outputs rather than JSON mode when you need schema adherence. For Anthropic, use output_config.format for final JSON and strict: true for tool inputs. For Gemini, use response_json_schema with application/json.

Design to the portable subset. Keep schemas shallow. Prefer required fields, simple objects, arrays, enums, booleans, strings, integers, and nullable fields. Avoid depending on complex anyOf/oneOf, deep nesting, regex constraints, intricate numeric constraints, or provider-specific property-order behavior.

Validate twice. First validate syntactic/schema compliance with Pydantic, Zod, JSON Schema, etc. Then validate semantic/business rules separately. The provider can guarantee “this is an integer in the enum”; it cannot guarantee “this extracted date is actually the filing deadline implied by the document.” Google explicitly recommends application-side validation because schema-compliant values may still fail business logic.

Treat refusals, truncation, and tool-call mode as separate states. A structured-output call can still fail shape guarantees if the model refuses or hits token limits; OpenAI and Anthropic both document these as cases you must handle programmatically.

Build a small adversarial conformance suite. For each provider/model you care about, test the exact schemas you use: missing required fields, bad enum values, extra properties, nullability, nested arrays, malformed dates, overly long strings, and ambiguous extractions. This is better than trusting docs alone because the portable behavior is the intersection of provider implementation, model version, SDK transformation, and your own schema.

Version-pin prompts, schemas, SDKs, and models. Structured-output behavior is not just “model behavior”; it is also API-mode behavior, SDK schema transformation, grammar compilation, and provider-side validation. Treat schema changes as breaking API changes.

For your use case, I would use official provider docs as the source of truth, Instructor as the pragmatic cross-provider adapter, and a local conformance/evaluation harness as the real reliability layer. The harness should be considered part of the system, not merely a test suite.