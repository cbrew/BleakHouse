# Scientific Hypotheses for the BleakHouse Literary Podcast System

## System Overview

BleakHouse generates multi-voice literary discussion podcasts about novels. Three fictional experts discuss passages from a novel, guided by a host, producing a structured script that is rendered to audio via TTS.

### Key architectural features

**Pipeline phases.** The system runs in stages: (0) enrich every paragraph of the novel with 20 structured fields using a cheap LLM; (0.5) design episode segments; (1) select passages for each expert using min-cost flow optimisation; (2) assign passages to segments; (2.5, optional) host preparation via pre-interviews and question planning; (3) generate a multi-voice script with sentence-level TTS annotations; (4) render to audio.

**Expert personas.** Six stereotyped experts are available, three per episode. Each has a name, a scholarly perspective (literary critic, social historian, close reader, traditionalist, Marxist critic, performer), a demand profile (a vector over seven content dimensions), and a distinctive speaking style. The demand profile controls what passages the transport solver assigns to each expert.

**Passage grounding.** Selected passages are included verbatim in the script generation prompt. All experts see all passages assigned to their segment, creating shared material for cross-expert engagement. The system compares five selection strategies: min-cost flow transport (zero LLM tokens), embedding retrieval with LLM curation, plain RAG, random selection, and no passages (prior knowledge only).

**Seven provision dimensions.** Every passage is scored on: character_development, plot_advancement, thematic_depth, social_critique, humor_entertainment, atmosphere_setting, narrative_technique. These are the axes along which the transport solver matches passages to expert demands.

**Conversational design instructions.** The script generation prompt specifies: a three-part quote pattern (setup, reading, commentary), reactive language between experts, turn structure, inter-speaker timing, sentence-type classification, and prosodic annotations (rate, pause, emphasis) for TTS rendering.

**Host preparation (Phase 2.5).** An optional stage where a cheap LLM interviews each expert about their assigned passages, then a capable LLM synthesises these into a HostBrief: 3-5 targeted questions per segment, each directed at a named expert, with notes on who else should jump in. The HostBrief is injected into the script generation prompt alongside a system-prompt mandate for the host to ask prepared questions.

**Segment continuity.** Each segment is generated independently but receives context about the previous and next segment titles. Only the first segment includes a welcome and expert introductions; subsequent segments open with a brief bridge; the final segment ends with a sign-off.

**Confabulation detection.** For ungrounded runs (no passages), a post-hoc matcher slides a 5-word window across each quote utterance and searches all passages in the novel's enriched corpus. Matches are scored 0-1 and categorised as verified (>=0.6), paraphrase (0.3-0.6), or confabulation (<0.3).

### Novels currently in the system

Five novels spanning different authors, eras, and traditions: Dickens's *Bleak House* (1853) and *Our Mutual Friend* (1865), Eliot's *The Mill on the Floss* (1860), Gaskell's *North and South* (1855), and Forster's *A Passage to India* (1924). All are well-known canonical texts.

### Candidate novels for extension

Five lesser-known Victorian novels available on Project Gutenberg, ordered by likely LLM training exposure (most to least): Collins's *No Name* (1862), Gissing's *New Grub Street* (1891), Gissing's *The Odd Women* (1893), Oliphant's *Miss Marjoribanks* (1866), Oliphant's *Hester* (1883).

---

## Hypotheses

Each hypothesis is classified by primary interest:
- **ARCH** = architectural (what the system design causes)
- **AI** = artificial intelligence (what the LLM does or fails to do)
- **UX** = user experience and editorial control
- **LIT** = literary (what the system reveals about the novels or about literary discussion)

Hypotheses are ordered by scientific interest within each group.

---

### Architectural hypotheses

**H1. Cross-expert engagement is architecture-driven, not prompt-driven.** [ARCH]

Removing the "experts react to each other... not parallel monologues" instruction from the system prompt will not significantly reduce cross-expert referencing, because the shared-passage architecture (all experts see all passages) creates natural reason to engage. The active ingredient is that experts have shared material to react to, not that the prompt tells them to.

