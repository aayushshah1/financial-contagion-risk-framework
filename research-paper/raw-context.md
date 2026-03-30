# Raw Project Context: Decision Journey & Technical Rationale

> **Purpose**: This document captures the chronological evolution of design decisions, data source discoveries, and technical rationale that shaped the Financial Contagion Risk Framework. Use this to craft authentic narrative arcs in the paper's Data, Methodology, and Discussion sections.

---

## Timeline of Key Decisions

### Phase 1: Initial Problem Formulation

#### Core Motivation (Early Conceptualization)
**The Network Insight**: The Indian financial landscape is a dense network of Scheduled Commercial Banks (SCBs), NBFCs, and Mutual Funds. While individual institutions may appear resilient, the "pipes" connecting them create a network where failure in one sector (e.g., Power Sector default) can rapidly infect the entire system.

**Three Critical Gaps Identified**:
1. **The Data Lag**: Current assessments (IMF FSAP/RBI FSR) are largely reactive, relying on quarterly balance sheet data
2. **The Information Gap**: Contagion spreads through "super-spreader" entities in hours, while existing detection tools operate in months
3. **Missing Soft Data**: Market sentiment, news, and credit ratings are rarely integrated with numeric capital ratios in a deterministic, scalable model

#### Original Aim Statement
> "To develop a dynamic, **Knowledge Graph-based Risk Engine** providing a 360-degree, real-time view of systemic risk and contagion paths."

#### Commercial Use Case Anchor
**ECL Enhancement**: Help banks (e.g., Kotak Bank) identify "hidden" default risks in their loan books by mapping 2nd and 3rd-order counterparty exposures.

---

## Literature Foundation (Jan 27, 2026 - Research Phase)

### Core Theoretical Papers

1. **IMF SyRIN (2018/2025)** - [IMF WP/18/14]
   - Introduced "Portfolio of Entities" approach
   - CIMDO method to infer multivariate densities of distress
   - **Decision Impact**: Adapted SyRIN framework to real-time Indian context

2. **Caccioli et al. (2020)** - Systemic Risk Measures
   - Novel measure identifying specific institutional contributions to network stability
   - Critical for mapping individual NBFC-to-Bank risk
   - **Decision Impact**: Informed hub-based network filtering strategy

3. **RBI FSR (Dec 2025)**
   - Highlighted growing role of NBFCs
   - Called for macro-stress tests on interconnectedness
   - **Decision Impact**: Validated focus on NBFC-Bank nexus

4. **Epidemiological Modeling (SEIR)**
   - "Financial Virus" models (Susceptible-Exposed-Infected-Recovered)
   - Simulates shock propagation through interbank networks
   - **Decision Impact**: Adopted SEIR for contagion propagation module

5. **rt360 (BCT Digital)** - Commercial Benchmark
   - Integration of diverse data (GST, transaction alerts) into regulatory sandboxes
   - **Decision Impact**: Real-world validation of multi-source data integration

### India-Specific Papers Discovered

6. **"Systematic risk of NBFC and banks"** (2025) - [ScienceDirect]
   - **Significance**: Considered both banks AND NBFCs in India
   - Full dataset with code available: https://data.mendeley.com/datasets/4snkm43drx/2
   - **Citation Target**: Primary empirical reference for Indian context

7. **"Analysing the systemic risk of Indian banks"** (2019) - [Economics Letters]
   - https://www.sciencedirect.com/science/article/abs/pii/S0165176519300023
   - **Citation Target**: Methodological foundation for Indian bank analysis

---

## Data Source Discovery & Selection

### Primary Data Sources (Finalized)

| **Source** | **Type** | **What We Extract** | **Graph Component** |
|------------|----------|---------------------|---------------------|
| **CRISIL Ratings Database** | Credit Ratings | 9,900 entities with ratings, PD matrices | Node attributes: credit_score, PD |
| **Bank Pillar 3 Disclosures** | Regulatory Filings | Industry-wise exposure tables (quarterly) | Edges: Bank →[LENDS_TO]→ Sector |
| **MCA XBRL Data** | Corporate Filings | Related Party Transactions (RPT), Subsidiary structures | Edges: SHAREHOLDER_OF, SUBSIDIARY_OF |
| **NSE/BSE Shareholding** | Market Data | Shareholding patterns | Edges: INVESTOR_IN |
| **CRISIL Industry Mapping API** | Sector Classification | Industry names for all 9,900 entities | Node attribute: industry_name |

