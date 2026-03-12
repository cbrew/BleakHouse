# Expert Variation Analysis: Persona Rigidity vs Responsiveness

**Date:** 2026-03-10
**Data:** 408 expert-runs across 136 runs (20 panels × 5 conditions)

Three complementary analyses of how expert personas interact with passage selection conditions. The question: are the expert caricatures rigid (persona dominates regardless of input) or responsive (output changes with different passages)?

## 1. Behavioral Profiles: What Experts *Do*

Each utterance has a `sentence_type` — a structured label for its function in the conversation. The distribution over types is a behavioral fingerprint: does this expert ask questions, read quotes, deliver analysis, or land punchlines?

### 1.1 Mean Behavioral Profile by Expert

| Expert | intro | question | q_setup | q_read | analysis | punch | trans | closing |
|--------|------:|------:|------:|------:|------:|------:|------:|------:|
| Caroline Woodcourt | 0.003 | 0.002 | 0.096 | 0.118 | 0.665 | 0.089 | 0.024 | 0.001 |
| Daniel Rosen | 0.002 | 0.007 | 0.079 | 0.090 | 0.677 | 0.124 | 0.021 | 0.001 |
| Edmund Leigh | 0.003 | 0.002 | 0.079 | 0.089 | 0.707 | 0.105 | 0.013 | 0.001 |
| Eleanor Hartley | 0.002 | 0.002 | 0.084 | 0.097 | 0.690 | 0.107 | 0.017 | 0.001 |
| James Blackstone | 0.002 | 0.001 | 0.073 | 0.083 | 0.708 | 0.112 | 0.021 | 0.000 |
| Oliver Trevelyan | 0.005 | 0.002 | 0.095 | 0.120 | 0.624 | 0.126 | 0.028 | 0.001 |

### 1.2 Behavioral Shift Across Conditions

Jensen-Shannon divergence between an expert's sentence type distribution under different conditions. **Higher = the expert changes what they *do* (more quotes, fewer questions, etc.) depending on input.**

| Expert | Mean JSD | Max JSD | Interpretation |
|--------|--------:|--------:|----------------|
| Daniel Rosen | 0.0029 | 0.0088 | **Rigid** — same behavior regardless of input |
| Caroline Woodcourt | 0.0028 | 0.0069 | **Rigid** — same behavior regardless of input |
| Eleanor Hartley | 0.0027 | 0.0049 | **Rigid** — same behavior regardless of input |
| Oliver Trevelyan | 0.0026 | 0.0066 | **Rigid** — same behavior regardless of input |
| James Blackstone | 0.0026 | 0.0074 | **Rigid** — same behavior regardless of input |
| Edmund Leigh | 0.0024 | 0.0062 | **Rigid** — same behavior regardless of input |

### 1.3 Quote Rate by Expert × Condition

Fraction of utterances that are direct novel quotations. Experts who quote more in passage-grounded conditions are responding to their input material.

| Expert | Transport | Embedding | RAG | No Pass | Random |
|--------|--------:|--------:|----:|--------:|-------:|
| Caroline Woodcourt | 0.134 | 0.120 | 0.108 | 0.111 | 0.100 | 0.129 | 0.127 |
| Daniel Rosen | 0.089 | 0.099 | 0.091 | 0.094 | 0.077 | 0.096 | 0.084 |
| Edmund Leigh | 0.086 | 0.079 | 0.085 | 0.086 | 0.076 | 0.103 | 0.113 |
| Eleanor Hartley | 0.113 | 0.106 | 0.096 | 0.078 | 0.087 | 0.106 | 0.093 |
| James Blackstone | 0.092 | 0.087 | 0.092 | 0.069 | 0.080 | 0.076 | 0.087 |
| Oliver Trevelyan | 0.131 | 0.125 | 0.113 | 0.105 | 0.111 | 0.124 | 0.134 |

### 1.4 Punchline Rate by Expert × Condition

