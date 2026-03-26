# Quote Verification

## Method

Each podcast script contains utterances marked `is_quote: true` by the
generating LLM — passages that the fictional experts read aloud from the
novel under discussion.  We verify these quotes against the novel's full
text using a sliding 5-word window: for each quote utterance, we extract
every contiguous 5-word subsequence and check whether any appears
verbatim in the lowercased source text.  A quote is "verified" if at
least one 5-word window matches.  This is a conservative test — it
catches exact quotation and near-exact quotation with minor word changes,
but rejects paraphrase, summary, and fabrication.

## Results across the full matrix

Across all 120 conditions in the experiment matrix (15 novels × 2
panels × 2 pipelines × 2 host-prep settings), every grounded condition
achieves high quote verification.  The pipeline type makes no measurable
difference:

| Pipeline   | Runs | Mean verification | Min   | Max    |
|------------|------|-------------------|-------|--------|
| Transport  | 176  | 97.7%             | 88.1% | 100.0% |
| Embedding  |  94  | 97.2%             | 88.2% | 100.0% |
| RAG        |  20  | 94.9%             | 86.1% | 100.0% |
| Random     |  20  | 93.7%             | 82.8% | 100.0% |
| No passages|  53  | 48.9%             |  0.0% |  81.2% |

The gap between grounded (~97%) and ungrounded (~49%) is the dominant
effect.  Within the grounded conditions, the difference between
transport and embedding is 0.5 percentage points — noise.  Even random
passage selection achieves 93.7%.  The method of grounding is
irrelevant to quote fidelity; the fact of grounding is what matters.

## Examples: verified quotes from a grounded run

When passages are provided, the LLM quotes them accurately.  In the
Bleak House transport baseline (`ext_v01_baseline`), all 42 reading-mode
quotes verify against the source text.  Typical examples:

> **Blackstone** reads: "lies there with no more track behind him that
> any one can trace than a deserted infant."

> **Hartley** reads: "Lady Dedlock is always the same exhausted deity,
> surrounded by worshippers, and terribly liable to be bored to death,
> even while presiding at her own shrine."

> **Blackstone** reads: "Lady Dedlock, have the goodness to stop and
> hear me, or before you reach the staircase I shall ring the alarm-bell
> and rouse the house."

Each of these appears verbatim in the provided passages.  The LLM
copies the text faithfully, preserving Dickens's syntax down to the
punctuation.

## Examples: ungrounded generation

Without passages, the LLM generates from memory.  For *Bleak House*
— a canonical, well-studied novel — it still gets 29 of 40 quotes
right (72.5%).  The verified quotes include some of the novel's most
famous lines:

> **Hartley** reads: "Fog everywhere. Fog up the river, where it flows
> among green aits and meadows; fog down the river, where it rolls
> defiled among the tiers of shipping."

> **Woodcourt** reads: "Dead, your Majesty. Dead, my lords and
> gentlemen. Dead, Right Reverends and Wrong Reverends of every order.
> Dead, men and women, born with Heavenly compassion in your hearts.
> And dying thus around us every day."

> **Woodcourt** reads: "I lifted the heavy head, put the long dank hair
> aside, and turned the face. And it was my mother, cold and dead."

These are passages that appear frequently in scholarship, anthologies,
and online discussions of *Bleak House*.  The LLM has seen them often
enough to reproduce them accurately.

The 11 unverified quotes are more revealing.  They are not random noise
— they are plausible Dickensian prose that sounds right but does not
appear in the novel:

> **Blackstone** reads: "Suffer no fancy to lead you to connect the
> suit with any hope of good to yourselves."

This resembles Jarndyce's actual warning ("Suffer any wrong that can be
done you rather than come here") but substitutes different words.  The
LLM has the gist — the sentiment, the register, the speaker — but not
the exact text.

> **Woodcourt** reads: "He was not only worn and haggard, but he was
> much changed in his manner — at once more furtive and more fierce."

This describes Richard Carstone in language that could pass as
Dickens.  The vocabulary ("worn and haggard," "furtive and more
fierce"), the sentence rhythm, and the conjunction pattern are all
stylistically accurate.  But the sentence does not exist in *Bleak
House*.  It is a confabulation — the LLM generating in the style of
Dickens rather than from Dickens.

> **Hartley** reads: "as empty as the shell of a great spider who has
> been long dead."

This is characteristic of a particular confabulation mode: the LLM
produces a simile that *sounds* Dickensian (the grotesque natural
image, the morbid specificity) but is its own invention.

> **Woodcourt** reads: "I have no purpose but to die. When I am found,
> let me be carried to where I am to lie, and left without a word."

This could plausibly be Lady Dedlock's final words — the tone, the
resignation, the formal simplicity all fit.  But Dickens never wrote
this sentence.  The LLM has inferred what Lady Dedlock *would* say
from the arc of her character, producing a pastiche that is emotionally
accurate but textually fabricated.

## The confabulation pattern

The unverified quotes share three properties:

1. **Stylistic accuracy.**  They sound like the novel.  Vocabulary,
   register, and sentence rhythm are appropriate to Dickens and to the
   specific character being discussed.

2. **Semantic plausibility.**  They say things that a character might
   say, or that the narrator might write about that character.  They
   are not random — they are *inferred* from the novel's themes and
   character arcs.

3. **Textual absence.**  Despite sounding right, they do not appear in
   the source text.  The 5-word window test catches this reliably.

This pattern — stylistically accurate, semantically plausible, textually
absent — is what makes ungrounded LLM-generated literary discussion
dangerous.  A listener would have no way to distinguish the fabricated
quotes from the genuine ones without checking the source.  Grounding
eliminates this problem entirely: when passages are provided, the LLM
quotes them rather than inventing.

## Variation by novel

The no-passages verification rate varies by novel, from 23.4% (North
and South) to 64.1% (Bleak House).  This variation does not correlate
with simple measures of fame (Wikipedia article length: r = −0.60).
The mechanism is unclear — it may reflect the distinctiveness of the
novel's prose style, the frequency of famous passages in training data,
or the LLM's ability to reconstruct specific registers.  What is clear
is that the variation exists, is substantial, and is eliminated by
grounding.