### Data Sources Evaluated But Not Used (For Limitations Section)
- **Insta Finance**: APIs for risk reports, shareholder lists (company-specific, not scalable)
- **Tijori Finance**: Investment research tools (subscription barrier)
- **Alpha Vantage**: Market intelligence (US-focused)
- **Screener.in**: Shareholder data (web scraping complexity vs. NSE official data)

### Key Data URLs for Citation
1. **CRISIL Industry Mapping**: 
   ```
   https://www.crisilratings.com/content/crisilratings/en/home/our-business/ratings/credit-ratings-list/_jcr_content/wrapper_100_par/columncontrol_copy/container-100-1/ratingresultlisting.results.json?cmd=CR&start=0&limit=30000
   ```
   - Provides industry classification for all 9,900 CRISIL-rated entities
   - Solved sector name mapping issue

2. **Bank Regulatory Disclosures Example**:
   ```
   https://www.hdfc.bank.in/about-us/regulatory-disclosures
   ```
   - Template for extracting standardized Pillar 3 exposure data

3. **Rating Agency Reports Example**:
   ```
   https://www.crisil.com/mnt/winshare/Ratings/RatingList/RatingDocs/HDFC_Bank_Limited_August_31_2020_RR.html
   ```
   - Source for detailed credit assessments

---

## Critical Technical Decision: The ₹50 Crore Threshold

### Context
Initial dataset contained **9,900 entities** from CRISIL database. Question arose: Should we include all entities or filter for systemic relevance?

### Decision: Filter at ₹50 Crore Total Exposure

**Final Network**:
- **Entities Retained**: 2,858 (28.9%)
- **Entities Dropped**: 7,042 (71.1%)

### Four-Pillar Justification

#### 1. Empirical Justification (The Data Proof)

**Exposure Distribution Analysis**:
- **Total Network Exposure (9,900 entities)**: ₹37,85,217.69 Crores
- **Exposure Retained (>₹50 Cr)**: ₹36,73,748.58 Crores (97.05%)
- **Exposure Discarded (<₹50 Cr)**: ₹1,11,469.11 Crores (2.95%)

**Signal-to-Noise Ratio**:
- Dropped **70% of nodes** (noise)
- Retained **97.05% of systemic financial weight** (signal)
- The discarded 2.95% consists of idiosyncratic MSME loans lacking mass to trigger systemic events

**Paper Framing**: "By implementing a ₹50 Crore exposure threshold, we apply a **97/70 rule**: retaining 97% of systemic exposure while reducing network complexity by 70%."

#### 2. Network Theory Perspective (Caccioli et al., 2020)

**The "Robust-yet-Fragile" Property**:
- Financial networks are **robust** to random failure of small nodes (the 2.95% exposure dropped)
  - Bank capital buffers easily absorb micro-shocks
- Financial networks are **fragile** to failure of large, highly connected hubs
  - Contagion propagates through "whale" entities

**Theoretical Alignment**:
- Caccioli et al. demonstrate that systemic risk is NOT driven by absolute number of nodes
- Risk concentrates in highly connected "hubs"
- By isolating 2,858 "Whale" entities, SEIR contagion model focuses computational resources on nodes capable of transmitting distress

**Citation Strategy**: Reference Caccioli's hub-centrality findings to justify threshold mathematically.

#### 3. Regulatory Alignment (RBI CRILC Standard)

**Not Arbitrary - Matches RBI Framework**:
- RBI established **CRILC (Central Repository of Information on Large Credits)** for systemic risk monitoring
- Banks mandated to report borrower exposures **≥₹5 Crore**
- Intense scrutiny, consortium lending rules scale up at **₹50 Crore mark**
- This is where regulators track "Systemically Important" exposures