*Test:* Ablation A1 — remove the cross-engagement instruction, measure cross-referencing rate and expert-to-expert transition frequency. Compare against baseline with instruction present.

*Why it matters:* If confirmed, this means conversational coherence is a property of the information architecture, not prompt engineering. This is a much stronger design principle than "tell the LLM to be conversational."

---

**H3. Persona dominates content: framework dominance.** [ARCH]

Two passage selection algorithms that choose almost entirely different material (passage Jaccard < 0.05) produce scripts with converging vocabulary and character focus, because the persona — not the passage — determines what each expert says about the material. The expert's identity is so strong that it overrides the content it operates on.

*Test:* Transport vs embedding, same panel, same novel. Measure passage-level Jaccard (expected near zero), then per-expert TF-IDF vocabulary cosine across conditions (expected > 0.5).

*Why it matters:* This challenges the assumption that content selection is the primary determinant of generated text quality. If personas dominate, then the RAG literature's focus on retrieval quality may be less important than persona design for conversational applications.

---

**H13. The enrichment schema transfers across novels without modification.** [ARCH]

The seven provision dimensions capture different balances across Victorian and modernist novels but remain usable without schema redesign. No dimension is systematically empty or saturated for any novel in the current set.

*Test:* Provision distribution statistics across all novels. For each dimension, measure the fraction of passages rated "strong." A dimension is problematic if < 5% of passages are strong for any novel.

*Why it matters:* If the schema transfers, it means the enrichment layer is a genuine abstraction over literary content, not a Dickens-specific hack.

---

**H18. The enrichment schema is biased toward Dickensian features.** [ARCH]

The seven provision dimensions were designed with Dickens in mind. On novels with different strengths — Collins's plot machinery, Gissing's psychological realism, Oliphant's domestic comedy — some dimensions will be systematically under-supplied, distorting passage selection. This is a stress test of H13.

*Test:* Run enrichment on the five candidate novels. Measure provision distributions. Compare against the five existing novels. Identify any dimension with < 5% "strong" passages for any novel.

*Why it matters:* If the schema breaks on non-Dickensian novels, the system needs either novel-specific enrichment schemas or a more general dimension set. This is a fundamental design question about whether literary features can be captured in a fixed vocabulary.

---

### AI hypotheses

**H5. Grounding prevents confabulation regardless of selection method.** [AI]

Any form of passage grounding (transport, embedding, random, plain RAG) achieves > 90% quote verification, while ungrounded generation drops below 50%. The gap holds across all five current novels. The method of grounding matters far less than the fact of grounding.

*Test:* Five selection conditions across five novels, fuzzy 5-word subsequence quote matching against source text.

*Why it matters:* This establishes the minimum viable intervention for trustworthy LLM-generated literary discussion: provide passages. Everything else is optimisation.

---

**H9. The confabulation pattern is novel-dependent.** [AI]

No-passages confabulation rates correlate with the LLM's likely training exposure. Well-studied texts (Bleak House, Passage to India) have higher ungrounded verification rates than less-studied ones (North and South, Mill on the Floss). The LLM's prior knowledge is a measurable, novel-specific quantity.

*Test:* No-passages condition across all novels, quote verification rates. Rank by rate and compare against proxies for training exposure (e.g. Wikipedia article length, Gutenberg download count, scholarly citation frequency).

*Why it matters:* This quantifies LLM literary knowledge as an empirical variable, not a binary known/unknown.

---

**H16. The grounding gap widens dramatically for obscure novels.** [AI]

