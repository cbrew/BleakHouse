# Optimal Transport for Legal Document Matching: When Min-Cost Flow Beats Greedy Heuristics

*How we replaced a 4-stage heuristic pipeline with a single optimization that guarantees globally optimal matching and explicit gap detection*

---

## The Matching Problem

After enriching legal documents (see Part 1), we have:
- **Source sentences** with provisions: what each sentence *provides* (facts, legal basis, party info, etc.)
- **Target sentences** with needs: what each ECA report section *requires*

The goal: match sources to targets so that every target's needs are satisfied by sources that provide those dimensions.

Simple, right? Just find the best source for each target.

**Wrong.** That greedy approach fails spectacularly.

---

## Why Greedy Matching Fails

### The Over-Assignment Problem

Consider this scenario:

```
Sources:
  S1: "Contract signed January 15, 2023" → facts:strong, timeline:strong
  S2: "Defendant is a Delaware corporation" → party_info:strong
  S3: "Payment was $50,000" → financials:strong

Targets (all need timeline:strong):
  T1: "When was the agreement executed?"
  T2: "What was the sequence of events?"
  T3: "Establish the timeline of breach"
```

**Greedy result:** S1 matches T1, T2, and T3. It's the best match for each individually!

**Problem:** S1 is used three times. S2 and S3 are ignored. The report cites one sentence repeatedly while other relevant sources gather dust.

### The Coverage Illusion

Greedy matching gives you high confidence scores but poor coverage. You think you've matched everything, but you've really just found the same few "popular" sources over and over.

### Threshold-Based Gap Detection

With greedy matching, gap detection becomes "confidence below threshold = gap." But what threshold? 0.5? 0.7? The choice is arbitrary, and you can't distinguish between:
- "No good sources exist" (real gap)
- "Good sources exist but weren't selected" (algorithm failure)

---

## The Optimal Transport Solution

We reframed matching as a **resource allocation problem**:

- Sources have **supply** (what they can provide)
- Targets have **demand** (what they need)
- Find the minimum-cost way to satisfy all demand

This is a classic **min-cost flow** problem, solvable optimally with network flow algorithms.

### The Key Insight

Each (section, dimension) pair becomes a separate flow problem:

```
For Section III, dimension "facts":
  - Sources: sentences that provide facts for Section III
  - Targets: sentences that need facts in Section III
  - Goal: flow "facts" from sources to targets at minimum cost
```

By solving each (section, dimension) pair independently, we get:
1. **Global optimization**: No source is over-used
2. **Explicit gaps**: Unmet demand is precisely measured
3. **Dimension-aware matching**: Facts flow to fact-needs, timeline to timeline-needs

---

## The 7 Provision Dimensions

We model legal content across 7 dimensions, each representing a type of information:

| Dimension | What Sources Provide | What Targets Need |
|-----------|---------------------|-------------------|
| `facts` | Events, actions, circumstances | Factual foundation for claims |
| `legal_basis` | Statutes, case law, authorities | Legal support for arguments |
| `party_info` | Parties, relationships, roles | Establishing who's involved |
| `timeline` | Dates, sequences, causation | Temporal narrative |
| `financials` | Money, damages, payments | Damages calculation |
| `contractual` | Contract terms, obligations | Breach analysis |
| `admissions` | Acknowledgments, concessions | Undisputed facts |

Each dimension has a **strength**:
- `none` = 0 units
- `weak` = 1 unit
- `strong` = 2 units

A source with `facts:strong` provides 2 units of facts. A target with `facts:strong` demands 2 units.

---

## The Flow Network

For each (section, dimension) pair, we construct a flow network:

```
                        ┌─────────────────────┐
                        │    SUPER_SOURCE     │
                        │   (supplies total   │
                        │      demand)        │
                        └─────────┬───────────┘
                                  │
              ┌───────────────────┼───────────────────┐
              │                   │                   │
              ▼                   ▼                   ▼
        ┌──────────┐        ┌──────────┐        ┌──────────┐
        │ Source 1 │        │ Source 2 │        │ NULL_SRC │
        │ supply=2 │        │ supply=1 │        │ (dummy)  │
        └────┬─────┘        └────┬─────┘        └────┬─────┘
             │                   │                   │
             │    ┌──────────────┼──────────────┐    │
             │    │              │              │    │
             ▼    ▼              ▼              ▼    ▼
        ┌──────────┐        ┌──────────┐        ┌──────────┐
        │ Target 1 │        │ Target 2 │        │ Target 3 │
        │ demand=2 │        │ demand=1 │        │ demand=2 │
        └────┬─────┘        └────┬─────┘        └────┬─────┘
             │                   │                   │
             └───────────────────┼───────────────────┘
                                 │
                        ┌────────▼────────┐
                        │   SUPER_SINK    │
                        │ (receives total │
                        │     demand)     │
                        └─────────────────┘
```

