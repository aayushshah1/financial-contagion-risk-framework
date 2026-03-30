# Research Paper Context & Guidelines

## Paper Title
**A Contagion Mapping Framework for Eminent Systemic Risks In the Indian Financial Credit Sector.**

---

## Formatting Requirements

| Specification | Details |
|--------------|---------|
| **Font** | Times New Roman 12pt |
| **Spacing** | 1.5 line spacing |
| **Citations** | APA style |
| **Layout** | One-column portrait |
| **Length** | ~8,000–10,000 words |
| **Anonymization** | Yes (remove author names) |
| **Figures** | Numbered above table |

---

## Paper Structure (15 Sections)

### 1. Title, Abstract & Keywords (~250 words)
- State problem
- Method used
- Dataset description
- Key result
- Implication

### 2. Introduction
- **Hook**: IL&FS crisis
- Asymmetric information problem
- Research gap identification
- Contribution statement
- Paper structure overview

### 3. Literature Review
- Systemic risk theory
- Network contagion models
- Indian credit market studies
- FinBERT NLP applications in finance

### 4. Research Motivation & Problem Statement
- Why India?
- Why credit sector specifically?
- Scope of dataset
- Research questions

### 5. Data & Sources
- CRISIL reports
- RPT (Related Party Transactions) data
- MCA (Ministry of Corporate Affairs) filings
- Scheduled Banks data
- Coverage & limitations

### 6. Framework Architecture
- System overview diagram
- Pipeline flow
- MongoDB + Neo4j design rationale
- Technical implementation justification

### 7. Entity Stress Scoring Model
- PD (Probability of Default) transition matrices
- Rating-based scoring methodology
- FinBERT sentiment integration
- Stress formula derivation

### 8. Knowledge Graph Construction
- Entity resolution process
- Relationship types:
  - `LENDS_TO`
  - `SHAREHOLDER_OF`
  - `SUBSIDIARY_OF`
- Graph schema design

### 9. Contagion Propagation Model
- Fixed-point iteration algorithm
- Stress transfer function
- Exposure weighting methodology
- Convergence criteria

### 10. Empirical Results & Validation
- Stress score outputs
- Network heatmaps
- IL&FS-like scenario simulation
- Sensitivity analysis

### 11. Case Study: IL&FS Contagion Simulation
- Simulate IL&FS default event
- Trace 2nd/3rd order effects
- Compare to actual observed stress
- Validation against real-world outcomes

### 12. Discussion & Policy Implications
- **For institutional investors**: Risk assessment tools
- **For bank management**: Portfolio stress testing
- **For regulators** (SEBI/RBI): Systemic risk monitoring
- Framework scalability considerations

### 13. Limitations & Future Work
- Data coverage gaps
- Real-time feeds integration
- OTC derivatives not captured
- Extension to full market ecosystem

### 14. Conclusion
- Restate contribution
- Empirical proof of concept
- Call for regulatory adoption
- Future research directions

### 15. References
- APA or IEEE format
- Comprehensive bibliography

### 16. Appendix (Optional)
- Technical details
- Additional data tables
- Code snippets
- Supplementary figures

---

## Current Writing Focus
Priority sections to complete first:
1. **Introduction** - IL&FS crisis hook
2. **Literature Review** - Theoretical foundation
3. **Research Motivation & Problem Statement** - Justification
4. **Case Study: IL&FS** - Empirical validation

---

## Key Technical Components (from codebase)

### Data Pipeline
- **Ingestion**: `ingestion/` - CRISIL scrapers, XLSX ratio extractors
- **Consolidation**: Data pushed to MongoDB (`financial_kg` database)
- **Storage**: MongoDB (document store) + Neo4j (graph database)

### Analytics Engine
- **Location**: `engine/` directory
- **Entity Stress**: `engine/stress/entity_stress_pipeline.py`
  - Uses PD transition matrices
  - Rating-based scoring (0-100 scale)
- **Sentiment Analysis**: `news_data_fetcher_stress_mapper.py`
  - FinBERT integration
  - Real-time news sentiment scoring
- **Contagion Model**: Fixed-point iteration over graph
  - Stress transfer through relationships
  - Exposure-weighted propagation

### Knowledge Graph
- **Builder**: `prototype_kg/loader.py`
- **Relationships**: 
  - `LENDS_TO` (credit exposure)
  - `SHAREHOLDER_OF` (equity exposure)
  - `SUBSIDIARY_OF` (ownership structure)
- **Entity Types**: Banks, Companies, Sectors, Industries

### Visualization
- **Framework**: React/Vite/TypeScript + React Three Fiber
- **Features**: 3D network visualization, interactive stress heatmaps
- **Location**: `visualser/` directory