For genuinely obscure novels (Oliphant's Miss Marjoribanks, Hester), ungrounded quote verification will drop below 10%, making the grounding gap > 85 percentage points. The transport pipeline's passage grounding becomes essential rather than merely helpful.

*Test:* No-passages vs transport for Oliphant novels. Compare gap size against the five current novels.

*Why it matters:* This is the strongest possible argument for passage grounding. If the system can produce a coherent, accurately-quoted discussion of a novel the LLM barely knows, that demonstrates the architecture's value in a way that well-known novels cannot.

---

**H19. Confabulation takes a novel-specific form on obscure texts.** [AI]

When the LLM lacks training data for a novel, it does not produce random confabulations. Instead, it produces plausible-sounding Victorian prose borrowed from better-known novels. Confabulated "Oliphant quotes" will resemble real Dickens or Eliot passages. The confabulation detector can identify these cross-contaminations.

*Test:* Run the confabulation matcher on no-passages Oliphant episodes against all existing novels' passage corpora. Measure cross-novel false-positive rates: does a confabulated "Oliphant quote" match a real Dickens passage better than any real Oliphant passage?

*Why it matters:* This reveals the structure of LLM literary hallucination — it is not noise but systematic borrowing from the most similar well-known text. This has implications for any domain where LLMs generate content about material outside their training distribution.

---

**H4. The three-part quote pattern is prompt-driven.** [AI]

Removing the explicit setup-reading-commentary specification will cause quotes to appear but without consistent framing. The model has no inherent reason to produce this specific three-part structure without instruction.

*Test:* Ablation A2 — remove the quote pattern specification, measure quote pattern compliance.

*Why it matters:* This tests whether conversational micro-structure (the rhythm of setting up and unpacking a quotation) is a natural LLM behaviour or an artefact of explicit instruction. The answer determines how much prompt engineering is needed for structured conversational output.

---

**H7. Prosodic annotations are prompt-driven and meaningful.** [AI]

Removing rate and pause timing guidance will cause rate values to collapse to 1.0 and pause distributions to become uniform, destroying the prosodic variation that TTS rendering depends on. The LLM does not naturally produce fine-grained prosodic control without instruction.

*Test:* Ablation A3 — remove rate/pause guidance, measure rate standard deviation and pause distribution entropy.

*Why it matters:* This tests whether LLMs can serve as prosody controllers for TTS when given structured output schemas. If confirmed, it validates the design decision to push prosodic control into the script generation phase rather than the TTS phase.

---

### UX and editorial hypotheses

**H2. Host preparation transforms monologue into dialogue.** [UX]

Adding Phase 2.5 host prep increases question frequency from < 1 to 3-5 per segment and reactive markers by > 3x, while preserving expert identity signatures. The host becomes an active interviewer rather than a passive presenter.

*Test:* With vs without --host-prep, same passages, same panel. Measure question frequency, reactive markers, host word fraction, expert airtime proportions.

*Preliminary result:* Confirmed. 0.4 to 5.9 questions/seg (constrained version), 5x reactive markers, expert airtime shifts < 5 percentage points.

*Why it matters:* This demonstrates that conversational steering is a manipulable lever. The same passages and experts produce qualitatively different conversations depending on whether the host has done homework.

---

**H8. Demand-profile manipulation produces predictable passage shifts.** [UX]

Peaking each expert's demand vector (concentrating on their defining dimension) reshapes the passage set substantially (Jaccard with baseline < 0.55), while additive manipulation (increasing arc demands) adds passages proportionally. The transport formulation makes editorial intention legible as flow changes.

*Test:* Peaked vs high-arc vs baseline, transport only. Measure passage-level and chapter-level Jaccard.

*Why it matters:* This is the core manipulability claim. If demand profiles produce predictable, inspectable changes, the system offers editorial control that embedding-based retrieval fundamentally cannot match.

---

**H14. Transport manipulability enables zero-cost editorial exploration.** [UX]

Re-solving a min-cost flow after demand profile changes takes < 1 second and zero LLM tokens. Over N exploratory configurations, transport saves N x 15K Sonnet tokens vs embedding, enabling a preview-before-commit workflow impossible with retrieval.

*Test:* Timing and token accounting across N configurations. Measure time-to-preview for transport vs embedding.

*Why it matters:* This is the practical cost argument. Even if the scripts are similar in quality, transport's exploration cost advantage compounds with iteration — the user can try 20 demand configurations in the time it takes to run one embedding curation.

---

**H11. Segment length constraints preserve conversational gains.** [UX]

Adding a ~1,500 word/segment target reduces episode length by > 25% from unconstrained host-prep while retaining > 80% of the question frequency and reactive marker gains. The constraint forces prioritisation without destroying the conversational format.

*Test:* Constrained vs unconstrained host-prep, same passages.

*Preliminary result:* Confirmed. 12% length reduction, 84% of questions retained, 84% of reactive markers retained. Target slightly overshot (1,707 avg vs 1,500 target).

*Why it matters:* This shows that conversational quality and length are separable — you can have the dialogue gains of host preparation without doubling the episode length.

---

### Literary and generalization hypotheses

**H6. Expert prominence adapts to textual affordance.** [LIT]

Trevelyan's (the performer's) airtime decreases monotonically across novels as performative material decreases: Our Mutual Friend > Bleak House > Mill on the Floss > Passage to India > North and South. The system responds to genuine variation in what a novel offers each expert.