### Node Types

1. **SUPER_SOURCE** (node 0): Supplies total demand to all sources
2. **SUPER_SINK** (node 1): Receives total demand from all targets
3. **NULL_NODE** (node 2): Dummy source for unmatched demand (gap detection!)
4. **Source nodes**: One per source sentence with this dimension
5. **Target nodes**: One per target sentence needing this dimension

### Arc Costs

The cost function encodes our preferences:

```python
class TransportConfig:
    null_cost: int = 100    # Very expensive: unmatched demand
    strong_cost: int = 1    # Cheap: strong provision matches
    weak_cost: int = 2      # More expensive: weak provision matches
```

**Why these values?**

- **Strong matches cost 1**: Preferred—source definitively provides the dimension
- **Weak matches cost 2**: Acceptable but less ideal
- **NULL matches cost 100**: Extremely expensive—only used when no real source exists

The solver minimizes total cost, so it:
1. Prefers strong sources over weak
2. Uses real sources before resorting to NULL
3. Distributes demand across sources (avoids over-assignment)

---

## The Algorithm

```python
def solve_flow(section: str, dimension: str,
               sources: list[SourceNode],
               targets: list[TargetNode],
               config: TransportConfig) -> FlowResult:

    # Filter to relevant nodes
    section_sources = [s for s in sources
                       if section in s.eca_sections
                       and s.provisions[dimension] != "none"]
    section_targets = [t for t in targets
                       if t.eca_section == section
                       and t.needs[dimension] != "none"]

    if not section_targets:
        return FlowResult(section, dimension, demand=0, supplied=0, null_flow=0)

    # Compute supply and demand
    supplies = {s.sid: STRENGTH_TO_UNITS[s.provisions[dimension]]
                for s in section_sources}
    demands = {t.sid: STRENGTH_TO_UNITS[t.needs[dimension]]
               for t in section_targets}

    total_demand = sum(demands.values())

    # Build the flow network
    smcf = pywrapgraph.SimpleMinCostFlow()

    # Add nodes
    SUPER_SOURCE, SUPER_SINK, NULL_NODE = 0, 1, 2
    # ... source and target nodes numbered 3 onwards

    # Add arcs
    # SUPER_SOURCE → each source (capacity = supply, cost = 0)
    for s in section_sources:
        smcf.add_arc(SUPER_SOURCE, source_idx[s.sid], supplies[s.sid], 0)

    # SUPER_SOURCE → NULL (capacity = total_demand, cost = 0)
    smcf.add_arc(SUPER_SOURCE, NULL_NODE, total_demand, 0)

    # Each source → each target (full bipartite)
    for s in section_sources:
        strength = s.provisions[dimension]
        cost = config.strong_cost if strength == "strong" else config.weak_cost
        for t in section_targets:
            smcf.add_arc(source_idx[s.sid], target_idx[t.sid],
                        supplies[s.sid], cost)

    # NULL → each target (capacity = demand, cost = null_cost)
    for t in section_targets:
        smcf.add_arc(NULL_NODE, target_idx[t.sid],
                    demands[t.sid], config.null_cost)

    # Each target → SUPER_SINK (capacity = demand, cost = 0)
    for t in section_targets:
        smcf.add_arc(target_idx[t.sid], SUPER_SINK, demands[t.sid], 0)

    # Set node supplies
    smcf.set_node_supply(SUPER_SOURCE, total_demand)
    smcf.set_node_supply(SUPER_SINK, -total_demand)

    # Solve!
    status = smcf.solve()

    # Extract results
    flows = []
    null_flow = 0
    for arc in range(smcf.num_arcs()):
        flow = smcf.flow(arc)
        if flow > 0:
            tail, head = smcf.tail(arc), smcf.head(arc)
            if tail == NULL_NODE:
                null_flow += flow  # Gap detected!
            elif tail in source_nodes and head in target_nodes:
                flows.append(FlowAssignment(
                    source_sid=idx_to_source[tail],
                    target_sid=idx_to_target[head],
                    units=flow
                ))

    return FlowResult(
        section=section,
        dimension=dimension,
        total_demand=total_demand,
        total_supplied=total_demand - null_flow,
        null_flow=null_flow,  # This is the GAP!
        flows=flows,
        status="OPTIMAL" if status == smcf.OPTIMAL else "INFEASIBLE"
    )
```

---

## Gap Detection: NULL Flows

The magic is in the NULL node. When real sources can't satisfy demand, flow must come from NULL—at cost 100.

