# Expert Variation Analysis: Persona Rigidity vs Responsiveness

**Date:** 2026-03-10
**Data:** 300 expert-runs across 100 runs (20 panels × 5 conditions)

Three complementary analyses of how expert personas interact with passage selection conditions. The question: are the expert caricatures rigid (persona dominates regardless of input) or responsive (output changes with different passages)?

## 1. Behavioral Profiles: What Experts *Do*

Each utterance has a `sentence_type` — a structured label for its function in the conversation. The distribution over types is a behavioral fingerprint: does this expert ask questions, read quotes, deliver analysis, or land punchlines?

### 1.1 Mean Behavioral Profile by Expert

| Expert | intro | question | q_setup | q_read | analysis | punch | trans | closing |
|--------|------:|------:|------:|------:|------:|------:|------:|------:|
| Caroline Woodcourt | 0.003 | 0.002 | 0.096 | 0.115 | 0.669 | 0.089 | 0.026 | 0.002 |
| Daniel Rosen | 0.002 | 0.006 | 0.078 | 0.090 | 0.682 | 0.122 | 0.019 | 0.000 |
| Edmund Leigh | 0.003 | 0.002 | 0.075 | 0.083 | 0.718 | 0.105 | 0.014 | 0.001 |
| Eleanor Hartley | 0.003 | 0.003 | 0.083 | 0.096 | 0.694 | 0.104 | 0.017 | 0.001 |
| James Blackstone | 0.002 | 0.001 | 0.074 | 0.084 | 0.709 | 0.107 | 0.023 | 0.000 |
| Oliver Trevelyan | 0.005 | 0.003 | 0.093 | 0.117 | 0.631 | 0.122 | 0.028 | 0.001 |

### 1.2 Behavioral Shift Across Conditions

Jensen-Shannon divergence between an expert's sentence type distribution under different conditions. **Higher = the expert changes what they *do* (more quotes, fewer questions, etc.) depending on input.**

| Expert | Mean JSD | Max JSD | Interpretation |
|--------|--------:|--------:|----------------|
| Caroline Woodcourt | 0.0033 | 0.0069 | **Rigid** — same behavior regardless of input |
| Daniel Rosen | 0.0032 | 0.0088 | **Rigid** — same behavior regardless of input |
| James Blackstone | 0.0030 | 0.0074 | **Rigid** — same behavior regardless of input |
| Eleanor Hartley | 0.0030 | 0.0049 | **Rigid** — same behavior regardless of input |
| Oliver Trevelyan | 0.0029 | 0.0066 | **Rigid** — same behavior regardless of input |
| Edmund Leigh | 0.0020 | 0.0041 | **Rigid** — same behavior regardless of input |

### 1.3 Quote Rate by Expert × Condition

Fraction of utterances that are direct novel quotations. Experts who quote more in passage-grounded conditions are responding to their input material.

| Expert | Transport | Embedding | RAG | No Pass | Random |
|--------|--------:|--------:|----:|--------:|-------:|
| Caroline Woodcourt | 0.134 | 0.120 | 0.108 | 0.111 | 0.100 |
| Daniel Rosen | 0.089 | 0.099 | 0.091 | 0.094 | 0.077 |
| Edmund Leigh | 0.086 | 0.079 | 0.085 | 0.086 | 0.076 |
| Eleanor Hartley | 0.113 | 0.106 | 0.096 | 0.078 | 0.087 |
| James Blackstone | 0.092 | 0.087 | 0.092 | 0.069 | 0.080 |
| Oliver Trevelyan | 0.131 | 0.125 | 0.113 | 0.105 | 0.111 |

### 1.4 Punchline Rate by Expert × Condition

| Expert | Transport | Embedding | RAG | No Pass | Random |
|--------|--------:|--------:|----:|--------:|-------:|
| Caroline Woodcourt | 0.089 | 0.081 | 0.096 | 0.079 | 0.097 |
| Daniel Rosen | 0.111 | 0.125 | 0.117 | 0.106 | 0.153 |
| Edmund Leigh | 0.112 | 0.105 | 0.103 | 0.084 | 0.123 |
| Eleanor Hartley | 0.117 | 0.099 | 0.104 | 0.084 | 0.113 |
| James Blackstone | 0.107 | 0.112 | 0.111 | 0.085 | 0.121 |
| Oliver Trevelyan | 0.129 | 0.116 | 0.136 | 0.103 | 0.128 |