*Test:* Transport condition, all-swapped panel (Trevelyan, Leigh, Rosen), all five novels. Measure per-expert word count as fraction of total expert words.

*Why it matters:* If expert prominence adapts to the text, the system is doing something more interesting than applying uniform stereotypes. It is reading the novel through each expert's lens and finding different amounts of material. This is a form of automated literary analysis.

---

**H17. Expert personas degrade gracefully on unfamiliar material.** [LIT]

On novels the LLM has limited knowledge of, experts will still produce coherent discussion (because the passages provide content), but their characteristic vocabulary signatures will weaken. The system adapts by redistributing airtime rather than producing incoherent output.

*Test:* Expert TF-IDF cosine between familiar novels (Dickens) and unfamiliar (Oliphant), per expert. Airtime proportions across all novels including new candidates.

*Why it matters:* Graceful degradation is a stronger property than correct behaviour on well-known material. If the system produces reasonable literary discussion of a novel it barely knows, that demonstrates the architecture's robustness in a way that Bleak House never can.

---

**H10. Host preparation does not dilute expert identity.** [LIT]

Despite the host asking more targeted questions and experts engaging more reactively, per-expert TF-IDF vocabulary signatures remain stable (cross-condition cosine > 0.8) between prepared and unprepared runs. The experts retain their distinctive voices even under more active steering.

*Test:* TF-IDF cosine between hostprep and baseline runs, per expert, same panel, same novel.

*Why it matters:* This tests whether conversational steering and expert identity are independent levers. If they are, designers can adjust one without disturbing the other — a desirable compositionality property.

---

**H20. Host preparation compensates for LLM ignorance.** [LIT]

On obscure novels where the LLM has limited prior knowledge, host preparation should help more than on well-known novels. The pre-interviews force experts to engage with the specific passages provided rather than falling back on nonexistent prior knowledge. The hostprep lift in question frequency and reactive markers should be larger for Oliphant than for Dickens.

*Test:* Hostprep delta (with vs without) on Bleak House vs Miss Marjoribanks, same panel.

*Why it matters:* This would show that the system's components interact non-additively: host prep + transport grounding together compensate for LLM ignorance in a way that neither achieves alone. This is an argument for the full pipeline, not just individual components.

---

**H12. Sentence-type classification is partially redundant.** [AI]

Removing the 8-type sentence classification requirement will not significantly change the functional variety of utterances. The model naturally produces analysis, questions, and transitions in literary discussion without being told to label them.

*Test:* Ablation A4 — remove sentence-type classification, measure sentence-type entropy (by human annotation or proxy).

*Why it matters:* Identifying redundant prompt instructions is valuable for simplifying the system. If confirmed, the sentence-type field can be removed from the output schema, reducing prompt complexity and token cost.

---

**H15. Inter-speaker timing guidance is prompt-driven but low-impact.** [AI]

Removing the inter-speaker timing table will change pause_before_ms distributions but not significantly affect perceived conversational quality. Listeners are insensitive to small timing variations in the 100-400ms range.

*Test:* Ablation A6 — remove timing guidance, measure pause distributions. Ideally, a listening study comparing with-timing and without-timing audio.

*Why it matters:* This is the least scientifically important hypothesis, included for completeness. If timing guidance has low impact, it can be simplified or removed. If it has high impact, it validates the design decision to control prosody at the script level.
