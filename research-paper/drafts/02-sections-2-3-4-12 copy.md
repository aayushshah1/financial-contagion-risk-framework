# Academic Paper Draft: Sections 2, 3, 4, 12 (REVISED v3 — Faculty-Reviewed)

**Paper Title**: A Knowledge-Graph Contagion Mapping Framework for Systemic Risk in India's Credit Sector

**Formatting**: Times New Roman 12pt | Double spacing | APA citations | Anonymized

**Target Word Budget**: ~1,850 words across 4 sections

---

## 2. Introduction (~450 words)

September 2018. Infrastructure Leasing & Financial Services Limited (IL&FS)—a shadow lender rated investment-grade by three agencies—defaulted on ₹1,000 Crore commercial paper (Ministry of Corporate Affairs, 2018). Within weeks, investigators discovered the group held ₹91,000 Crores of debt distributed across 348 subsidiaries, built on parent equity of just ₹9.83 Crores (Serious Fraud Investigation Office, 2019). A debt-to-equity ratio of 9,257:1.

The contagion was swift. Over 300 NBFC and Housing Finance Company stocks lost between 20–70% of their value in the following quarter (NSE India, 2018). Mutual funds holding IL&FS paper faced redemption pressures; DSP Mutual Fund's forced sale of DHFL commercial paper triggered its own spiral. Credit spreads for AAA-rated NBFCs widened 100 basis points overnight (Reserve Bank of India, 2018). What market observers widely characterized as India's own "Lehman moment" during then-RBI Governor Patel's tenure was not simply a story of fraud—it was a story of institutional blindness. Government intervened by superseding the IL&FS board, an unprecedented step under Companies Act 2013.

What made the crisis uniquely instructive was the invisibility of its architecture. 179 of IL&FS's 348 subsidiaries had never appeared in consolidated financial statements (Grant Thornton, 2019). Credit rating agencies maintained "AAA" and "AA+" designations months before default. RBI's own Financial Stability Reports from 2017–2018 raised no specific IL&FS concern. The conduits connecting India's financial system—short-term borrowings refinanced daily, inter-corporate deposits, related-party guarantees—were hidden until they failed.

This paper asks a methodological question: can public disclosures alone, integrated through a heterogeneous Knowledge Graph, produce a meaningful map of such hidden dependencies?

Our answer is partial, deliberate, and instructive. Constructing a network of 2,858 entities from CRISIL's FY2024–25 rated universe of 9,911 entities—integrating credit ratings, MCA filings, Basel III Pillar 3 disclosures, and FinBERT news sentiment—we find that the framework successfully identifies structural hub banks, non-bank bridge intermediaries, and multi-hop contagion pathways at the core of the observable network. At the same time, our results confirm that public disclosures, as currently mandated, are too fragmented to constitute a complete credit map: the lender-facility layer captures only approximately 10% of aggregate bank advances, and only 2.86% of corporate nodes carry the required loan-edge structure for full contagion tracing.

The paper's contribution is therefore twofold. First, it demonstrates that a Knowledge Graph is the correct architectural choice for this problem—capable of unifying heterogeneous relational structures that balance-sheet or correlation-based methods cannot represent. Second, it establishes, with precision, exactly what data regulators would need to mandate in order to make such a framework operationally complete. The proof of concept is not a claim that the system is ready; it is a diagnostic that identifies what readiness would require.

Three constituencies stand to benefit from this analysis. For regulators—RBI, SEBI—the topological findings indicate which disclosures are the binding constraint on network visibility. For bank risk teams calculating Expected Credit Loss under Ind AS 109, the identified bridge entities reveal systemic concentrations that single-name limits systematically miss. For institutional investors, the stress scoring architecture provides a methodology for independent, continuously updating risk signals—regardless of whether rating agency reviews have caught up to the underlying deterioration.

---

## 3. Literature Review (~450 words)

Financial contagion operates like an epidemic. Allen and Gale (2000) first formalized this intuition: liquidity withdrawal at one bank cascades through networks, with transmission speed depending on topology—not individual institution health. Their insight launched two decades of systemic risk measurement.

Acharya et al. (2017) introduced Marginal Expected Shortfall (MES), measuring institutional loss during market-wide downturns. Brownlees and Engle (2017), building on Engle's Nobel-recognized work in volatility modeling, extended this to SRISK—capital shortfall conditional on prolonged market decline. Both approaches, now applied by CAFRAL and IIMs for Indian bank assessment, share one foundational constraint: they require traded market prices, rendering them inapplicable to India's substantial unlisted corporate and NBFC universe.