```python
@dataclass
class FlowResult:
    section: str
    dimension: str
    total_demand: int      # What targets needed
    total_supplied: int    # What real sources provided
    null_flow: int         # What came from NULL = THE GAP
    flows: list[FlowAssignment]
    status: str
```

**Interpretation:**

| null_flow | Meaning |
|-----------|---------|
| 0 | All demand satisfied by real sources |
| > 0 but < total_demand | Partial gap—some needs unmet |
| = total_demand | Complete gap—no sources for this dimension |

**No arbitrary thresholds.** The gap is the precise amount of unmet demand.

### Gap Classification

```python
def classify_gap(result: FlowResult) -> GapAnalysis:
    if result.null_flow == 0:
        return None  # No gap

    if result.null_flow == result.total_demand:
        gap_type = "no_sources"
        severity = "critical"
    else:
        gap_type = "weak_matches"
        severity = "high" if result.null_flow > result.total_demand / 2 else "medium"

    return GapAnalysis(
        gap_type=gap_type,
        missing_provisions=[result.dimension],
        severity=severity,
        section=result.section
    )
```

---

## Section-Aware Matching

ECA reports have 5 sections, each with different information needs:

| Section | Focus | Key Dimensions |
|---------|-------|----------------|
| I | Parties and Stakeholders | party_info, contractual |
| II | Jurisdiction and Venue | legal_basis, party_info |
| III | Claims and Defenses | facts, legal_basis, admissions |
| IV | Damages and Risk | financials, facts, timeline |
| V | Strategic Assessment | all (synthesis) |

We filter matching by section **before** running transport:

```python
def filter_sources_by_section(sources: list[SourceNode],
                               target_section: str) -> list[SourceNode]:
    """Only match sources that are relevant to the target's section."""
    return [s for s in sources if target_section in s.eca_sections]
```

This reduces the search space by 60-80% and ensures relevance. A sentence about "jurisdiction in Delaware" shouldn't match a damages calculation, even if both mention Delaware.

---

## The Full Pipeline

```python
def run_transport_matching(sources: list[SourceNode],
                           targets: list[TargetNode],
                           config: TransportConfig) -> MatchingResult:

    all_flows = []
    all_gaps = []

    for section in ["I", "II", "III", "IV", "V"]:
        for dimension in DIMENSIONS:
            result = solve_flow(section, dimension, sources, targets, config)
            all_flows.extend(result.flows)

            if result.null_flow > 0:
                gap = classify_gap(result)
                all_gaps.append(gap)

    # Aggregate flows into source-target matches
    matches = aggregate_flows(all_flows)

    return MatchingResult(
        matches=matches,
        gaps=all_gaps,
        coverage=compute_coverage(all_flows)
    )
```

We solve 5 sections × 7 dimensions = **35 flow problems**. Each is small and fast (OR-Tools solves them in milliseconds).

---

## Why This Beats the Heuristic Approach

We replaced a 4-stage heuristic pipeline:

1. **ECA Section Filtering** → Reduce search space
2. **Provisions Scoring** → Cosine similarity on 7 dimensions
3. **BM25 Retrieval** → Lexical matching
4. **LLM Verification** → Claude verifies top matches

### Problems with the Heuristic

| Issue | Heuristic Approach | Optimal Transport |
|-------|-------------------|-------------------|
| **Optimization** | Local (greedy per target) | Global (all targets simultaneously) |
| **Over-assignment** | Popular sources matched repeatedly | Each source used proportionally |
| **Gap detection** | Threshold-based (arbitrary) | Exact (null_flow = unmet demand) |
| **Reproducibility** | LLM in loop = non-deterministic | Deterministic algorithm |
| **Cost** | LLM verification = expensive | No LLM = free |
| **Latency** | 4 stages, LLM calls | Single optimization pass |

### The Numbers

On a typical case (300 source sentences, 150 target sentences):

| Metric | Heuristic | Transport |
|--------|-----------|-----------|
| Runtime | 45 seconds | 0.3 seconds |
| API cost | $0.12 (LLM verification) | $0.00 |
| Deterministic | No | Yes |
| Coverage accuracy | ~85% | 100% (by construction) |

---

## Dimension Weights for Scoring

When we do need semantic similarity (e.g., for UI display), we weight dimensions:

```python
DIMENSION_WEIGHTS = {
    "facts": 1.5,         # High priority—foundation of claims
    "legal_basis": 1.2,   # Important—supports arguments
    "party_info": 1.3,    # Important—establishes standing
    "timeline": 1.4,      # Important—causation matters
    "financials": 1.5,    # High priority—damages are critical
    "contractual": 1.0,   # Moderate—depends on case type
    "admissions": 2.0,    # HIGHEST—undisputed facts are gold
}
```

**Why admissions are weighted 2.0:**