### Outputs
- **Stress Scores**: `entity_stress_scores.csv`
- **Format**: 0-100 scale, PD percentages, confidence intervals
- **Risk Tiers**: Investment Grade vs Default categories

---

## IL&FS Crisis Context (for Introduction/Case Study)

### Background
- IL&FS (Infrastructure Leasing & Financial Services Limited)
- September 2018 crisis
- Shadow banking/NBFC sector exposure
- Systemic risk manifestation

### Key Events
- Default on debt obligations
- Rating downgrades
- Market contagion
- Regulatory intervention

### Relevance to Framework
- Perfect case study for validation
- Demonstrates asymmetric information problem
- Shows need for network-based risk assessment
- Validates contagion propagation model

---

## Data Sources Detail

### CRISIL
- Credit rating data
- PD transition matrices
- Default statistics
- Corporate credit profiles

### MCA (Ministry of Corporate Affairs)
- Corporate filings
- Financial statements
- Directorship information
- Related party transactions

### RPT Data
- Lending relationships
- Shareholding patterns
- Subsidiary structures
- Group affiliations

### Scheduled Banks
- Balance sheet data
- Loan books
- Credit exposure
- Capital adequacy ratios

---

## Research Questions (to elaborate)

1. How can network-based models improve systemic risk detection in Indian credit markets?
2. What role does sentiment analysis play in early warning systems?
3. How does stress propagate through multi-layer financial networks?
4. Can graph-based approaches predict contagion effects?
5. What are policy implications for financial stability monitoring?

---

## Key Contributions

1. **Novel Framework**: Integration of credit scoring + NLP + graph analytics
2. **Indian Context**: First comprehensive network model for Indian credit sector
3. **Real-time Capability**: Live sentiment integration with FinBERT
4. **Validation**: IL&FS case study provides empirical proof
5. **Practical Tool**: Deployable system for regulators/institutions

---

## Technical Innovation Highlights

### Hybrid Database Architecture
- **MongoDB**: Document flexibility for heterogeneous financial data
- **Neo4j**: Graph traversal for contagion modeling
- **Justification**: Combines scalability with relationship-first queries

### Multi-source Stress Scoring
- Historical credit data (CRISIL PD matrices)
- Real-time sentiment (FinBERT on news)
- Network position (centrality measures)
- **Result**: Holistic stress assessment

### Fixed-Point Contagion Algorithm
- Iterative stress propagation
- Exposure-weighted transfer
- Convergence to equilibrium
- **Advantage**: Captures cascading effects

---

## Notes & Considerations

### Writing Strategy
- Start with Introduction (crisis hook engages reader)
- Build theoretical foundation in LR
- Justify approach in Motivation section
- Defer technical details to methodology sections
- Use IL&FS case study as validation anchor

### Citation Strategy (APA)
- Systemic risk: Allen & Gale (2000), Acemoglu et al. (2015)
- Network models: Battiston et al. (2012), Elliott et al. (2014)
- Indian markets: RBI reports, SEBI guidelines
- NLP finance: Araci (2019) - FinBERT, sentiment analysis papers

### Figure Planning
1. System architecture diagram
2. Knowledge graph schema
3. Stress propagation flowchart
4. IL&FS contagion network visualization
5. Heatmap of stress distribution
6. Sensitivity analysis charts

---

## Status Tracking

### Completed
- [ ] Title & Abstract
- [ ] Introduction
- [ ] Literature Review
- [ ] Research Motivation
- [ ] Data & Sources
- [ ] Framework Architecture
- [ ] Entity Stress Model
- [ ] KG Construction
- [ ] Contagion Model
- [ ] Empirical Results
- [ ] IL&FS Case Study
- [ ] Discussion & Policy
- [ ] Limitations
- [ ] Conclusion
- [ ] References
- [ ] Appendix

### Current Priority
- Introduction (IL&FS hook)
- Literature Review
- Research Motivation & Problem Statement
- IL&FS Case Study

---

## Custom Skill Available

### 📚 Academic Financial Risk Writer
**Location**: `~/.github-copilot-skills/academic-financial-risk-writer.md`

This skill reverse-engineers the writing style of gold-standard papers in financial risk to ensure your paper matches top-tier journal quality.

**How to use**:
```
@academic-financial-risk-writer draft the Introduction section (1,200 words).

Key points:
- IL&FS crisis hook
- Asymmetric information problem
- Research gap
- Framework contribution

Style: Match Acharya et al. (2017) crisis-hook pattern and Bajaj & Damodaran (2023) Indian context.
```

---

## Revision Notes
(Add notes here as we iterate on drafts)