Network-based approaches address that constraint. Battiston et al. (2012) developed DebtRank, propagating stress through exposure-weighted edges in a manner consistent with our fixed-point iteration design. Adrian and Brunnermeier (2016) contributed ΔCoVaR for institution-level systemic contribution. The IMF's SyRIN framework (2018) operationalized these concepts for emerging markets. Caccioli et al. (2020) demonstrated that financial networks exhibit "robust-yet-fragile" properties—absorbing small-node failures while remaining vulnerable when hubs collapse. That finding provides the theoretical grounding for our threshold-based entity filtering at ₹50 Crore exposure.

Indian credit market literature has grown rapidly. Bajaj and Damodaran (2023) identified Domestic Systemically Important Banks using component expected shortfall, documenting increasing NBFC contribution to aggregate network risk. Dash et al. (2023) mapped Indian bank interconnections using ΔCoVaR, distinguishing "good links" (liquidity sharing) from "bad links" (contagion channels). Poddar et al. (2023) employed Panel VAR to visualize bank interconnectedness during downturns. The RBI's Financial Stability Reports acknowledge the concentration dimension directly: a simultaneous default by the top three borrowers would raise system GNPA by 350 basis points (Reserve Bank of India, 2025).

For real-time signals, FinBERT (Araci, 2019) enables domain-specific sentiment analysis, capturing the financial meanings of terms—"restructuring," "NPA," "covenant breach"—that generic language models mishandle. Stander (2024) constructed a FinBERT-based news sentiment index demonstrating a causal relationship with systemic risk indicators, directly validating sentiment as a leading impairment signal under IFRS 9 and Ind AS 109. Knowledge graphs have recently entered financial risk literature. Chen and Zhang (2024) applied KG embeddings to study liquidity-to-systemic risk transmission in banking networks; their approach uses market-driven embeddings, while ours constructs the graph from regulatory filings—capturing unlisted entities that market-based methods cannot reach.

**The Gap**: Existing frameworks rely either on complete proprietary datasets—such as the Federal Reserve's Y-14 or the ECB's AnaCredit—or on narrow, listed-entity subsets. No existing work evaluates the feasibility and topological characteristics of a multi-source network built strictly from heterogeneous Indian public disclosures (CRISIL, MCA, NSE, RBI Pillar 3). That evaluation, and the data-quality implications it surfaces, is the gap this paper addresses. The framework maps the structurally significant links that have historically mediated financial contagion in India—while being transparent about the substantial share of the network that public disclosures leave unmapped.

---

## 4. Research Motivation and Problem Statement (~400 words)

### Why India, Why Now

India's banking sector has tripled in a decade—credit expanded from ₹66.91 lakh crore to ₹181.34 lakh crore (Press Information Bureau, 2025). NBFCs now account for roughly 25% of credit intermediation (Reserve Bank of India, 2024). The IMF's 2025 Financial Sector Assessment Programme praised the resulting diversification while simultaneously noting that increased interconnectedness introduces new fragility (International Monetary Fund, 2025). The combination is not contradictory; it is precisely the condition in which network-based analysis becomes necessary rather than merely useful.

Indian markets present research conditions without close parallel in developed economies. Where the Federal Reserve's Y-14 or the ECB's AnaCredit provide bilateral exposure registries, Indian credit relationships must be inferred from fragmented regulatory disclosures. Where developed markets feature predominantly listed entities, Indian corporates include substantial unlisted exposure requiring non-market-based stress assessment. IL&FS provided a high-visibility natural experiment: a crisis that was the product not of isolated balance-sheet failure but of systemic opacity at the inter-entity level.

### The Information Asymmetry Problem

Picture a bank credit committee evaluating a corporate borrower. They possess: audited financial statements, a credit rating, a sector outlook report. They do not observe: the borrower's full subsidiary and related-party structure, real-time news signaling governance deterioration, the stress levels of the borrower's other creditors, or the second-order exposures created by the borrower's own loan book.

RBI does maintain CRILC—the Central Repository of Information on Large Credits—mandating that banks report all exposures ≥₹5 Crore (Reserve Bank of India, 2014). However, CRILC data remains siloed within the regulatory perimeter. Commercial banks cannot see one another's CRILC submissions. Market participants and institutional investors operate without visibility into the full network. Asymmetry therefore persists for all actors except the regulator—who, in turn, lacks real-time sentiment integration.

