# Expert Clustering Analysis: Persona Rigidity vs Responsiveness

**Date:** 2026-03-10
**Utterances analysed:** 5,888 turns across 20 panels × 5 conditions

## 1. Overview

Each expert persona is a deliberate caricature — the Marxist always finds class struggle, the legal historian always finds institutional failure. But how *rigid* are these caricatures? Does passage selection change what an expert talks about, or does the persona dominate regardless of input?

We cluster all expert utterances (turns) using TF-IDF vectors and measure how tightly each expert's utterances group together (rigidity) vs how much they spread across conditions (responsiveness). An expert with a strong, rigid agenda will cluster tightly regardless of condition; a responsive expert will shift vocabulary depending on what passages they receive.

### 1.1 Utterance Counts

| Expert | Transport | Embedding | Rag | No Passages | Random | Total |
|--------|------:|------:|------:|------:|------:|------:|
| Eleanor Hartley | 201 | 233 | 195 | 214 | 198 | 1041 |
| James Blackstone | 191 | 189 | 184 | 187 | 176 | 927 |
| Caroline Woodcourt | 175 | 217 | 180 | 193 | 175 | 940 |
| Edmund Leigh | 202 | 199 | 206 | 203 | 193 | 1003 |
| Daniel Rosen | 189 | 211 | 187 | 202 | 184 | 973 |
| Oliver Trevelyan | 205 | 215 | 195 | 215 | 174 | 1004 |

## 2. Persona Rigidity: Intra-Expert Distances

Mean pairwise cosine distance between all utterances by the same expert, across all conditions and panels. **Lower distance = tighter cluster = more rigid persona.** Higher distance = more varied vocabulary = more responsive to input material.

| Expert | Mean Distance | Std Dev | N Utterances | Interpretation |
|--------|-------------:|--------:|------------:|----------------|
| Edmund Leigh | 0.9669 | 0.0332 | 1003 | **Responsive** — spread out |
| James Blackstone | 0.9677 | 0.0361 | 927 | **Responsive** — spread out |
| Eleanor Hartley | 0.9687 | 0.0366 | 1041 | **Responsive** — spread out |
| Daniel Rosen | 0.9690 | 0.0349 | 973 | **Responsive** — spread out |
| Oliver Trevelyan | 0.9701 | 0.0337 | 1004 | **Responsive** — spread out |
| Caroline Woodcourt | 0.9704 | 0.0347 | 940 | **Responsive** — spread out |

**Edmund Leigh** is the most rigid expert — their utterances are the most self-similar regardless of condition. **Caroline Woodcourt** is the most responsive — their vocabulary shifts most depending on input material.

## 3. Condition Responsiveness: How Much Do Centroids Shift?

For each expert, we compute a centroid (mean TF-IDF vector) per condition, then measure the mean pairwise cosine distance between those centroids. **Higher shift = the expert's vocabulary changes more across conditions.**

| Expert | Mean Centroid Shift | Max Shift | Interpretation |
|--------|-------------------:|----------:|----------------|
| Caroline Woodcourt | 0.2935 | 0.3450 | **Agenda-driven** — stable across conditions |
| Daniel Rosen | 0.2689 | 0.3076 | **Agenda-driven** — stable across conditions |
| Oliver Trevelyan | 0.2676 | 0.3260 | **Agenda-driven** — stable across conditions |
| Eleanor Hartley | 0.2672 | 0.3209 | **Agenda-driven** — stable across conditions |
| James Blackstone | 0.2531 | 0.2848 | **Agenda-driven** — stable across conditions |
| Edmund Leigh | 0.2199 | 0.2911 | **Agenda-driven** — stable across conditions |

### 3.1 Pairwise Centroid Distances (selected experts)

**Caroline Woodcourt** (most responsive):