**Paper Framing**: "Our threshold mirrors the regulatory demarcation where RBI monitoring intensifies, ensuring our model aligns with official systemic risk definitions."

#### 4. Computational Optimization

**Algorithmic Complexity**:
- Simulating contagion (SEIR) and graph centrality: O(V+E) to O(V³)
- Including 7,000 micro-nodes introduces excessive computational latency WITHOUT altering final Systemic Risk Index (SRI)

**Practical Benefits**:
- **Dimensionality Reduction**: Optimized technique for real-time analysis
- Streamlit dashboard renders Knowledge Graph smoothly
- "What-If" stress tests execute in milliseconds (not minutes)

**Paper Framing**: "The threshold serves dual purposes: theoretical rigor (network science) and practical scalability (real-time deployment)."

---

## Entity Resolution & Mapping Strategy

### Problem Identified
Need consistent entity identifiers across heterogeneous data sources (CRISIL, MCA, NSE, bank disclosures).

### Solution: CIN-Based Key Mapping

**CIN (Corporate Identity Number)** chosen as primary key:
- Unique identifier assigned by MCA to all Indian companies
- Persistent across mergers, name changes
- Present in CRISIL data, MCA XBRL filings, shareholding patterns

**Implementation Pipeline**:

1. **CRISIL Data**: Direct CIN mapping (primary)
2. **RPT & Subsidiary Data**: Extract CIN from XBRL filings
3. **Entities Without CIN**: 295 entities (10.3% of final 2,858)
   - Resolution: Brave AI API for fuzzy name matching
   - Fallback: CRISIL industry mapping API

**Graph Representation**:
- **Node ID**: CIN (when available) or generated UUID
- **Node Name**: Legal entity name (for visualization)
- **Node Type**: Bank | NBFC | Corporate | Sector

---

## Knowledge Graph Schema Design

### Final Pipeline Architecture

**Each Bank Document Contains**:
a. List of all borrowers with amounts and instrument types
b. Related Party Transaction (RPT) data (from XBRL)
c. Subsidiary data (from XBRL)

### Graph Relationships (Neo4j)

| **Relationship** | **Source → Target** | **Attributes** | **Data Source** |
|------------------|---------------------|----------------|-----------------|
| `LENDS_TO` | Bank → Corporate | amount, instrument, maturity | Pillar 3 Disclosures |
| `SHAREHOLDER_OF` | Investor → Corporate | stake_percentage, date | NSE/BSE Shareholding |
| `SUBSIDIARY_OF` | Subsidiary → Parent | ownership_percentage | MCA XBRL |
| `BORROWS_FROM` | Corporate → Bank | amount, collateral | (Reverse of LENDS_TO) |
| `RELATED_PARTY_OF` | Entity → Entity | transaction_type, amount | XBRL RPT Data |

### Node Properties

**Bank/NBFC Nodes**:
- `entity_type`: "Bank" | "NBFC"
- `capital_adequacy`: CAR from regulatory filings
- `total_assets`: From balance sheet
- `stress_score`: Calculated (0-100)

**Corporate Nodes**:
- `entity_type`: "Corporate"
- `industry_name`: From CRISIL API
- `crisil_rating`: Current rating
- `pd_score`: Probability of Default
- `stress_score`: Calculated (0-100)

**Sector Nodes**:
- `entity_type`: "Sector"
- `aggregated_exposure`: Sum of all loans to sector
- `sector_stress`: Weighted average of corporate stress

---

## Methodological Choices (To Expand in Paper)

### Why MongoDB + Neo4j Hybrid?

**MongoDB** (Document Store):
- **Rationale**: Financial data is inherently heterogeneous
  - Bank balance sheets vs. NBFC structures vs. corporate filings
  - Nested documents (subsidiaries within subsidiaries)
  - Schema flexibility for adding new data sources

**Neo4j** (Graph Database):
- **Rationale**: Contagion IS a graph problem
  - Native graph traversal (Cypher queries)
  - Optimized for shortest-path, centrality algorithms
  - Real-time "What-If" scenario simulation