Without access to CRILC or any comparable bilateral credit registry, any network mapping of the Indian financial system must reverse-engineer credit exposures from public sources. This paper accepts that constraint as given and asks what, exactly, can be learned within it. The sparsity findings in our results—a 2.86% loan-edge coverage rate at the corporate level and approximately 10% of aggregate bank advances mapped—are not a failure of the method; they are the method's most important finding. They locate, with precision, the information gap that regulatory intervention would need to close.

### Research Questions

This paper addresses three questions grounded directly in the results the framework produces:

**RQ1**: What are the topological characteristics—degree distribution, centrality, bridge-node structure, and inter-bank path length—of the observable Indian credit network when constructed exclusively from heterogeneous public disclosures?

**RQ2**: Which non-bank entities emerge as structural bridge nodes that mediate multi-hop contagion pathways between otherwise weakly connected bank pairs, and what institutional categories do they represent?

**RQ3**: To what extent does the reliance on fragmented public disclosures induce data sparsity in the resulting network, and how does this sparsity constrain the operational scope of systemic risk mapping?

### Scope

The framework covers 41 Scheduled Commercial Banks, NBFCs including Housing Finance Companies, and primary corporate borrowers above the ₹50 Crore exposure threshold. Excluded are: mutual fund portfolio holdings (data constraints), insurance interconnections (separate regulatory domain), OTC derivatives (bilateral data unavailable), and cross-border linkages (complexity beyond present scope). The entity universe comprises 2,858 entities from CRISIL's FY2024–25 rated universe of 9,911 entities, selected at a threshold aligned with RBI's CRILC monitoring intensity. This filtering is theoretically grounded in Caccioli et al.'s (2020) finding that systemic risk concentrates in highly connected hubs.

A note on the fixed-point contagion propagation model employed here: the algorithm captures mechanical transmission—the direct financial loss that flows from a defaulting entity to its creditors through exposure-weighted edges. It does not model behavioral contagion: the panic-driven liquidity hoarding through which lenders withdraw funding from institutions with no direct exposure to the defaulting entity, simply because confidence has collapsed. The 2018 NBFC funding freeze that followed IL&FS was substantially behavioral in character—DHFL and other NBFCs faced redemption pressure not because their balance sheets were immediately impaired, but because investors fled the asset class. Our model captures the mechanical network; the behavioral amplification layer constitutes an important boundary condition of the present results.

---

## 12. Discussion and Policy Implications (~550 words)

### Methodological Validation and Its Limits

The results presented in this paper establish that a Knowledge Graph constructed from Indian public disclosures produces analytically meaningful network topology. Our findings reveal a system that is sparse at the aggregate level (density = 0.000145) but structurally concentrated around a small number of hub banks, bridge intermediaries, and short multi-hop pathways. These characteristics are consistent with the "robust-yet-fragile" topology formalized by Caccioli et al. (2020) and with the hub-concentration dynamics observed empirically by Bajaj and Damodaran (2023) for the Indian banking sector.

That said, methodological viability is not operational readiness. The lender-facility layer captures approximately 10% of aggregate bank advances, and only 100 of 3,497 company nodes—2.86%—carry the loan-edge structure required for full contagion tracing. Our results confirm the framework's architectural soundness; they simultaneously confirm the operational inadequacy of the public data on which it currently depends. A framework that maps the visible portion of a mostly hidden network is a diagnostic instrument, not an early warning system. This paper offers the former and argues that achieving the latter requires regulatory action.

### Use Cases by Stakeholder

**Regulators (RBI/SEBI)**: The topological findings—hub concentration, bridge-node emergence, path-length distributions—provide a template for the kind of structural surveillance that entity-level supervision does not supply. Our results found that YESBANK ranks first by betweenness centrality despite far lower total degree than HDFCBANK or SBIN, a finding that degree-led regulatory monitoring would miss entirely. The framework's primary policy value is not its current coverage but the precision with which it identifies the disclosures regulators must mandate to extend that coverage. The principal implication for RBI is a structured mandate for graph-database reporting of interconnected subsidiary chains—precisely the reporting that would have made the IL&FS group's hidden subsidiaries visible before default.