| Condition Pair | Distance |
|---------------|--------:|
| embedding ↔ random | 0.3450 |
| embedding ↔ rag | 0.3314 |
| rag ↔ transport | 0.3132 |
| no_passages ↔ rag | 0.3020 |
| embedding ↔ transport | 0.3014 |
| random ↔ transport | 0.2747 |
| embedding ↔ no_passages | 0.2700 |
| no_passages ↔ transport | 0.2697 |
| rag ↔ random | 0.2674 |
| no_passages ↔ random | 0.2602 |

**Edmund Leigh** (least responsive):

| Condition Pair | Distance |
|---------------|--------:|
| embedding ↔ rag | 0.2911 |
| rag ↔ transport | 0.2642 |
| no_passages ↔ rag | 0.2516 |
| embedding ↔ random | 0.2338 |
| rag ↔ random | 0.2189 |
| embedding ↔ transport | 0.2010 |
| no_passages ↔ transport | 0.1904 |
| embedding ↔ no_passages | 0.1903 |
| random ↔ transport | 0.1835 |
| no_passages ↔ random | 0.1741 |

## 4. Global Clustering Metrics

| Metric | Value | Interpretation |
|--------|------:|----------------|
| Silhouette (expert labels) | 0.0025 | Weak expert separation in TF-IDF space |
| Silhouette (condition labels) | 0.0008 | Weak condition separation |
| ARI (K-means vs expert) | 0.0053 | Expert identity is a weak clustering signal |
| ARI (K-means vs condition) | 0.0110 | Condition is a weak clustering signal |

The ARI ratio (expert/condition = 0.5×) suggests condition influences clustering as much or more than expert identity.

## 5. Inter-Expert Similarity

Mean cosine similarity between utterances of each expert pair. Higher values mean experts use more overlapping vocabulary.

| | Caroline | Daniel | Edmund | Eleanor | James | Oliver |
|---|---:|---:|---:|---:|---:|---:|
| **Caroline** | **0.031** | 0.024 | 0.024 | 0.026 | 0.022 | 0.027 |
| **Daniel** | 0.024 | **0.032** | 0.026 | 0.025 | 0.027 | 0.023 |
| **Edmund** | 0.024 | 0.026 | **0.034** | 0.024 | 0.024 | 0.023 |
| **Eleanor** | 0.026 | 0.025 | 0.024 | **0.032** | 0.023 | 0.025 |
| **James** | 0.022 | 0.027 | 0.024 | 0.023 | **0.033** | 0.022 |
| **Oliver** | 0.027 | 0.023 | 0.023 | 0.025 | 0.022 | **0.031** |

Most similar pair: **Daniel–James** (0.027). Least similar: **James–Oliver** (0.022).

## 6. Expert Vocabulary Signatures

Top 15 TF-IDF terms per expert (aggregated across all conditions). These are the words most distinctive to each expert's overall output.

**Caroline Woodcourt:** *esther* (0.045), *richard* (0.031), *time* (0.028), *jo* (0.024), *read* (0.022), *novel* (0.022), *lady* (0.021), *says* (0.020), *doesn* (0.020), *passage* (0.020)

**Daniel Rosen:** *richard* (0.034), *jo* (0.033), *novel* (0.030), *chancery* (0.026), *jarndyce* (0.025), *class* (0.025), *doesn* (0.023), *fog* (0.022), *dedlock* (0.022), *want* (0.020)

**Edmund Leigh:** *moral* (0.047), *richard* (0.036), *think* (0.029), *novel* (0.029), *man* (0.028), *jarndyce* (0.027), *esther* (0.026), *character* (0.024), *does* (0.024), *merely* (0.021)

**Eleanor Hartley:** *esther* (0.043), *novel* (0.028), *narrator* (0.027), *fog* (0.024), *richard* (0.024), *jo* (0.024), *structural* (0.023), *narration* (0.021), *doing* (0.021), *person* (0.020)

**James Blackstone:** *chancery* (0.042), *legal* (0.033), *jarndyce* (0.031), *court* (0.026), *victorian* (0.023), *richard* (0.023), *law* (0.023), *real* (0.022), *jo* (0.022), *novel* (0.020)