**Why Not Single Database?**
- MongoDB: Poor at multi-hop relationship queries (slow JOINs)
- Neo4j: Poor at storing unstructured/nested financial documents
- **Solution**: Best-of-both with ETL pipeline (MongoDB → Neo4j)

### Why FinBERT for Sentiment?

**Alternatives Considered**:
- Generic BERT: Not finance-domain trained
- VADER: Rule-based, misses context
- GPT-based: Too expensive for real-time at scale

**FinBERT Selection**:
- Pre-trained on financial news corpus
- Understands domain-specific language ("default," "restructuring," "NPA")
- Lightweight enough for real-time inference
- Validated in academic literature (Araci, 2019)

---

## Data Coverage & Limitations (For Paper Section 5 & 13)

### Coverage Achieved

| **Category** | **Coverage** | **Source** |
|--------------|--------------|------------|
| **Scheduled Commercial Banks** | 43 major banks | RBI list + Pillar 3 disclosures |
| **NBFCs** | 850+ rated NBFCs | CRISIL database |
| **Corporates** | 2,858 entities (>₹50 Cr exposure) | CRISIL + MCA |
| **Total Exposure Mapped** | ₹36.73 Lakh Crores | Aggregated loan books |
| **Relationships** | ~15,000 edges | Lending + Shareholding + Subsidiary |

### Acknowledged Limitations

1. **OTC Derivatives Not Captured**
   - Inter-bank derivatives market (IRS, CDS) not included
   - Data not publicly available
   - **Mitigation**: Note in Limitations; suggest RBI data access for future

2. **Real-Time Data Lag**
   - Bank disclosures: Quarterly
   - CRISIL ratings: Event-driven updates
   - News sentiment: Real-time (only component)
   - **Mitigation**: Stress scores update as new data arrives

3. **Unlisted Entities**
   - Private companies without CRISIL ratings: Not covered
   - Represents ~20% of credit market
   - **Mitigation**: Focus on "systemically important" rated entities

4. **Geographic Scope**
   - India-only
   - Cross-border exposures simplified
   - **Mitigation**: Note as scope limitation; future work for global extension

---

## Secondary Decision Points (To Weave into Narrative)

### Sector Name Mapping Resolution
**Problem**: 295 entities (post-₹50Cr filter) lacked CIN → couldn't auto-map to CRISIL industry
**Solution**: CRISIL public API provides industry classification for all 9,900 entities
**Outcome**: 100% sector coverage for filtered entities

### Node Representation Choice
**Decision**: Use entity legal name (not CIN) for node labels in visualization
**Rationale**: Human readability in Streamlit dashboard
**Technical**: CIN stored as node property for backend joins

### Data Refresh Strategy
**Challenge**: How often to update Knowledge Graph?
**Initial Design**: Monthly batch updates (quarterly for banks, event-driven for ratings)
**Future Enhancement**: Real-time streaming (mentioned in Future Work)

---

## Key Equations & Formulas (To Formalize in Paper)

### Stress Score Calculation (Simplified)
```
S_i,t = α * PD_i,t + β * Sentiment_i,t + γ * Σ(w_ij * S_j,t-1)
```
Where:
- `S_i,t`: Stress score of entity i at time t
- `PD_i,t`: Probability of Default (from CRISIL rating)
- `Sentiment_i,t`: FinBERT news sentiment score
- `w_ij`: Exposure weight from entity j to entity i
- `α, β, γ`: Calibration parameters

### Network Filtering Rule
```
Entity included ⟺ Σ(all_exposures) ≥ ₹50 Crores
```

### Contagion Propagation (SEIR-Inspired)
```
Stress_Transfer(i → j) = exposure_ij / total_capital_j * stress_i
```
- If `Stress_Transfer > threshold` → j moves from Susceptible to Exposed

---

## Writing Strategy Notes (For Paper Sections)

### For Introduction (Section 2)
**Hook Structure**:
1. Start with IL&FS crisis (Sept 2018) - vivid narrative
2. Transition: "This episode revealed three critical gaps..." (cite our three gaps)
3. Problem statement: "Existing tools operate in months; contagion spreads in hours"
4. Our solution: "We developed a real-time Knowledge Graph..."

