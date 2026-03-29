# Blog Series Plan: Not In Our Time — Technical Deep Dives

Target audience: technical LLM practitioners (engineers, researchers, applied scientists) interested in RAG alternatives, structured generation, and creative AI applications.

## Post 1: "The Reader Makes the Reading" (existing, lightly revised)
Overview post. Framework dominance finding, pastiche, knowledge gradient. Already written.

## Post 2: "Enrichment at Scale: 60,000 Passages, 20 Fields Each"
- How we parse novels into passages (Gutenberg → lxml → passage segmentation)
- The enrichment schema: interest score, 7 provision dimensions, characters, themes, quotability, best_quote
- Why Haiku, not Sonnet (cost × 60K passages)
- Structured output via Anthropic's json_schema format
- Quality control: what goes wrong, how we catch it
- The atmosphere_setting failure across 15 novels (schema bias)
- Passage length confound (Miss Marjoribanks 161 words vs Bleak House 49)

## Post 3: "Min-Cost Flow vs Embeddings: Two Ways to Read a Novel"
- The transport formulation: passages as supply, experts as demand, OR-Tools SimpleMinCostFlow
- Why it produces synoptic readings (multi-dimensional demand → breadth)
- The embedding alternative: contextual retrieval à la Anthropic, cosine similarity, Sonnet curation
- Why it produces analytical readings (similarity clustering → depth)
- The convergence finding: Jaccard 0.057 but airtime ±2%
- Practical implications: when to use which

## Post 4: "Host Preparation: From Monologue to Dialogue"
- The problem: without scaffolding, LLMs produce expert monologues
- Phase 2.5a: pre-interviews (Haiku, 3 experts × 7 segments = 21 calls)
- What the LLM actually produces in pre-interviews (key points, quotes, disagreement angles)
- Phase 2.5b: question planning (Sonnet, 7 calls)
- Steering notes and cross-engagement targets
- The result: Q/seg jumps from ~1 to ~11, uniformly across 15 novels
- The retry logic story (API 500 killed Hard Times, now we retry 3×)

## Post 5: "Making It Sound Right: Structured Output for TTS"
- The script generation prompt (~250 lines)
- Sentence-level structured output: sentence_type, quote_mode, rate, pause_before/after, emphasis_words
- The quote handling pattern: setup → reading → commentary
- Voice assignment: Gemini TTS, per-speaker voices, accent direction
- The problem with hardcoded voices (interdisciplinary panel came out British)
- Cache strategy: per-turn audio caching for re-renders
- Audio assembly: segment breaks, leading/trailing pauses

## Post 6: "Pastiche, Not Hallucination: What LLMs Do When They Haven't Read the Book"
- The no-passages condition and what it reveals
- 5-tier verification: verified → paraphrase → distant echo → no source → invented
- The vocabulary autopsy: 82% of invented quotes use 90-100% of the novel's words
- The knowledge gradient: Middlemarch 57% → Hester 0%
- Within-author evidence controlling for prose style
- The analytical reinforcement hypothesis (with honest caveats)
- North and South: the adaptation outlier
- Measuring LLM literary knowledge as an unintended instrument

## Post 7: "What If I Put My Friends in the Podcast?"
- Creating custom expert panels (ExpertProfile + ExpertPersona)
- The interdisciplinary panel: Chen (NLP), Martinez (astronomy), Volkov (musicology)
- Sharpening Sarah Chen: how persona description controls linguistic precision
- "Metaphors but not methods": the scaffolding imports literary-critical norms
- The prompt critique: what would genuinely interdisciplinary encounter look like?
- American voices: accent direction in TTS

## Post 8: "Building This With Claude Code"
- The development workflow: beads for issue tracking, Claude Code for everything else
- What Claude Code is good at: parallel exploration, systematic data analysis, pipeline orchestration
- What it's bad at: making claims without evidence (the no-unsupported-claims policy)
- The three-document dialectic: thesis, rebuttal, synthesis
- Deploying to fly.dev: the tar pipe trick, the audio volume saga
- What I learned about human-AI collaboration on a real project