When a party admits something, it's established. No need to prove it. An admission that "payment was late" is worth more than ten documents arguing about payment timing.

---

## Semantic Direction: Solving the Meaning Problem

A subtle issue: sentences can have identical dimension scores but opposite meanings.

```
Source: "Defendant owed no fiduciary duty"
  → legal_basis: strong, facts: strong

Target: "Establish that defendant owed fiduciary duty"
  → legal_basis: strong, facts: strong
```

Same dimensions. Opposite conclusions. Without additional context, transport would match them!

### The Solution: SemanticDirection

```python
class SemanticDirection(BaseModel):
    legal_stance: Literal["asserts", "denies", "neutral"]
    party_favors: Literal["plaintiff", "defendant", "neutral"]
    primary_party: str  # "Amneal", "OSB", etc.
    key_concept: str    # "fiduciary_duty", "breach", etc.
```

We add direction compatibility to scoring:

```python
def direction_compatible(source: SemanticDirection,
                         target: SemanticDirection) -> float:
    # If target is neutral, accept anything
    if target.legal_stance == "neutral":
        return 1.0

    # If stances conflict, zero compatibility
    if source.legal_stance == "denies" and target.legal_stance == "asserts":
        return 0.0

    if source.legal_stance == "asserts" and target.legal_stance == "denies":
        return 0.0

    # Check party alignment
    if source.party_favors != "neutral" and target.party_favors != "neutral":
        if source.party_favors != target.party_favors:
            return 0.3  # Reduced but not zero

    return 1.0
```

This prevents matching "Defendant owed no duty" to "Establish defendant owed duty."

---

## Results in Practice

### Before: Heuristic Matching

```
Section III: Claims and Defenses
  Target 45: "Plaintiff alleges breach of fiduciary duty"
  Matches:
    - complaint:23 (0.89) "Defendant breached duties"
    - complaint:24 (0.87) "Duties were owed under Delaware law"
    - complaint:23 (0.85) "Defendant breached duties"  ← DUPLICATE
    - complaint:23 (0.82) "Defendant breached duties"  ← DUPLICATE

  Gap detection: confidence > 0.7 → no gaps detected

  Problem: Same source matched 3 times. Coverage looks good but is illusory.
```

### After: Transport Matching

```
Section III, dimension "legal_basis":
  Total demand: 8 units
  Total supplied: 6 units
  NULL flow: 2 units  ← EXPLICIT GAP

  Flows:
    - complaint:23 → target:45 (2 units)
    - complaint:24 → target:46 (2 units)
    - contract:12 → target:47 (2 units)
    - NULL → target:48 (2 units)  ← Gap identified

  Gap: Section III needs 2 more units of legal_basis coverage.
       Specifically, target:48 has no matching source.
```

No over-assignment. Explicit gaps. Actionable information.

---

## Implementation: OR-Tools

We use Google's OR-Tools `SimpleMinCostFlow`:

```python
from ortools.graph.python import pywrapgraph

smcf = pywrapgraph.SimpleMinCostFlow()

# Add arc: tail → head, capacity, unit_cost
smcf.add_arc_with_capacity_and_unit_cost(0, 3, 10, 1)

# Set node supply (positive = source, negative = sink)
smcf.set_node_supply(0, 100)   # Super source supplies 100
smcf.set_node_supply(1, -100)  # Super sink demands 100

# Solve
status = smcf.solve()
if status == smcf.OPTIMAL:
    for arc in range(smcf.num_arcs()):
        print(f"Flow on arc {arc}: {smcf.flow(arc)}")
```

OR-Tools is battle-tested (used at Google scale), handles our problem sizes trivially, and has Python bindings.

---

## Key Takeaways

1. **Model matching as resource allocation**, not similarity search. Sources supply; targets demand.

2. **Solve per (section, dimension)**. 35 small problems, not one giant one.

3. **NULL flows = gaps**. No thresholds, no guessing. Unmet demand is precisely measured.

4. **Optimal beats greedy**. Global optimization prevents over-assignment and ensures fair coverage.

5. **Remove LLM from the loop**. Deterministic algorithms are faster, cheaper, and reproducible.

6. **Add semantic direction** to catch meaning conflicts that dimension similarity misses.

---

## What's Next

The transport matching gives us structured data about what matched and what didn't. The next step: feeding this into report generation, where gaps become `[GAP: ...]` placeholders that tell attorneys exactly what evidence to find.

The system doesn't pretend to have answers it doesn't have. It says "I matched these sources to these needs, and here's precisely what's missing."

That's more valuable than a confident-sounding report that hides its uncertainty.

---

*This is Part 2 of a series on building AI-powered legal document analysis. Part 1 covers the enrichment pipeline.*