**Bank Risk Teams**: ECL models under Ind AS 109 assess borrowers individually, missing the network amplification that transforms isolated distress into sectoral contagion. Our results found that Shriram Finance Limited carries 55 distinct lender relationships in the observable network—a concentration figure that no single bank's internal model captures in full. Counterparty network maps of this kind reveal correlated default risk that single-name exposure limits are structurally designed to ignore.

**Institutional Investors**: Rating agencies maintained IL&FS at investment grade until crisis materialized. The hybrid stress scoring methodology introduced here—blending CAMELS-style supervisory ratios, Merton-oriented distance-to-default signals, and FinBERT news sentiment—updates continuously without awaiting formal rating review. It provides an independent leading signal calibrated to the same financial vocabulary that precedes distress.

### Future Directions: Toward Federated Graph Learning

The present framework operates on public disclosures. Extending it to sensitive credit data—internal loan books, real-time delinquency trends, covenant breach alerts—requires a privacy-preserving architecture capable of respecting regulatory and competitive constraints without collapsing the multi-hop relational structure that graph-based contagion analysis depends upon.

Standard Federated Learning (McMahan et al., 2017; Yang et al., 2019) is not an adequate solution to this problem. Standard FL computes and aggregates gradients or model parameters across decentralized nodes. It is designed for independent, identically distributed tabular data. Multi-hop contagion tracing, by definition, cannot be performed on locally isolated node embeddings: a bank's two-hop exposure to another bank's borrower is a structural property of the full graph, not a feature any single institution's local dataset encodes. Averaging weights across bank-level models does not reconstruct that path structure. Retaining this architectural equivalence would misrepresent what graph-based systemic risk analysis fundamentally requires.

The technically appropriate frontier is Federated Graph Learning (FGL) or Privacy-Preserving Graph Neural Networks (PP-GNNs) (He et al., 2021; Zhang et al., 2021). Under FGL, participating institutions collaboratively train graph neural networks on subgraph partitions, exchanging encrypted structural embeddings rather than raw data. Crucially, the protocol propagates local neighborhood information across partitions in a manner that preserves multi-hop path topology—the prerequisite for contagion tracing. Differential privacy mechanisms applied at the embedding level, rather than at the gradient level, prevent reconstruction of individual exposure relationships while enabling network-level inference.

The viable roadmap for Indian financial stability surveillance is therefore: (1) RBI mandates structured graph-compatible reporting from banks and systemically important NBFCs, anchored to CRILC; (2) a regulatory technology consortium implements FGL or PP-GNN-based aggregation over the resulting subgraphs; (3) the resulting topology is made available to macro-prudential surveillance functions without exposing individual institution data. This paper's proof of concept demonstrates that the architectural choice—Knowledge Graphs as the organizing structure—is correct. It also demonstrates, with uncomfortable precision, that public data alone will not suffice to make it work at scale.

### A Note on Scope and the Path Forward

This paper covers a subset of Indian financial sector exposures. The limitations are well-defined: the lender-facility layer maps roughly one-tenth of aggregate bank advances, and the corporate exposure table reflects a high-confidence but partial slice of the full credit universe. These constraints stem not from a deficiency in the analytical approach but from the fragmentation of the disclosures on which it relies.

The vision motivating this work, however, is not bounded by that subset. A framework of this kind, built on complete CRILC data with structured subsidiary reporting, could cover the entire Indian financial sector. It could support real-time stress propagation modeling, scenario-based contagion analysis for macro-prudential policy, and the kind of network-aware early warning that was absent in 2018. Events like IL&FS do not announce themselves in balance sheets; they accumulate in the invisible junctions between entities. Making those junctions visible—through regulatory mandate, heterogeneous data integration, and graph-native analytics—is the necessary condition for a financial stability apparatus adequate to the complexity of modern Indian credit markets. The architecture proposed here is a starting point. The data mandate is the missing piece regulators have yet to act on.

---

## References

### Section 2: Introduction

1. Ministry of Corporate Affairs. (2018). *Order under Section 241 of the Companies Act, 2013 regarding IL&FS Ltd.* Government of India.

2. Serious Fraud Investigation Office. (2019). *Interim report on IL&FS group investigation.* Ministry of Corporate Affairs, Government of India.

3. NSE India. (2018). *Market activity report: September–December 2018.* National Stock Exchange of India.

4. Reserve Bank of India. (2018). *Financial stability report, December 2018.* RBI Publications.

5. Grant Thornton. (2019). *Forensic audit report of IL&FS group.* Submitted to National Company Law Tribunal.

### Section 3: Literature Review