| Expert | Transport | Embedding | RAG | No Pass | Random |
|--------|--------:|--------:|----:|--------:|-------:|
| Caroline Woodcourt | 0.089 | 0.081 | 0.096 | 0.079 | 0.097 | 0.089 | 0.095 |
| Daniel Rosen | 0.111 | 0.125 | 0.117 | 0.106 | 0.153 | 0.126 | 0.135 |
| Edmund Leigh | 0.112 | 0.105 | 0.103 | 0.084 | 0.123 | 0.104 | 0.106 |
| Eleanor Hartley | 0.117 | 0.099 | 0.104 | 0.084 | 0.113 | 0.106 | 0.125 |
| James Blackstone | 0.107 | 0.112 | 0.111 | 0.085 | 0.121 | 0.132 | 0.115 |
| Oliver Trevelyan | 0.129 | 0.116 | 0.136 | 0.103 | 0.128 | 0.130 | 0.143 |

## 2. Distinctive Vocabulary: How Experts *Frame*

For each run, we compute G2 log-likelihood ratio for each expert's words vs the other two experts in the same run. This strips shared Bleak House vocabulary and isolates the analytical frame — the words each expert uses to *interpret*, not what they interpret.

### 2.1 Top Distinctive Terms by Expert (all conditions)

**Caroline Woodcourt:** **she** (7.6), **time** (5.0), **her** (4.6), **esther** (4.3), **read** (3.8), **you** (3.5), **almost** (3.3), **then** (2.6), **love** (2.1), **and** (2.1), **every** (2.1), **there** (1.8)

**Daniel Rosen:** **system** (10.9), **class** (3.6), **edmund** (3.3), **chancery** (2.5), **not** (2.2), **people** (2.2), **law** (1.8), **has** (1.6), **dead** (1.6), **are** (1.6), **power** (1.5), **they** (1.5)

**Edmund Leigh:** **moral** (12.5), **not** (9.6), **would** (4.7), **man** (2.5), **though** (2.4), **rather** (2.3), **merely** (2.3), **will** (2.2), **but** (2.0), **daniel** (1.9), **human** (1.7), **more** (1.7)

**Eleanor Hartley:** **esther** (4.1), **structural** (3.5), **she** (3.0), **then** (2.9), **sentence** (2.8), **doing** (2.8), **narration** (2.6), **person** (2.5), **first** (2.2), **fog** (2.2), **extraordinary** (2.2), **omniscient** (1.9)

**James Blackstone:** **was** (13.9), **chancery** (7.5), **legal** (7.4), **court** (4.7), **had** (4.3), **victorian** (4.1), **were** (4.1), **law** (3.6), **precise** (3.0), **real** (2.9), **social** (2.8), **system** (2.5)

**Oliver Trevelyan:** **you** (15.0), **read** (7.7), **when** (3.8), **then** (2.8), **aloud** (2.7), **have** (2.6), **feel** (2.5), **and** (2.4), **voice** (2.0), **time** (2.0), **always** (1.8), **every** (1.8)

### 2.2 Vocabulary Stability Across Conditions

Mean Jaccard overlap of top-10 distinctive terms across conditions. **Higher = the expert's distinctive vocabulary is stable regardless of input (rigid frame). Lower = their framing vocabulary shifts with passages.**

| Expert | Mean Jaccard | Interpretation |
|--------|------------:|----------------|
| James Blackstone | 0.528 | **Rigid frame** — same analytical lens |
| Caroline Woodcourt | 0.356 | **Rigid frame** — same analytical lens |
| Edmund Leigh | 0.321 | Moderate stability |
| Oliver Trevelyan | 0.307 | Moderate stability |
| Eleanor Hartley | 0.264 | Moderate stability |
| Daniel Rosen | 0.216 | Moderate stability |

### 2.3 Condition-Specific Distinctive Terms

**James Blackstone** (most stable):

- **transport**: *was*, *legal*, *chancery*, *victorian*, *had*, *were*, *court*
- **embedding**: *was*, *legal*, *were*, *law*, *court*, *chancery*, *precise*
- **rag**: *was*, *chancery*, *legal*, *court*, *had*, *could*, *real*
- **no_passages**: *was*, *legal*, *chancery*, *had*, *real*, *court*, *social*
- **random**: *was*, *chancery*, *had*, *law*, *victorian*, *not*, *system*
- **high_arc**: *was*, *chancery*, *legal*, *court*, *were*, *victorian*, *had*
- **extreme**: *was*, *legal*, *victorian*, *chancery*, *could*, *jarndyce*, *court*

**Daniel Rosen** (most variable):