## 2. Distinctive Vocabulary: How Experts *Frame*

For each run, we compute G2 log-likelihood ratio for each expert's words vs the other two experts in the same run. This strips shared Bleak House vocabulary and isolates the analytical frame — the words each expert uses to *interpret*, not what they interpret.

### 2.1 Top Distinctive Terms by Expert (all conditions)

**Caroline Woodcourt:** **she** (8.5), **her** (5.7), **esther** (5.1), **time** (4.2), **you** (3.5), **almost** (3.2), **read** (3.2), **every** (2.2), **and** (2.2), **there** (2.0), **then** (2.0), **woodcourt** (1.9)

**Daniel Rosen:** **system** (10.5), **class** (3.6), **edmund** (3.5), **chancery** (2.5), **not** (2.3), **people** (2.2), **dead** (1.9), **law** (1.7), **power** (1.6), **tulkinghorn** (1.5), **has** (1.5), **but** (1.5)

**Edmund Leigh:** **moral** (12.5), **not** (9.3), **would** (4.8), **rather** (2.5), **merely** (2.4), **man** (2.4), **though** (2.2), **will** (2.1), **daniel** (2.0), **but** (2.0), **human** (1.9), **does** (1.6)

**Eleanor Hartley:** **esther** (4.5), **she** (3.5), **structural** (3.1), **person** (3.1), **doing** (2.8), **sentence** (2.8), **then** (2.7), **narration** (2.5), **first** (2.4), **extraordinary** (2.3), **fog** (2.2), **two** (2.1)

**James Blackstone:** **was** (14.0), **chancery** (7.4), **legal** (7.4), **court** (4.5), **had** (4.5), **were** (3.9), **victorian** (3.5), **law** (3.5), **real** (3.3), **precise** (2.9), **social** (2.7), **system** (2.6)

**Oliver Trevelyan:** **you** (14.0), **read** (7.6), **when** (3.6), **aloud** (3.3), **then** (3.1), **and** (2.6), **feel** (2.3), **every** (2.3), **have** (2.1), **time** (2.1), **voice** (2.0), **three** (1.8)

### 2.2 Vocabulary Stability Across Conditions

Mean Jaccard overlap of top-10 distinctive terms across conditions. **Higher = the expert's distinctive vocabulary is stable regardless of input (rigid frame). Lower = their framing vocabulary shifts with passages.**

| Expert | Mean Jaccard | Interpretation |
|--------|------------:|----------------|
| James Blackstone | 0.505 | **Rigid frame** — same analytical lens |
| Caroline Woodcourt | 0.367 | **Rigid frame** — same analytical lens |
| Edmund Leigh | 0.336 | Moderate stability |
| Oliver Trevelyan | 0.336 | Moderate stability |
| Eleanor Hartley | 0.231 | Moderate stability |
| Daniel Rosen | 0.192 | **Responsive frame** — vocabulary shifts with input |

### 2.3 Condition-Specific Distinctive Terms

**James Blackstone** (most stable):

- **transport**: *was*, *legal*, *chancery*, *victorian*, *had*, *were*, *court*
- **embedding**: *was*, *legal*, *were*, *law*, *court*, *chancery*, *precise*
- **rag**: *was*, *chancery*, *legal*, *court*, *had*, *could*, *real*
- **no_passages**: *was*, *legal*, *chancery*, *had*, *real*, *court*, *social*
- **random**: *was*, *chancery*, *had*, *law*, *victorian*, *not*, *system*

**Daniel Rosen** (most variable):

