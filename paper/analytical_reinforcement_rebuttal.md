# Document 2: Rebuttal — Against the Analytical Reinforcement Thesis

## Overview

Document 1 claims that LLM quote fidelity tracks "analytical reinforcement" — the volume of secondary discussion that re-quotes specific passages.  The claim is seductive.  It is also, on close examination, under-determined, confounded, and in several respects misleading.  We dispute each major claim in turn.

## Objection 1: The correlation is inflated by the outlier exclusion

The headline number — r = 0.89 — is obtained by removing North and South from the dataset.  With all 15 novels, r = 0.72.  Excluding a data point because it is inconvenient and then reporting the improved correlation is a textbook example of post-hoc rationalisation.

The justification offered (BBC adaptation inflates Goodreads ratings) is plausible but unverified.  Cranford also has a well-known BBC adaptation (2007, starring Judi Dench) and its Goodreads count (48,000) is also partially adaptation-driven — yet it is not excluded.  Daniel Deronda had a 2002 BBC adaptation — also not excluded.  The exclusion of North and South is motivated by the desire for a cleaner correlation, not by a principled criterion.

**If the analysis requires excluding outliers to work, it does not work.**

## Objection 2: The attention score is ad hoc

The composite score combines three heterogeneous proxies (Goodreads ratings, Wikipedia word count, study guide presence) with equal weights and no theoretical justification.  Why equal weights?  Why these three proxies and not others?  Why log-normalise Goodreads but linearly normalise Wikipedia?

Different weighting schemes would produce different correlations.  The analysis did not test the sensitivity of r to the weighting.  A score that optimises correlation with the dependent variable and then reports that correlation is circular.

More fundamentally: the "attention score" conflates several distinct phenomena:
- **Contemporary readership** (Goodreads)
- **Encyclopaedic coverage** (Wikipedia)
- **Curriculum presence** (study guides)

These are correlated but not identical.  A novel can be encyclopaedically notable without being widely read (Daniel Deronda) or widely read without being encyclopaedically covered (North and South, per the thesis).  Collapsing them into a single number obscures more than it reveals.

## Objection 3: We don't know what's actually in the training data

The central claim — that memorisation tracks duplication of secondary sources — rests on an assumption about training data composition that we cannot verify.  We do not know:

- Which version of each novel is in the training data (Gutenberg? Wikisource? A different digitisation?)
- How many times each novel appears across the training corpus
- Whether the secondary sources we cite (SparkNotes, Wikipedia, academic papers) are in the training data at all, or to what degree
- Whether training data deduplication removed some copies

Carlini et al.'s finding that memorisation grows with duplication is about *observed duplication within the training set*.  We are using *proxies for imagined duplication in a training set we cannot inspect*.  The gap between these is large.

For proprietary models like Claude (which we use), the training data composition is not disclosed.  For all we know, Anthropic's training pipeline includes copyright filtering that removes Gutenberg texts, or upsampling that duplicates obscure novels.  We simply do not know.

## Objection 4: The verification metric conflates multiple phenomena

The "nop verification rate" — the fraction of LLM-generated quotes that match the novel's text — conflates at least three distinct abilities:

1. **Verbatim recall**: can the model reproduce a specific passage from memory?
2. **Plausible construction**: can the model construct something that sounds like the author?
3. **Knowledge of what is quotable**: does the model know which passages are typically quoted?

A high nop verification rate might mean the model memorised the text (Claim 1 interpretation).  Or it might mean the model knows which passages are famous — because they are discussed in secondary literature — and can reconstruct approximate versions.  These are different mechanisms with different implications.

The 5-tier matching (verified / paraphrase / distant echo / no clear source / invented) partially addresses this, but the "verified" category (≥60% match) is still quite loose — a 60% match is a paraphrase by most standards.

## Objection 5: Author effects are confounded with novel effects

The top of the table is dominated by Dickens and Eliot; the bottom by Gissing and Oliphant.  This is not just a novel-level effect — it is an author-level effect.  The LLM may be better at quoting Dickens not because Bleak House has more secondary discussion but because:

- **Dickens's prose is more distinctive** and therefore more memorisable (rhythmic, rhetorical, repetitive)
- **The training data contains more Dickens** in general (letters, adaptations, criticism of all his works)
- **Dickens's vocabulary is more predictable** given a few seed words

Oliphant's prose, by contrast, is more conventional mid-Victorian — grammatically complex but stylistically less distinctive.  The model may struggle to reproduce her passages not because of insufficient reinforcement but because her prose is harder to compress into the model's learned distributions.

We cannot distinguish "this novel is analytically under-discussed" from "this author's style is harder to memorise" with our data.

## Objection 6: n = 15 is too small for the claims being made

Fifteen novels is enough to spot a trend but not enough to draw reliable statistical conclusions.  With 15 data points, a Pearson correlation of 0.72 has a wide confidence interval.  Removing one point changes r from 0.72 to 0.89, which tells you how fragile the estimate is.

The claim that "79% of variance is explained by critical attention" (r² = 0.79, from the outlier-excluded r = 0.89) overstates the precision.  A bootstrap or permutation test would likely show that the 95% confidence interval for r includes values as low as 0.5.

## Objection 7: The causal direction is ambiguous

Even if the correlation is real, the causal story is unclear.  Document 1 implies:

> More secondary discussion → more passage duplication in training data → better LLM memorisation → higher nop verification

But the causal chain could equally be:

> More famous/canonical novel → both more secondary discussion AND more training data exposure → correlation without one causing the other

"Critical attention" and "training data exposure" may both be effects of a common cause — canonical status — rather than one causing the other.

## Objection 8: The Bayard connection is strained

Bayard's argument is about *human* non-reading — the claim that educated people navigate literary culture through social positioning, reputation, and fragments rather than through full engagement with texts.  Mapping this onto LLM behaviour requires assuming that the LLM's training process is analogous to human cultural absorption.  It is not.  The LLM has no cultural positioning, no social motivation, no memory of reading experiences.  It has weight distributions learned from text.

The metaphorical connection is charming but intellectually dubious.  Saying the LLM has "read" Middlemarch more thoroughly than Hester because its training data contains more Middlemarch-adjacent text is a category error — or at best, a metaphor that should be explicitly flagged as such.

## Objection 9: Contemporary vs. present-day readership is not examined

Document 1 mentions "contemporary readership" in passing but does not measure it.  Several of our novels were popular successes in their own time:

- **Miss Marjoribanks** was well-received in 1866 and Oliphant was one of the most prolific and popular Victorian authors
- **No Name** was a bestseller and Collins was more commercially successful than Eliot in the 1860s
- **Hester** was reviewed in all the major periodicals

If "critical attention" is what matters, we should test whether *historical* critical attention (Victorian reviews, 19th-century reception) correlates with nop verification.  It almost certainly does not — because Victorian critical reception is barely digitised and unlikely to be in web-scraped training corpora.  This would support the training-data interpretation.  But it has not been tested.

## Objection 10: The "passage-quoting attention" refinement is unfalsifiable

After the North and South outlier embarrasses the main thesis, Document 1 retreats to a narrower claim: what matters is not generic attention but specifically "passage-quoting attention" — secondary literature that reproduces specific textual fragments.

This refinement is not measured.  No data is presented on passage-quoting frequency.  It is invoked to explain away a failure and then dropped.  If the refined claim were tested (e.g., by counting how many times specific passages from each novel appear on the web), it might hold up.  Or it might not.  As stated, it is a hypothesis, not a finding.

## Summary

The analytical reinforcement thesis is a compelling narrative built on fragile evidence.  The correlation is real but moderate (r = 0.72), inflated to impressive (r = 0.89) by excluding an inconvenient outlier.  The attention score is ad hoc.  The causal mechanism is assumed, not demonstrated.  Author effects are confounded with novel effects.  The sample is too small for confident inference.  And the Bayard connection, while evocative, is a metaphor doing the work of an argument.

The thesis should be presented as what it is: a suggestive hypothesis supported by a moderate correlation, not a demonstrated causal mechanism.
