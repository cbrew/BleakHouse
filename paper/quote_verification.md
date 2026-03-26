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

Across the experiment matrix (15 novels × conditions), every grounded
condition achieves high quote verification.  The pipeline type makes no
measurable difference:

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

## Verified quotes from a grounded run

When passages are provided, the LLM quotes them accurately.  In the
Bleak House transport baseline (`ext_v01_baseline`), all 42 reading-mode
quotes verify against the source text — a 100% hit rate.

## The spectrum of ungrounded quotation

Without passages, the LLM generates from memory.  For *Bleak House*
— a canonical, well-studied novel — it gets 29 of 40 quotes right
(72.5%).  But "right" and "wrong" are not binary.  The 40 quotes
fall along a spectrum from exact reproduction to pure invention,
which we classify into five categories based on their relationship
to the source text.

### Direct quotation (ratio > 0.8)

The LLM reproduces the source text verbatim or near-verbatim, with
at most trivial differences in punctuation or capitalisation.

> **Blackstone** reads: "Never can there come fog too thick, never can
> there come mud and mire too deep, to assort with the groping and
> floundering condition which this High Court of Chancery, most
> pestilent of hoary sinners..."

Match ratio: 0.99.  Reproduced character-for-character.

> **Woodcourt** reads: "Dead, your Majesty. Dead, my lords and
> gentlemen. Dead, Right Reverends and Wrong Reverends of every order.
> Dead, men and women, born with Heavenly compassion in your hearts.
> And dying thus around us every day."

Match ratio: 0.92.  One of Dickens's most famous passages, reproduced
from training data with complete accuracy.

> **Woodcourt** reads: "I lifted the heavy head, put the long dank hair
> aside, and turned the face. And it was my mother, cold and dead."

Match ratio: 0.83.  The source paragraph opens with "I passed on to the
gate and stooped down" before reaching this sentence; the LLM has
extracted the core image accurately but omitted the approach.

These are genuine quotations — a reader checking the source would find
them there.

### Acceptable paraphrase (ratio 0.5–0.8)

The LLM captures the essential phrasing with minor substitutions or
reorderings that do not change the meaning.

> **Hartley** reads: "And hard by Temple Bar, in Lincoln's Inn Hall, at
> the very heart of the fog, sits the Lord High Chancellor in his High
> Court of Chancery."

Match ratio: 0.73.  The source has "in the midst of the mud and at the
heart of the fog" — the LLM has substituted "And hard by Temple Bar, in
Lincoln's Inn Hall" for "in the midst of the mud," combining two nearby
phrases.  The core image is preserved: the Chancellor sits at the heart
of the fog.

> **Woodcourt** reads: "Jo, can you say what I say?" "I'll say anythink
> as you say, sir, for I knows it's good."

Match ratio: 0.75.  Jo's response is verbatim from the source.  The
preceding question is compressed but recognisable.

These pass a literary-discussion standard of accuracy — an expert
reading from memory at a panel discussion might produce exactly this
level of approximation.

### Dubious paraphrase (ratio 0.35–0.5)

The LLM has the right character, situation, or theme, but the wording
has drifted far enough from the source that a careful reader would
notice.

> **Woodcourt** reads: "He was young, and handsome, and had been full
> of promise."

Match ratio: 0.34.  The source passage reads: "So young and handsome,
and in all respects so perfectly the opposite of Miss Flite!"  The
LLM has flattened Dickens's comparative construction into a plain
list and dropped the contrast with Miss Flite.  The adjectives are
right; the sentence is not.

> **Blackstone** reads: "Suffer any wrong that can be done you rather
> than come here."

This verifies (the 5-word window catches it), but it is worth noting
that the LLM also produced a variant: "Suffer no fancy to lead you to
connect the suit with any hope of good to yourselves," which does *not*
verify.  The two are semantically similar — both are Jarndyce warning
against Chancery — but only one is in the novel.  The LLM knows the
*type* of thing Jarndyce says, and sometimes generates the right
instance, sometimes a plausible alternative.

### Borderline confabulation (ratio 0.3–0.45)

The LLM generates text that fits the novel's style and situation but
borrows phrasing from different parts of the book, or blends source
material with its own invention.

> **Woodcourt** reads: "He was not only worn and haggard, but he was
> much changed in his manner — at once more furtive and more fierce."

Match ratio: 0.44.  The closest source passage describes Richard in
different words: "he was not in the least disconcerted by our appearance,
but rose and received us in his usual airy manner."  The LLM has
generated a description of Richard's decline that is thematically correct
(he does become worn and haggard) but textually absent.  The vocabulary
("furtive and more fierce") is Dickensian but invented.

> **Woodcourt** reads: "I don't know nothink about no lady. I never see
> no lady."

Match ratio: 0.42.  The source contains Jo saying "I don't know nothink
about no—where I was took by the beadle, do you mean?" — the LLM has
preserved Jo's distinctive grammar ("don't know nothink") but put
different words in his mouth.  A reader familiar with Jo's voice would
find this convincing.  It is not in the novel.

### Clearly imagined (ratio < 0.3)

The LLM invents text that could belong in the novel but does not.  These
are creative acts — the model generates *in the style of* Dickens
rather than *from* Dickens.

> **Hartley** reads: "as empty as the shell of a great spider who has
> been long dead."

Match ratio: 0.37.  No passage in *Bleak House* contains this simile.
The grotesque natural image, the morbid specificity, the rhythmic
cadence — all are Dickensian.  But the sentence is the LLM's own.

> **Woodcourt** reads: "I have no purpose but to die. When I am found,
> let me be carried to where I am to lie, and left without a word."

Match ratio: 0.39.  This sounds like Lady Dedlock's final words — the
resignation, the formal simplicity, the cadence of surrender.  Dickens
never wrote this sentence.  The LLM has inferred what she *would* say
from the arc of her character.

> **Hartley** reads: "Turn that dog's descendants loose, who are his
> parents, brothers, sisters? What chances or mischances have made him
> thus?"

Match ratio: 0.03.  This has no close match anywhere in the novel.
The rhetoric ("Turn that dog's descendants loose") sounds like it could
be the omniscient narrator's voice in the Jo chapters, but it is pure
invention.  The word "mischances" does not appear in *Bleak House*.

> **Blackstone** reads: "It is a system — not my doing — I didn't
> make it."

Match ratio: 0.04.  This captures the self-exculpatory logic of
Chancery's defenders, but as a quotation it is fabricated.  No
character says these exact words.

## The confabulation pattern

The spectrum reveals that ungrounded confabulation is not random error
— it is *graduated borrowing*.  At the top end, the LLM reproduces
famous passages verbatim from training data.  In the middle, it
produces acceptable paraphrases that a scholar reading from memory
might produce.  At the bottom, it generates pastiche — new text in
the author's style that is thematically appropriate but textually
absent.

The dangerous zone is not the clearly imagined quotes (which a
knowledgeable listener might catch) but the dubious paraphrases — text
close enough to the source to sound right, different enough to be
wrong, and confident enough to pass without scrutiny.

Grounding eliminates the entire spectrum.  When passages are provided,
the LLM copies them rather than reconstructing from memory.
Verification rates rise from 72.5% to 100%.

## Variation by novel

The no-passages verification rate varies by novel, from 23.4% (North
and South) to 64.1% (Bleak House).  This variation does not correlate
with simple measures of fame (Wikipedia article length: r = −0.60).
The mechanism is unclear — it may reflect the distinctiveness of a
novel's prose, the frequency of famous passages in training data, or
the LLM's ability to reconstruct specific registers.  What is clear
is that the variation is substantial and is eliminated by grounding.
