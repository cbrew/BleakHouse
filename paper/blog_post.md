# The Reader Makes the Reading

## What happens when you give an LLM fifteen novels, three critics, and a microphone

I've spent the last few months building a system that generates literary discussion podcasts. Not summaries, not reviews — actual multi-voice conversations in which three expert panelists and a host discuss novels, quote passages, disagree with each other, and occasionally say things that surprise me.

The system works well enough that you can listen to the results. But the interesting part isn't the podcasts themselves. It's what the experiments revealed about how interpretation works — or more precisely, about where the creative agency sits when an LLM is doing the interpreting.

## The setup

Take a Victorian novel. Parse it into passages. Annotate each passage with an enrichment schema: interest score, seven "provision dimensions" (character development, social critique, narrative technique, etc.), characters present, themes, quotability. Then select passages for discussion using one of several algorithms, and hand them to an LLM along with expert personas and conversational scaffolding instructions. Out comes a structured podcast script — turns, quotations, prosodic annotations — which can be rendered to audio via TTS.

I tested this across 15 novels (Dickens, Eliot, Gaskell, Forster, Collins, Gissing, Oliphant), 180 experimental conditions, and about 60,000 passages. The 180 conditions cross novels with panels (two different expert trios), pipelines (transport, embedding, no-passages), and host preparation (with and without).

## The finding that shouldn't have surprised me but did

Two of the passage-selection algorithms — one based on min-cost network flow, the other on contextual embeddings — select almost entirely different passages. Jaccard similarity: 0.057. That's fewer than 6% of passages in common.

The min-cost flow method selects broadly: 59 passages from 28 chapters, weighted toward character development and plot. Call it the synoptic reader — the one who assigns the whole novel.

The embedding method selects narrowly: 32 passages from 20 chapters, weighted toward social critique and thematic depth. Call it the analytical reader — the one who curates a dossier of key passages.

These are recognisably different scholarly strategies. In a seminar room you'd notice the difference. But in the generated discussions, you can barely tell them apart. Expert airtime — each panelist's share of the conversation — varies by less than 2 percentage points regardless of which algorithm did the selecting.

The interpretive framework dominates. The reading strategy doesn't.

This is Fish's thesis — that meaning is reader-constructed, not text-extracted — tested at scale across 15 novels. And it holds. A Marxist reading of Cranford and a Marxist reading of Hard Times select different evidence but produce the same analytical character. The reader makes the reading.

## The friends panel

The default panelists are literary scholars: a formalist, a social historian, a close reader. Stereotypes, honestly, but useful ones. For fun, I replaced them with three Americans from outside literary studies: a computer scientist who specialises in speech recognition and NLP, an astronomer who studies stellar formation, and a musicologist who studies Cold War cultural diplomacy.

The astronomer reads Dickens's fog as a physical formation condition — opacity is not metaphor but the baseline state of complex systems. The NLP scientist analyses agent deletion in the opening sentences: "There is no main clause. It is a sequence of noun phrases and participial clauses with no finite verb until paragraph two." The musicologist compares Chancery to Soviet institutions that consumed the artists they were supposed to support.

Two things happened. First, the framework dominance finding still held — even with radically different personas, the discussions were structurally convergent. Second, the experts brought their metaphors but not their methods. The astronomer didn't propose measurements. The NLP scientist didn't run a parser. They produced literary-critical discourse decorated with disciplinary imagery, because the host preparation prompts ("what strikes you about these passages?") import literary-critical norms regardless of the persona.

This is itself a finding about where creative constraint operates: not just in the persona but in the conversational scaffold.

## Reading without having read

The no-passages condition is where things get genuinely interesting. With no source passages, the LLM must discuss the novel from prior knowledge alone. It's the computational equivalent of the seminar participant who didn't do the reading.

Pierre Bayard wrote a delightful book arguing that "non-reading" is a spectrum — books skimmed, books heard about, books forgotten. Our system provides the first computational test of his claim. And the results confirm his intuition, with a twist: we can measure the degradation.

For Middlemarch — canonical, widely taught, endlessly discussed — the LLM produces verifiable quotes 57% of the time. For Hester, an Oliphant novel that barely registers in modern literary culture, the rate drops to zero.

All fifteen novels are on Project Gutenberg. The raw text is almost certainly in the training data. What varies is the analytical reinforcement — the volume of study guides, Wikipedia articles, academic papers, and blog posts that quote and re-quote specific passages. Carlini et al. showed that LLM memorisation grows with data duplication. For novels, the relevant duplication isn't the Gutenberg text (which appears once) but its most-quoted passages, duplicated across thousands of secondary sources for canonical works and virtually none for obscure ones.

The within-author evidence is the most compelling part. Among Dickens's four novels: Bleak House (53% verified) > David Copperfield (44%) > Hard Times (39%) > Our Mutual Friend (29%). Same author, same prose style, different critical prominence, different quote fidelity.

## Pastiche, not hallucination

When the LLM can't quote accurately, what does it do? It doesn't produce gibberish. It produces pastiche.

We performed a vocabulary autopsy on 726 invented quotes — passages the LLM attributed to novels but which don't exist anywhere in the text. 82% of these invented quotes draw 90-100% of their individual words from the novel's own vocabulary. The mean overlap is 95%.

The system is writing *in the style of* the novel rather than *from* the novel. It recombines real vocabulary into plausible-but-nonexistent sequences. "I am very weak, but I shall begin the world" — every word appears in Bleak House, but this exact sentence doesn't. Classic Dickensian sentiment, constructed from Dickens's own word stock.

In literary-critical terms, this is pastiche — imitation of an author's manner without direct quotation. And the graduated nature of the imitation (from verbatim reproduction of the fog opening to pure invention for obscure Oliphant novels) makes it measurable. Confabulation rate, it turns out, is an instrument for measuring LLM literary knowledge.

## What I think this means

The system's value isn't in any individual podcast, though some of them are genuinely good (the interdisciplinary panel on Bleak House is my favourite). The value is in making the space of possible interpretations navigable.

A human editor can swap critical lenses, adjust demand profiles, add or remove scaffolding, compare grounded and ungrounded conditions — and each variation reveals something about the relationship between reader and text. The passage-selection step runs in under 100ms with no LLM calls. You can preview dozens of configurations before committing to the expensive generation step.

This is Boden's exploratory creativity: systematic traversal of an interpretive space defined by critical perspectives and textual affordances. The human defines the space. The machine renders the view. The human evaluates the result.

Whether any of this constitutes "creativity" is, I think, the right question for the computational creativity community to argue about. My own view: the LLM is a realiser, not a creative agent. But the ability to vary systematically at scale produces surprises — not through generative novelty but through comparison. And surprise-through-comparison deserves a place in the vocabulary alongside surprise-through-generation.

## Try it

The tracker, reports, and audio are live at [bleakhouse-demo.fly.dev](https://bleakhouse-demo.fly.dev). You can browse the 180-condition experiment matrix, listen to generated episodes (including the friends panel with American voices), and drill down into passage backlinks, host preparation data, and quote verification for every run.

The code is at [github.com/cbrew/BleakHouse](https://github.com/cbrew/BleakHouse).