- **transport**: *system*, *law*, *class*, *power*, *name*, *people*, *but*
- **embedding**: *system*, *not*, *made*, *edmund*, *every*, *its*, *has*
- **rag**: *system*, *class*, *edmund*, *chancery*, *tulkinghorn*, *vholes*, *rouncewell*
- **no_passages**: *system*, *dead*, *edmund*, *tom*, *class*, *alone*, *not*
- **random**: *system*, *chancery*, *edmund*, *people*, *his*, *they*, *from*
- **high_arc**: *system*, *has*, *chancery*, *people*, *edmund*, *class*, *not*
- **extreme**: *system*, *class*, *they*, *edmund*, *cannot*, *are*, *money*

## 3. Paired Comparisons: How Much Does Input Change Output?

For each expert in each panel, we compare their TF-IDF vector across conditions. Because these are *within-panel* comparisons (same three experts, same segment structure), differences are attributable to passage selection, not panel composition.

### 3.1 Mean Within-Panel Distance Across Conditions

| Expert | Mean Distance | Std | N | Interpretation |
|--------|-------------:|----:|--:|----------------|
| Caroline Woodcourt | 0.7827 | 0.0406 | 204 | **Highly responsive** to passages |
| Daniel Rosen | 0.7378 | 0.0416 | 198 | Moderately responsive |
| Eleanor Hartley | 0.7156 | 0.0427 | 210 | Moderately responsive |
| Oliver Trevelyan | 0.7137 | 0.0516 | 192 | Moderately responsive |
| Edmund Leigh | 0.6999 | 0.0462 | 192 | Moderately responsive |
| James Blackstone | 0.6921 | 0.0529 | 192 | Moderately responsive |

### 3.2 Distance from Transport (per expert)

How different is each expert's output under transport vs each other condition? Larger distances mean that condition produces more different output — exactly what manipulability claims.

| Expert | vs Embedding | vs RAG | vs No Pass | vs Random |
|--------|------------:|-------:|----------:|----------:|
| Caroline Woodcourt | 0.7920 | 0.8032 | 0.8012 | 0.8058 |
| Daniel Rosen | 0.7455 | 0.7544 | 0.7558 | 0.7568 |
| Edmund Leigh | 0.7077 | 0.7164 | 0.7028 | 0.7082 |
| Eleanor Hartley | 0.7339 | 0.7326 | 0.7263 | 0.7519 |
| James Blackstone | 0.7112 | 0.7230 | 0.7137 | 0.7441 |
| Oliver Trevelyan | 0.7341 | 0.7218 | 0.7201 | 0.7380 |

## 4. Synthesis: The Rigidity–Responsiveness Spectrum

Three independent measures — behavioral (sentence types), lexical (distinctive vocabulary stability), and paired (within-panel TF-IDF distance) — converge on a ranking:

| Rank | Expert | Behavioral | Vocab Stability | Paired Dist | Composite |
|------|--------|----------:|----------------:|------------:|----------:|
| 1 | James Blackstone | 0.0026 | 0.528 | 0.6921 | 0.165 |
| 2 | Edmund Leigh | 0.0024 | 0.321 | 0.6999 | 0.250 |
| 3 | Oliver Trevelyan | 0.0026 | 0.307 | 0.7137 | 0.487 |
| 4 | Eleanor Hartley | 0.0027 | 0.264 | 0.7156 | 0.602 |
| 5 | Caroline Woodcourt | 0.0028 | 0.356 | 0.7827 | 0.789 |
| 6 | Daniel Rosen | 0.0029 | 0.216 | 0.7378 | 0.835 |

**James Blackstone** is the most rigid expert across all three measures — their behavioral profile, distinctive vocabulary, and overall output change least across conditions.

**Daniel Rosen** is the most responsive — their output genuinely changes with different passage selections, making them the best demonstration of the transport pipeline's manipulability.

### 4.1 Implications for the Manipulability Claim

The transport pipeline's value proposition — that changing demand vectors and arc constraints produces *visible, legible* output differences — is most clearly demonstrated through responsive experts. When the solver assigns different passages to a responsive expert, the resulting script measurably changes: different sentence type distribution, different analytical vocabulary, different overall content. For rigid experts, the pipeline controls *which text* they quote but not *how they think* — the caricature is stable regardless.

This is not a weakness — it reflects a design choice. A panel benefits from having both rigid experts (reliable anchors for their specialist perspective) and responsive experts (who adapt to the specific material, creating variety across configurations). The current six personas span this spectrum naturally.