**Oliver Trevelyan:** *read* (0.033), *aloud* (0.031), *richard* (0.025), *jo* (0.021), *man* (0.021), *like* (0.021), *esther* (0.020), *ve* (0.020), *novel* (0.019), *time* (0.019)

## 7. Condition-Responsive Vocabulary

Terms with highest variance across conditions for each expert. These are the words whose usage shifts most depending on what passages the expert receives — indicators of responsiveness.

### Caroline Woodcourt

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| esther | 0.00020 | 0.0437 | 0.0195 | 0.0561 | 0.0586 | 0.0530 |
| woodcourt | 0.00019 | 0.0111 | 0.0053 | 0.0418 | 0.0065 | 0.0097 |
| jo | 0.00018 | 0.0273 | 0.0335 | 0.0096 | 0.0406 | 0.0064 |
| smallweed | 0.00009 | 0.0000 | 0.0000 | 0.0000 | 0.0014 | 0.0245 |
| dead | 0.00009 | 0.0059 | 0.0143 | 0.0037 | 0.0286 | 0.0039 |
| mrs woodcourt | 0.00008 | 0.0041 | 0.0000 | 0.0230 | 0.0000 | 0.0017 |
| george | 0.00007 | 0.0008 | 0.0000 | 0.0033 | 0.0004 | 0.0222 |

### Daniel Rosen

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| dead | 0.00025 | 0.0042 | 0.0052 | 0.0028 | 0.0433 | 0.0018 |
| jo | 0.00018 | 0.0322 | 0.0447 | 0.0130 | 0.0489 | 0.0233 |
| vholes | 0.00011 | 0.0000 | 0.0099 | 0.0293 | 0.0204 | 0.0064 |
| fog | 0.00010 | 0.0222 | 0.0185 | 0.0080 | 0.0393 | 0.0214 |
| reverends | 0.00010 | 0.0000 | 0.0000 | 0.0000 | 0.0246 | 0.0000 |
| george | 0.00009 | 0.0027 | 0.0000 | 0.0026 | 0.0027 | 0.0254 |
| tom | 0.00008 | 0.0000 | 0.0013 | 0.0005 | 0.0243 | 0.0070 |

### Edmund Leigh

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| leicester | 0.00033 | 0.0070 | 0.0029 | 0.0518 | 0.0074 | 0.0103 |
| sir leicester | 0.00023 | 0.0065 | 0.0030 | 0.0445 | 0.0075 | 0.0105 |
| sir | 0.00022 | 0.0067 | 0.0029 | 0.0434 | 0.0076 | 0.0122 |
| jo | 0.00008 | 0.0205 | 0.0229 | 0.0051 | 0.0268 | 0.0074 |
| skimpole | 0.00007 | 0.0063 | 0.0058 | 0.0285 | 0.0110 | 0.0099 |
| jarndyce | 0.00007 | 0.0253 | 0.0118 | 0.0310 | 0.0358 | 0.0307 |
| tulkinghorn | 0.00005 | 0.0250 | 0.0097 | 0.0179 | 0.0059 | 0.0065 |

### Eleanor Hartley

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| jo | 0.00018 | 0.0267 | 0.0354 | 0.0040 | 0.0380 | 0.0106 |
| esther | 0.00018 | 0.0369 | 0.0223 | 0.0503 | 0.0613 | 0.0490 |
| person | 0.00013 | 0.0163 | 0.0109 | 0.0103 | 0.0412 | 0.0221 |
| fog | 0.00012 | 0.0197 | 0.0233 | 0.0147 | 0.0451 | 0.0163 |
| house | 0.00012 | 0.0028 | 0.0084 | 0.0348 | 0.0112 | 0.0129 |
| person narrator | 0.00010 | 0.0018 | 0.0008 | 0.0016 | 0.0276 | 0.0106 |
| bleak house | 0.00006 | 0.0026 | 0.0037 | 0.0251 | 0.0112 | 0.0110 |

