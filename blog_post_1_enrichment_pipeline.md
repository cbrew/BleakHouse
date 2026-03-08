# From Scanned PDFs to Structured Legal Intelligence: Building an AI-Powered Document Enrichment Pipeline

*How we built a system that transforms messy legal documents into richly annotated, machine-readable data for Early Case Assessment*

---

## The Problem: Legal Documents Are a Mess

Legal documents arrive in every imaginable format: scanned PDFs with OCR artifacts, Word documents with inconsistent formatting, emails exported as HTML. Before any AI can reason about the law, it needs clean, structured text.

But cleaning isn't enough. A sentence like "Defendant breached the employment agreement on March 15, 2023" contains multiple layers of meaning:
- **Facts**: A breach occurred
- **Timeline**: March 15, 2023
- **Party information**: The defendant
- **Contractual**: Employment agreement terms

Our pipeline extracts all of this, turning documents into structured knowledge graphs that power downstream legal analysis.

---

## Architecture Overview

```
PDF/DOCX → HTML Extract → Sentence Segmentation → OCR Correction
                                    ↓
                          LLM Enrichment (Claude)
                                    ↓
              ┌─────────────────────┴─────────────────────┐
              ↓                                           ↓
      Source Documents                            Target Documents
      (Complaints, Contracts)                     (ECA Report Draft)
              ↓                                           ↓
      "What does this PROVIDE?"               "What does this NEED?"
      - 7 provision dimensions                 - 7 need dimensions
      - Contribution roles                     - Gap detection
      - Strategic importance                   - Expected contribution
              ↓                                           ↓
              └─────────────────────┬─────────────────────┘
                                    ↓
                          Document Profiles
                                    ↓
                          Match Matrix
                                    ↓
                          ECA Report Generation
```

---

## Stage 1: Text Extraction and Normalization

### The Extraction Challenge

Legal PDFs often come from document management systems that produce... creative... HTML output. We use `pdfplumber` for PDFs and `pypandoc` for DOCX, then parse the resulting HTML to preserve document structure.

```python
def extract_text_blocks(html: str) -> list[TextBlock]:
    """Extract text while preserving structural information."""
    soup = BeautifulSoup(html, 'lxml')
    blocks = []

    for tag in soup.find_all(['p', 'li', 'td', 'blockquote', 'h1', 'h2', 'h3']):
        blocks.append(TextBlock(
            text=normalize_whitespace(tag.get_text()),
            tag=tag.name,
            xpath=get_xpath(tag),  # Preserve location for reconstruction
        ))

    return blocks
```

### Unicode Normalization

OCR engines produce Unicode chaos. We use `ftfy` (Fixes Text For You) to handle:
- Smart quotes that became `â€™`
- Ligatures that became `ﬁ` instead of `fi`
- Encoding misdetections

```python
text = ftfy.fix_text(raw_text)
```

### Dehyphenation

Scanned documents often have line-break hyphenation that OCR preserves literally:

```
The defen-
dant failed to...
```

Our dehyphenation logic reconnects these while being careful not to break intentional hyphens:

```python
def dehyphenate(text: str) -> str:
    # Only rejoin if the result is a real word
    pattern = r'(\w+)-\n(\w+)'
    return re.sub(pattern, lambda m:
        m.group(1) + m.group(2) if is_word(m.group(1) + m.group(2))
        else m.group(0), text)
```

---

## Stage 2: LLM-Powered Sentence Correction

Raw OCR text has errors that simple regex can't fix. We use Claude to perform intelligent correction:

### The Three-Task Prompt

```
You are reviewing OCR'd legal text. Perform these tasks:

1. SEGMENTATION REVIEW
   - Merge fragments under 15 characters
   - Split run-on sentences over 400 characters at natural boundaries
   - Preserve legal citations as single units

2. OCR ERROR CORRECTION
   - Fix common OCR errors: rn→m, 0/O, 1/l/I, fi/fl ligatures
   - PRESERVE: dates, dollar amounts, docket numbers, section symbols
   - When uncertain, prefer the legal term

3. OFFSET TRACKING
   - Record char_start and char_end for each corrected sentence
   - Enable reconstruction of original→corrected mapping
```

### Structured Output

We use Claude's structured output mode (`client.beta.messages.parse()`) with Pydantic models:

```python
class CorrectedSentence(BaseModel):
    corrected_text: str
    confidence: Literal["high", "medium", "low"]
    notes: str  # What was changed and why
    char_start: int
    char_end: int

class BlockResult(BaseModel):
    block_id: str
    sentences: list[CorrectedSentence]
```

This guarantees valid JSON that matches our schema—no parsing errors, no hallucinated fields.

---

## Stage 3: Enrichment—The Heart of the Pipeline

Here's where documents become intelligent. Each sentence gets classified across multiple dimensions.

### The 7 Provision Dimensions

We model legal content as a 7-dimensional vector:

| Dimension | What It Captures | Example |
|-----------|------------------|---------|
| `facts` | Events, circumstances, actions | "Defendant terminated plaintiff on March 15" |
| `legal_basis` | Statutes, case law, legal authorities | "Under 42 U.S.C. § 1983..." |
| `party_info` | Parties, relationships, roles | "Amneal Pharmaceuticals, a Delaware corporation" |
| `timeline` | Dates, sequences, causation | "Between January and March 2023" |
| `financials` | Money, damages, payments | "Plaintiff seeks $2.5 million in damages" |
| `contractual` | Contract terms, obligations | "Section 4.2 of the Agreement provides..." |
| `admissions` | Acknowledgments, concessions | "Defendant admits that payment was late" |

Each dimension has a strength: `none`, `weak`, or `strong`.

### Source vs. Target: A Symmetric Design

**Source documents** (complaints, contracts, depositions) **provide** information:
```python
class SourceEnrichmentResult(BaseModel):
    provisions: Provisions  # What this sentence PROVIDES
    eca_sections: list[ECASection]  # Which report sections it informs
    contribution_role: ContributionRole  # DEFINES, ALLEGES, ADMITS, etc.
    strategic_importance: int  # 0-5 scale
```

**Target documents** (the ECA report draft) **need** information:
```python
class TargetEnrichmentResult(BaseModel):
    needs: Needs  # What this sentence NEEDS from sources
    gap_type: GapType | None  # document_missing, fact_unsupported, etc.
    gap_severity: GapSeverity  # critical, high, medium, none
```

This symmetry is crucial: it lets us model matching as a supply-demand problem.

### Contribution Roles

Beyond dimensions, we classify *how* each source contributes:

| Role | Meaning | Example |
|------|---------|---------|
| `DEFINES` | Establishes terms, parties, relationships | Contract definitions |
| `ALLEGES` | Makes claims requiring proof | Complaint allegations |
| `ADMITS` | Acknowledges facts (gold standard!) | "Defendant admits..." |
| `DENIES` | Disputes allegations | "Defendant denies..." |
| `EVIDENCES` | Provides supporting evidence | Exhibit references |
| `REFERENCES` | Cites external authority | Case citations |

Admissions are weighted highest in matching—when a party admits something, you don't need other evidence.

### The Enrichment Prompt

```
You are enriching legal document sentences for Early Case Assessment.

ECA SECTIONS:
- Section I: Parties and Key Stakeholders
- Section II: Jurisdiction and Venue
- Section III: Assessment of Claims and Defenses
- Section IV: Damages and Risk Exposure
- Section V: Strategic Assessment and Recommendations

For each sentence, determine:
1. Which ECA sections does it inform? (may be multiple)
2. What is its contribution role?
3. Rate each provision dimension (none/weak/strong)
4. Strategic importance (0-5, with reasoning if ≥3)
5. BM25 context (key terms for retrieval)
```

### Batch Processing

We batch sentences for efficiency (typically 20-30 per API call), with fallback handling for failures:

```python
def enrich_batch(sentences: list[Sentence]) -> list[EnrichmentResult]:
    try:
        response = client.beta.messages.parse(
            model="claude-haiku-4-5-20251001",
            max_tokens=16384,
            messages=[{"role": "user", "content": format_batch(sentences)}],
            output_format=BatchOutput,
        )
        return response.parsed_output.results
    except ValidationError:
        # Fallback: return empty enrichments, log for retry
        return [empty_result() for _ in sentences]
```

---

## Stage 4: Document Profiles

After enrichment, we aggregate sentence-level data into document profiles:

```python
class DocumentProfile(BaseModel):
    doc_name: str
    doc_type: str  # complaint, contract, correspondence, etc.

    # Aggregated provisions
    provisions_summary: dict[str, int]  # {dimension: count of strong sentences}

    # Role distribution
    contribution_roles: dict[str, int]  # {DEFINES: 5, ALLEGES: 12, ...}

    # Top sentences per section (sorted by importance)
    sentences_by_section: dict[str, list[SentenceRef]]

    # Coverage assessment
    sections_covered: list[str]  # Sections with ≥2 relevant sentences
    relevance_score: float  # 0-1 based on strong provisions
```

This gives us a queryable summary: "Which documents have strong `financials` provisions?" or "What defines party relationships?"

---

## Stage 5: Match Matrix

The match matrix maps what's needed (target) to what's available (sources):

```python
class SectionMatch(BaseModel):
    section: str  # "I", "II", "III", "IV", "V"
    matched_sentences: dict[str, list[SentenceRef]]  # By source document
    coverage: dict[str, float]  # {dimension: 0.0-1.0}
    gaps: list[Gap]  # What's missing

def compute_coverage(sources: list[SourceSentence], dimension: str) -> float:
    """Compute coverage score for a dimension."""
    strong_count = sum(1 for s in sources if s.provisions[dimension] == "strong")
    weak_count = sum(1 for s in sources if s.provisions[dimension] == "weak")

    raw_score = strong_count * 1.0 + weak_count * 0.3
    return min(1.0, raw_score / 5.0)  # Normalize, cap at 1.0
```

### Gap Identification

Gaps are features, not bugs. We explicitly identify what's missing:

```python
def identify_gaps(section: str, coverage: dict[str, float]) -> list[Gap]:
    gaps = []
    for dim, score in coverage.items():
        if score < 0.3:  # Threshold for gap
            gaps.append(Gap(
                dimension=dim,
                severity="critical" if score == 0 else "high",
                description=f"Insufficient {dim} coverage for Section {section}"
            ))
    return gaps
```

---

## Stage 6: ECA Report Generation

Finally, we generate the report using Claude, with explicit gap signaling:

### Model Selection by Section

```python
SECTION_MODELS = {
    "I": "claude-haiku-4-5-20251001",    # Parties: straightforward
    "II": "claude-haiku-4-5-20251001",   # Jurisdiction: straightforward
    "III": "claude-haiku-4-5-20251001",  # Claims: complex but pattern-based
    "IV": "claude-haiku-4-5-20251001",   # Damages: calculation-focused
    "V": "claude-sonnet-4-5-20250929",   # Strategy: requires synthesis
}
```

Section V (Strategic Assessment) uses Sonnet because it requires synthesizing all prior sections into recommendations—genuine reasoning, not just pattern matching.

### The Generation Prompt

```
Generate Section {num}: {title}

CRITICAL RULES:
1. Only state what sources support—never fabricate
2. Include citations as [doc_name:SID] after factual claims
3. Insert [GAP: description] where evidence is missing
4. Gaps tell the attorney what to find—they're valuable

COVERAGE ASSESSMENT:
- facts: 85% (STRONG)
- legal_basis: 45% (WEAK)
- financials: 20% (CRITICAL GAP)

AVAILABLE EVIDENCE:
=== complaint ===
  [123] (ALLEGES_ROLE) Plaintiff worked for defendant from 2019-2023
      provisions: facts=strong, party_info=strong, timeline=strong
  [124] (ALLEGES_ROLE) Defendant failed to pay overtime wages
      provisions: facts=strong, legal_basis=weak, financials=weak
...

Generate the section with proper citations and gap markers.
```

### Output Structure

```python
class GeneratedParagraph(BaseModel):
    text: str  # With [doc:SID] citations and [GAP: ...] markers
    source_refs: list[str]  # Citations used
    has_gap: bool
    gap_description: str | None
    gap_severity: Literal["critical", "high", "medium", "none"]
```

### Example Output

```markdown
## Section IV: Damages and Risk Exposure

Plaintiff seeks compensatory damages for unpaid overtime wages. Based on the
employment records [payroll_records:45], plaintiff worked an average of 52 hours
per week from January 2021 through March 2023 [timesheet_summary:12].

[GAP: No source documents establish the applicable overtime rate or calculate
total damages. Discovery should target payroll records showing hourly rates.]

Defendant's potential exposure includes statutory penalties under the FLSA
[complaint:89], which provides for liquidated damages equal to unpaid wages
[complaint:91].
```

---

## The Complete Pipeline: Data Flow

```
Raw Document (PDF/DOCX)
    │
    ▼
Text Extraction (pdfplumber, pypandoc)
    │
    ▼
HTML Parsing (preserve structure via xpath)
    │
    ▼
Sentence Correction (Claude)
    │  - Segmentation review
    │  - OCR error fixing
    │  - Offset tracking
    ▼
Enrichment (Claude)
    │  - 7 provision dimensions
    │  - Contribution roles
    │  - Strategic importance
    │  - ECA section mapping
    ▼
Document Profiles (aggregation)
    │  - Provisions summary
    │  - Role distribution
    │  - Section coverage
    ▼
Match Matrix (supply-demand mapping)
    │  - Coverage scoring
    │  - Gap identification
    ▼
ECA Report (Claude)
    │  - Section-by-section generation
    │  - [doc:SID] citations
    │  - [GAP: ...] markers
    ▼
Output: JSON + Markdown + DOCX
```

---

## Key Design Decisions

### 1. Structured Outputs Everywhere

Every LLM call uses `client.beta.messages.parse()` with Pydantic models. This eliminates parsing errors and guarantees schema compliance.

### 2. Gaps as First-Class Citizens

Rather than hiding missing information, we surface it explicitly. `[GAP: ...]` markers tell attorneys exactly what to find—that's more valuable than a report that pretends to be complete.

### 3. Symmetric Source/Target Design

Modeling sources as "supply" and targets as "demand" across the same 7 dimensions enables optimal transport matching (covered in the next post).

### 4. Model Selection by Task Complexity

Haiku for pattern-matching tasks, Sonnet for synthesis. This balances cost and quality.

### 5. Batch Processing with Graceful Degradation

Batch sentences for efficiency, but handle failures gracefully. A failed batch returns empty results rather than crashing the pipeline.

---

## What's Next

In the next post, we'll dive into **source-target matching**: how we use optimal transport (min-cost flow) to match source provisions to target needs, ensuring global optimization and explicit gap detection.

The enrichment pipeline gives us structured data. The matching pipeline tells us how well that data meets the report's requirements.

---

*This is Part 1 of a series on building AI-powered legal document analysis. Part 2 covers the matching algorithm.*
