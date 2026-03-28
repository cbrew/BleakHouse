# Host Preparation Prompt: Suitability for Interdisciplinary Panels

## Context

The host preparation prompts (Phase 2.5a pre-interviews and Phase 2.5b
question planning) were designed for literary-critical expert panels
(Hartley/Blackstone/Woodcourt). We assess their suitability for the
interdisciplinary American panel (Chen NLP, Martinez astronomy, Volkov
musicology) based on the output of `interdisciplinary_trn_hostprep`.

## Arguments that the prompt works

**1. It is genuinely generic.** The system prompt says "literary
discussion" and asks about "passages," "disagreement," and "what will
make good radio." None of this assumes the experts are literary
scholars. It works for anyone discussing a text.

**2. The output proves it.** Elena Volkov's pre-interview produced
Soviet bureaucracy parallels to Chancery. Sarah Chen produced syntactic
analysis of agent deletion in the fog passage. Rebecca Martinez
compared the fog to protoplanetary disk opacity. The prompt gave them
room to bring their own frameworks without constraining them to
literary-critical vocabulary.

**3. The `{expert_description}` injection does the real work.** The
prompt inserts the full persona description (from
`ALTERNATIVE_PERSONAS`), which is where the interdisciplinary
specificity lives. The surrounding instructions are scaffolding: "what
strikes you, where would you push back, what do you want to quote."
These are productive questions for anyone engaging with a text.

**4. "Pub with smart friends, not conference panel" is the right
register.** An NLP researcher, an astronomer, and a musicologist
discussing Bleak House in a pub is exactly the tone the prompt
solicits. This register is more hospitable to interdisciplinary
exchange than an academic panel format would be.

## Arguments against

**1. "Which passage would they most want to quote aloud" assumes
literary-critical quotation practice.** An astronomer does not
naturally "want to quote aloud." She might want to point to a passage,
describe an image, or draw an analogy to stellar formation. The
framing steers all three experts toward the same behaviour — close
reading and quotation — which is a literary norm, not a universal one.
The prompt imports this norm without acknowledging it.

**2. "Where might they disagree with the other experts" presupposes a
literary-debate model.** Scientists more naturally qualify and build on
than disagree. The prompt imports an adversarial seminar dynamic that
may not match how Martinez or Chen would naturally engage with a text.
The generated disagreements (Martinez vs Volkov on whether "inevitable"
is a critique or a description) are compelling, but they are the
prompt's framing, not an organic interdisciplinary encounter.

**3. The prompt does not ask what the experts' own fields illuminate.**
It asks what strikes them about the passages and where they would push
back — but it does not ask "what does your field bring to this that
literary criticism doesn't?" or "what would a reader from your
discipline notice that a literary scholar would miss?" The
interdisciplinary value has to emerge incidentally from the persona
description rather than being solicited directly.

**4. "Reference passage IDs and actual text" is pipeline
scaffolding.** This instruction exists for infrastructure reasons (the
output needs passage_ref fields for the manifest). Scientists engaging
with text do not naturally think in passage IDs. The instruction is
harmless — the LLM complies and the output is well-formed — but it is
a literary-technical directive wearing the clothes of a natural
question.

**5. The question planning prompt frames everything as "literary
discussion."** The phrase appears repeatedly. This framing may cause
the LLM to pull the interdisciplinary experts back toward
literary-critical norms — producing, in effect, three literary critics
with unusual metaphors rather than three genuinely different
disciplinary perspectives encountering a novel.

## Evidence from the output

The generated pre-interviews are high quality. Volkov draws Cold War
institutional parallels. Chen identifies agent deletion as a syntactic
strategy. Martinez reads fog as a physical formation condition. These
are recognisably different perspectives.

However, all three ultimately produce literary-critical discourse:
close readings, passage quotations, interpretive arguments about
authorial intention. Volkov does not produce musicological analysis
(rhythm, counterpoint, structural form). Chen does not produce
computational analysis (n-gram patterns, syntactic dependency trees,
information-theoretic measures). Martinez does not produce
observational methodology (what would you measure, what hypothesis
would you test). They bring their metaphors but not their methods.

Whether this matters depends on the goal.

## Verdict

**If the goal is "interesting literary discussion from unusual
perspectives"** — the current prompt delivers. The interdisciplinary
backgrounds provide distinctive metaphors and framings that
literary-only panels do not produce. The output is engaging and
distinctive.

**If the goal is "genuinely interdisciplinary encounter with a text"**
— the prompt would need revision. It currently domesticates the
interdisciplinary experts into literary-critical behaviour. A revised
prompt might:

- Ask "what does this passage look like through the lens of your
  field?" rather than "what strikes you?"
- Ask "where does your expertise see something the literary critics
  would miss?" rather than "where would you push back?"
- Replace "which passage would you most want to quote aloud?" with
  "which passage would you most want to analyse using the tools of
  your discipline?"
- Remove the "literary discussion" framing from the question planning
  prompt and replace it with "interdisciplinary discussion" or simply
  "discussion"

These changes would risk less polished output (the literary-critical
framing produces reliably coherent discussion) but might produce more
genuinely surprising interdisciplinary encounters.

## Implications for the research

This critique connects to the framework dominance finding (DH1): the
prompt functions as an additional interpretive framework alongside the
persona. Even when the persona is an astronomer, the prompt pulls her
toward literary-critical behaviour. This is a concrete example of how
the system's architecture shapes output independently of content — and
a reminder that "framework dominance" operates at multiple levels, not
just the persona level.