### James Blackstone

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| jo | 0.00014 | 0.0224 | 0.0308 | 0.0045 | 0.0365 | 0.0126 |
| chancery | 0.00013 | 0.0357 | 0.0344 | 0.0634 | 0.0457 | 0.0326 |
| george | 0.00010 | 0.0005 | 0.0006 | 0.0023 | 0.0027 | 0.0269 |
| jennens | 0.00008 | 0.0000 | 0.0115 | 0.0030 | 0.0242 | 0.0016 |
| fog | 0.00008 | 0.0183 | 0.0182 | 0.0058 | 0.0307 | 0.0086 |
| court | 0.00006 | 0.0229 | 0.0235 | 0.0383 | 0.0315 | 0.0155 |
| vholes | 0.00006 | 0.0000 | 0.0053 | 0.0183 | 0.0193 | 0.0047 |

### Oliver Trevelyan

| Term | Variance | Transport | Embedding | RAG | No Pass | Random |
|------|--------:|----------:|----------:|----:|--------:|-------:|
| skimpole | 0.00021 | 0.0078 | 0.0041 | 0.0431 | 0.0050 | 0.0130 |
| fog | 0.00013 | 0.0126 | 0.0120 | 0.0067 | 0.0393 | 0.0134 |
| jo | 0.00011 | 0.0221 | 0.0328 | 0.0132 | 0.0303 | 0.0046 |
| dead | 0.00007 | 0.0089 | 0.0128 | 0.0021 | 0.0254 | 0.0024 |
| george | 0.00007 | 0.0009 | 0.0000 | 0.0047 | 0.0010 | 0.0226 |
| chambers | 0.00006 | 0.0007 | 0.0000 | 0.0195 | 0.0020 | 0.0000 |
| bucket | 0.00005 | 0.0133 | 0.0029 | 0.0062 | 0.0114 | 0.0238 |

## 8. Run-Level Analysis (Aggregated Documents)

The turn-level analysis above treats each speaker turn (~2–5 sentences) as a document. This is noisy: individual turns are short and topically constrained by segment context. Here we aggregate all of an expert's utterances within a single run into one document, producing one TF-IDF vector per expert per run (300 documents, matrix shape 300×3000).

### 8.1 Global Clustering Metrics (Run-Level)

| Metric | Turn-Level | Run-Level | Change |
|--------|----------:|----------:|--------|
| Silhouette (expert) | 0.0025 | 0.0717 | Stronger |
| Silhouette (condition) | 0.0008 | 0.0642 | Stronger |
| ARI (expert) | 0.0053 | 0.3451 | Stronger |
| ARI (condition) | 0.0110 | 0.2812 | Stronger |

Run-level ARI ratio (expert/condition): **1.2×**

### 8.2 Intra-Expert Distances (Run-Level)

| Expert | Mean Distance | N Docs | Interpretation |
|--------|-------------:|-------:|----------------|
| James Blackstone | 0.7024 | 50 | **Responsive** — spread out |
| Eleanor Hartley | 0.7115 | 50 | **Responsive** — spread out |
| Oliver Trevelyan | 0.7155 | 50 | **Responsive** — spread out |
| Edmund Leigh | 0.7251 | 50 | **Responsive** — spread out |
| Daniel Rosen | 0.7423 | 50 | **Responsive** — spread out |
| Caroline Woodcourt | 0.7694 | 50 | **Responsive** — spread out |

### 8.3 Condition Responsiveness (Run-Level)

| Expert | Mean Centroid Shift | Max Shift |
|--------|-------------------:|----------:|
| Caroline Woodcourt | 0.4635 | 0.5145 |
| Daniel Rosen | 0.4191 | 0.4760 |
| Eleanor Hartley | 0.3893 | 0.4382 |
| Oliver Trevelyan | 0.3828 | 0.4575 |
| James Blackstone | 0.3472 | 0.3933 |
| Edmund Leigh | 0.3399 | 0.4307 |

**Caroline Woodcourt** (most responsive, run-level):