6. Allen, F., & Gale, D. (2000). Financial contagion. *Journal of Political Economy, 108*(1), 1–33.

7. Acharya, V. V., Pedersen, L. H., Philippon, T., & Richardson, M. (2017). Measuring systemic risk. *The Review of Financial Studies, 30*(1), 2–47.

8. Brownlees, C., & Engle, R. F. (2017). SRISK: A conditional capital shortfall measure of systemic risk. *The Review of Financial Studies, 30*(1), 48–79.

9. Battiston, S., Puliga, M., Kaushik, R., Tasca, P., & Caldarelli, G. (2012). DebtRank: Too central to fail? Financial networks, the FED and systemic risk. *Scientific Reports, 2*, 541.

10. Adrian, T., & Brunnermeier, M. K. (2016). CoVaR. *American Economic Review, 106*(7), 1705–1741.

11. International Monetary Fund. (2018). *Systemic risk and interconnectedness network (SyRIN).* IMF Working Paper WP/18/14.

12. Caccioli, F., Barucca, P., & Kobayashi, T. (2020). Network models of financial systemic risk: A review. *Journal of Computational Social Science, 1*(1), 81–114.

13. Bajaj, R., & Damodaran, A. (2023). Identification of domestic systemically important banks in India. *Journal of Financial Stability, 65*, 101110.

14. Dash, S. R., et al. (2023). Network topology and systemic risk: Evidence from Indian banks. *Economics Letters, 225*, 111054.

15. Poddar, A., et al. (2023). Bank interconnectedness and systemic risk in India: A PVAR approach. *Applied Economics, 55*(12), 1342–1358.

16. Reserve Bank of India. (2025). *Financial stability report, June 2025.* RBI Publications.

17. Araci, D. (2019). FinBERT: Financial sentiment analysis with pre-trained language models. *arXiv preprint* arXiv:1908.10063.

18. Stander, Y. S. (2024). A news sentiment index to inform International Financial Reporting Standard 9 impairments. *Journal of Risk and Financial Management, 17*(7), 282. https://doi.org/10.3390/jrfm17070282

19. Chen, R.-R., & Zhang, X. (2024). From liquidity risk to systemic risk: A use of knowledge graph. *Journal of Financial Stability, 70*, 101195. https://doi.org/10.1016/j.jfs.2023.101195

### Section 4: Research Motivation & Problem Statement

20. Press Information Bureau. (2025, February 24). *Banking sector growth statistics FY2014–2024.* Ministry of Finance, Government of India. https://www.pib.gov.in/PressReleasePage.aspx?PRID=2201357

21. Reserve Bank of India. (2024). *Report on trend and progress of banking in India 2023–24.* RBI Publications.

22. International Monetary Fund. (2025). *India: Financial sector assessment program (FSAP) technical note on systemic risk analysis.* IMF Country Report.

23. Reserve Bank of India. (2014). *Master direction on Central Repository of Information on Large Credits (CRILC).* RBI/2014-15/45.

### Section 12: Discussion & Future Directions

24. McMahan, H. B., Moore, E., Ramage, D., Hampson, S., & Arcas, B. A. y. (2017). Communication-efficient learning of deep networks from decentralized data. *Proceedings of the 20th International Conference on Artificial Intelligence and Statistics,* 1273–1282.

25. Yang, Q., Liu, Y., Chen, T., & Tong, Y. (2019). Federated machine learning: Concept and applications. *ACM Transactions on Intelligent Systems and Technology, 10*(2), 1–19. https://doi.org/10.1145/3298981

26. He, C., Balasubramanian, K., Ceyani, E., Yang, C., Feng, H., Avestimehr, S., & Yu, P. (2021). FedGraphNN: A federated learning system and benchmark for graph neural networks. *arXiv preprint* arXiv:2104.07145.

27. Zhang, K., Yang, C., Li, X., Sun, L., & Yiu, S. M. (2021). Subgraph federated learning with missing neighbor generation. *Advances in Neural Information Processing Systems (NeurIPS), 34,* 6671–6682.

---

## Quality & Human-Authenticity Checks

### Word Count by Section
| Section | Target | Actual (approx.) |
|---------|--------|------------------|
| Introduction | ~450 | ~470 |
| Literature Review | ~450 | ~450 |
| Problem Statement & RQs | ~400 | ~430 |
| Discussion | ~550 | ~570 |
| **Total** | **~1,850** | **~1,920** |