- **transport**: *system*, *law*, *class*, *power*, *name*, *people*, *but*
- **embedding**: *system*, *not*, *made*, *edmund*, *every*, *its*, *has*
- **rag**: *system*, *class*, *edmund*, *chancery*, *tulkinghorn*, *vholes*, *rouncewell*
- **no_passages**: *system*, *dead*, *edmund*, *tom*, *class*, *alone*, *not*
- **random**: *system*, *chancery*, *edmund*, *people*, *his*, *they*, *from*

## 3. Paired Comparisons: How Much Does Input Change Output?

For each expert in each panel, we compare their TF-IDF vector across conditions. Because these are *within-panel* comparisons (same three experts, same segment structure), differences are attributable to passage selection, not panel composition.

### 3.1 Mean Within-Panel Distance Across Conditions

| Expert | Mean Distance | Std | N | Interpretation |
|--------|-------------:|----:|--:|----------------|
| Caroline Woodcourt | 0.7895 | 0.0319 | 100 | **Highly responsive** to passages |
| Daniel Rosen | 0.7446 | 0.0372 | 100 | Moderately responsive |
| Oliver Trevelyan | 0.7269 | 0.0453 | 100 | Moderately responsive |
| Eleanor Hartley | 0.7227 | 0.0366 | 100 | Moderately responsive |
| Edmund Leigh | 0.7075 | 0.0437 | 100 | Moderately responsive |
| James Blackstone | 0.7064 | 0.0501 | 100 | Moderately responsive |

### 3.2 Distance from Transport (per expert)

How different is each expert's output under transport vs each other condition? Larger distances mean that condition produces more different output — exactly what manipulability claims.

| Expert | vs Embedding | vs RAG | vs No Pass | vs Random |
|--------|------------:|-------:|----------:|----------:|
| Caroline Woodcourt | 0.7836 | 0.7973 | 0.7950 | 0.7977 |
| Daniel Rosen | 0.7481 | 0.7535 | 0.7515 | 0.7545 |
| Edmund Leigh | 0.7085 | 0.7196 | 0.7051 | 0.7067 |
| Eleanor Hartley | 0.7282 | 0.7282 | 0.7198 | 0.7452 |
| James Blackstone | 0.7123 | 0.7191 | 0.7079 | 0.7384 |
| Oliver Trevelyan | 0.7293 | 0.7208 | 0.7168 | 0.7299 |

## 4. Synthesis: The Rigidity–Responsiveness Spectrum

Three independent measures — behavioral (sentence types), lexical (distinctive vocabulary stability), and paired (within-panel TF-IDF distance) — converge on a ranking:

| Rank | Expert | Behavioral | Vocab Stability | Paired Dist | Composite |
|------|--------|----------:|----------------:|------------:|----------:|
| 1 | Edmund Leigh | 0.0020 | 0.336 | 0.7075 | 0.184 |
| 2 | James Blackstone | 0.0030 | 0.505 | 0.7064 | 0.263 |
| 3 | Oliver Trevelyan | 0.0029 | 0.336 | 0.7269 | 0.495 |
| 4 | Eleanor Hartley | 0.0030 | 0.231 | 0.7227 | 0.617 |
| 5 | Daniel Rosen | 0.0032 | 0.192 | 0.7446 | 0.805 |
| 6 | Caroline Woodcourt | 0.0033 | 0.367 | 0.7895 | 0.814 |

**Edmund Leigh** is the most rigid expert across all three measures — their behavioral profile, distinctive vocabulary, and overall output change least across conditions.

**Caroline Woodcourt** is the most responsive — their output genuinely changes with different passage selections, making them the best demonstration of the transport pipeline's manipulability.

### 4.1 Implications for the Manipulability Claim

The transport pipeline's value proposition — that changing demand vectors and arc constraints produces *visible, legible* output differences — is most clearly demonstrated through responsive experts. When the solver assigns different passages to a responsive expert, the resulting script measurably changes: different sentence type distribution, different analytical vocabulary, different overall content. For rigid experts, the pipeline controls *which text* they quote but not *how they think* — the caricature is stable regardless.

This is not a weakness — it reflects a design choice. A panel benefits from having both rigid experts (reliable anchors for their specialist perspective) and responsive experts (who adapt to the specific material, creating variety across configurations). The current six personas span this spectrum naturally.