| Condition Pair | Distance |
|---------------|--------:|
| no_passages ↔ rag | 0.5145 |
| rag ↔ transport | 0.5099 |
| embedding ↔ random | 0.5093 |
| embedding ↔ rag | 0.4770 |
| embedding ↔ transport | 0.4517 |
| rag ↔ random | 0.4450 |
| no_passages ↔ transport | 0.4429 |
| embedding ↔ no_passages | 0.4409 |
| random ↔ transport | 0.4392 |
| no_passages ↔ random | 0.4046 |

**Edmund Leigh** (least responsive, run-level):

| Condition Pair | Distance |
|---------------|--------:|
| embedding ↔ rag | 0.4307 |
| rag ↔ transport | 0.4188 |
| no_passages ↔ rag | 0.3917 |
| embedding ↔ random | 0.3427 |
| rag ↔ random | 0.3343 |
| no_passages ↔ transport | 0.3206 |
| embedding ↔ transport | 0.3073 |
| embedding ↔ no_passages | 0.3048 |
| random ↔ transport | 0.2832 |
| no_passages ↔ random | 0.2653 |

## 9. Interpretation

### 9.1 The Rigidity–Responsiveness Spectrum

Using the run-level analysis (Section 8), which provides cleaner signal, the experts fall along a spectrum from agenda-driven to input-responsive:

1. **James Blackstone** — run-level distance 0.7024, centroid shift 0.3472
2. **Eleanor Hartley** — run-level distance 0.7115, centroid shift 0.3893
3. **Oliver Trevelyan** — run-level distance 0.7155, centroid shift 0.3828
4. **Edmund Leigh** — run-level distance 0.7251, centroid shift 0.3399
5. **Daniel Rosen** — run-level distance 0.7423, centroid shift 0.4191
6. **Caroline Woodcourt** — run-level distance 0.7694, centroid shift 0.4635

**Blackstone** (legal historian) is the most rigid: his legal-institutional vocabulary dominates regardless of condition. His top terms — *chancery, legal, jarndyce, court, victorian, law* — are agenda-driven, not passage-driven.

**Woodcourt** (close reader/performer) is the most responsive: her vocabulary shifts substantially depending on what passages she receives. Her centroid shift (0.4635) is 1.4× Leigh's. She adapts to the material — her condition-responsive terms include character names like *woodcourt, smallweed, george* that appear only when the passages feature those characters.

### 9.2 The Expert–Condition Interaction

The run-level ARI ratio (expert/condition = 1.2×) confirms that expert identity is a stronger organising force than condition — but only marginally. Both matter. This is the expected result for a system that uses *both* persona prompts and passage selection: the persona sets the interpretive frame, and the passages provide the material to interpret.

The interesting finding is that these forces interact differently per expert. For Blackstone, persona dominates — he discusses legal institutions regardless of input. For Woodcourt, passages have genuine influence — she discusses what she's given. This means the transport pipeline's manipulability is *more valuable for some experts than others*.

### 9.3 Implications for Pipeline Design

Rigid experts (Blackstone, Leigh) are the most *reliable* caricatures — they sound like themselves regardless of input. But they are also the hardest to *steer* via passage selection: giving Blackstone different passages changes what legal concepts he discusses but not his fundamental legal-institutional framing.

Responsive experts (Woodcourt, Rosen) are more *manipulable* — their output genuinely changes with different input material. This makes them better subjects for exploring the configuration space, since changes to passage selection produce visible changes in their contributions. Notably, Rosen (the Marxist) is the second most responsive: despite his ideological framing, he adapts to specific characters and scenes in the passages he receives, applying his class-analysis lens to whatever material is provided.

The transport pipeline's value proposition is strongest for responsive experts: adjusting demand profiles and arc constraints produces measurably different output from experts who respond to their input. For rigid experts, the pipeline still controls *which text* they quote, but not *how they frame* it.

This spectrum also suggests a design lever: persona descriptions could be calibrated along the rigidity–responsiveness axis. A persona that is *too* rigid wastes the passage selection pipeline's effort; one that is *too* responsive loses its distinctive caricature. The current personas span this range naturally, which produces varied and interesting panel dynamics.