### For Data Section (Section 5)
**Narrative Arc**:
1. "We identified four critical data sources..." (CRISIL, MCA, Banks, NSE)
2. "The primary challenge was entity resolution..." (CIN mapping story)
3. "Our dataset covers ₹36.73 Lakh Crores..." (coverage stats)
4. "We acknowledge three key limitations..." (OTC, lag, unlisted)

### For Methodology Sections (6-9)
**Justification Pattern** (Emulate Brownlees & Engle):
1. **Intuition First**: "Intuitively, systemic risk concentrates in large exposures..."
2. **Design Choice**: "We implemented a ₹50 Crore threshold based on..."
3. **Theoretical Grounding**: "This aligns with Caccioli et al.'s hub-centrality findings..."
4. **Empirical Validation**: "Analysis shows 97% exposure retention with 70% complexity reduction..."

### For Results Section (10)
**Present the "97/70 Rule"**:
- Table: Exposure distribution comparison (9,900 vs 2,858 entities)
- Figure: Network visualization showing hub concentration
- Interpretation: "This validates network theory predictions..."

### For Discussion Section (12)
**Policy Implications of ₹50 Cr Threshold**:
- "Our threshold naturally aligns with RBI CRILC monitoring..."
- "This suggests our framework can integrate seamlessly into existing regulatory reporting..."
- "Banks can leverage this for ECL calculations under Ind AS 109..."

---

## Technical Artifacts Generated (For Appendix/Figures)

1. **Network Statistics**:
   - Node count: 2,858
   - Edge count: ~15,000
   - Average degree: ~10.5
   - Network diameter: [To calculate]
   - Clustering coefficient: [To calculate]

2. **Exposure Distribution** (For histogram):
   - Median exposure: [To calculate]
   - 90th percentile: [To calculate]
   - Top 10 entities by exposure: [Extract from CSV]

3. **Sector Breakdown** (For pie chart):
   - Banking: X%
   - NBFCs: Y%
   - Power: Z%
   - Infrastructure: W%
   - [Other sectors]

---

## Citation Preparation Checklist

### Papers to Actually Fetch & Read (Priority)
- [ ] IMF SyRIN (2018) - WP/18/14
- [ ] Caccioli et al. (2020) - Systemic risk measures paper
- [ ] "Systematic risk of NBFC and banks" (2025) - Get full citation
- [ ] "Analysing the systemic risk of Indian banks" (2019) - Economics Letters
- [ ] RBI Financial Stability Report (Dec 2025) - Download PDF
- [ ] Araci (2019) - FinBERT paper

### Regulatory Documents
- [ ] RBI CRILC Guidelines (2014) - For ₹50 Cr justification
- [ ] Basel III Pillar 3 Disclosure Requirements - For data extraction methodology
- [ ] Ind AS 109 (ECL Guidelines) - For commercial use case framing

### Benchmark Systems
- [ ] rt360 by BCT Digital - Competitor analysis
- [ ] Bloomberg Systemic Risk Dashboard - Industry standard comparison

---

## Future Context to Add

**Awaiting**:
- IL&FS crisis detailed context (next input)
- Specific stress propagation results from current implementation
- Network centrality rankings (for Results section)
- Actual IL&FS simulation outputs (for Case Study section)

---

## Notes for Different Paper Sections

### Abstract (~250 words)
**Formula**: Problem (1-2 sentences) → Gap (1 sentence) → Method (2-3 sentences) → Data (1-2 sentences) → Result (2 sentences) → Implication (1-2 sentences)

**Key Numbers to Include**:
- 2,858 entities
- ₹36.73 Lakh Crores exposure
- 97% coverage with 70% complexity reduction
- Real-time sentiment integration

### Keywords (5-7 terms)
Suggested: Systemic Risk, Financial Contagion, Knowledge Graphs, NBFC, Indian Banking, Network Analysis, FinBERT

---

## End of Raw Context Document

**Last Updated**: [To be updated as new context arrives]
**Next Steps**: 
1. Receive IL&FS crisis context
2. Fetch and analyze gold-standard papers
3. Begin drafting Introduction with crisis hook