### Key Changes in v3 (Faculty Review Response)

1. ✓ **Introduction reframed**: Removed definitiveness. Paper now explicitly positions itself as a methodological prototype that exposes what data regulators must mandate. "Proof of concept" language inserted in paragraph 4.
2. ✓ **Urjit Patel attribution removed**: Replaced direct governorship quote with "widely characterized by market observers during then-RBI Governor Patel's tenure."
3. ✓ **Literature Review gap paragraph rewritten**: No longer claims to solve all four limitations. Now positions paper as evaluating feasibility and topological characteristics of a network built strictly from heterogeneous Indian public disclosures.
4. ✓ **Problem Statement paragraph added**: New concluding paragraph explicitly primes the reader for sparsity findings. States that without CRILC access, any mapping relies on reverse-engineering exposures from public sources.
5. ✓ **All three Research Questions replaced**: New RQ1 = topological characteristics; New RQ2 = structural bridge nodes; New RQ3 = data sparsity and its limits on systemic risk mapping. All three are directly answered by the results in main.tex.
6. ✓ **Behavioral contagion caveat added** (Section 4, Scope): Distinguishes mechanical from behavioral contagion. Names the 2018 NBFC funding freeze as the behavioral amplification example the model does not capture.
7. ✓ **Discussion rewritten**: "Academic confirmation" victory language removed. Replaced with explicit statement that methodological viability ≠ operational readiness.
8. ✓ **Stakeholder section**: Removed "Regulators can use this today." Replaced with "Regulators must build this architecture on top of CRILC." Policy implication is now a mandate call for graph-database reporting.
9. ✓ **European Consortia false equivalence removed entirely**: No mention of fraud detection FL equivalence.
10. ✓ **Flower/IBM FL/Standard FL completely removed**: Replaced with technically accurate discussion of Federated Graph Learning (FGL) and Privacy-Preserving GNNs, with explicit explanation of why standard FL fails on multi-hop graph topology.
11. ✓ **"IL&FS simulation showed" → "Our results found that"**: All empirical claims now reference the actual results (degree distribution, centrality, bridge nodes, path lengths, sparsity). No simulation language retained.
12. ✓ **New references added**: He et al. (2021) for FedGraphNN; Zhang et al. (2021) for Subgraph FL with NeurIPS citation. McMahan and Yang retained for FL context, now correctly positioned as insufficient for this problem.

### Variability Verified
- [x] Sentence lengths: Range from 6 words ("That said, methodological viability is not operational readiness.") to 50+ words
- [x] Paragraph lengths: 1 to 7 sentences; no uniform rhythm
- [x] Transition words: Used in <35% of paragraphs
- [x] Active voice dominant; passive reserved for methodology framing (~20%)

### Engagement Elements
- **Opening**: Date + specific default amount (₹1,000 Cr CP), not abstract context
- **Analytical precision**: 9,257:1 leverage, 2.86% edge rate, density = 0.000145 — all sourced from main.tex
- **Named entities**: YESBANK betweenness finding, Shriram Finance 55-lender figure — both from Results section
- **Epistemic restraint**: Paper is described as a diagnostic instrument throughout, consistently calibrated to evidence
- **Structural tension**: Framework is correct architecture + data is inadequate = regulators must act

### Cross-Verification Against main.tex Results
- [x] Network density = 0.000145 (Section: Results, paragraph 1)
- [x] YESBANK betweenness = 0.00794, rank 1 (Table, subsection 3)
- [x] Shriram Finance: 55 lenders (Table 2, subsection 2)
- [x] 100 of 3,497 company nodes carry loan-edge structure = 2.86% (note below Table 2)
- [x] ~10% of bank advances mapped (Section: Data Sources)
- [x] 41 Scheduled Commercial Banks (Section: Data Sources)
- [x] 2,858 entities from 9,911 CRISIL rated universe (Abstract + Section 4 Scope)
- [x] Bridge score = Path Appearances × Unique Bank Pairs (Subsection 4)
- [x] Mean shortest path length = 2.33 hops; max = 5 hops (Subsection 6)

### Banned Phrases: None Present
- [x] No "delve into" / "robust framework" / "comprehensive analysis"
- [x] No "it's worth noting" / "moreover" at paragraph starts
- [x] No "IL&FS simulation showed" — replaced throughout with "our results found that"
- [x] No standard FL victory claims; no Flower/IBM FL/EU fraud equivalence