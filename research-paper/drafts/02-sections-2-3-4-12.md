# Academic Paper Draft: Sections 2, 3, 4, 12

**Paper Title**: A Contagion Mapping Framework for Eminent Systematic Risks in Indian Financial Credit Sector

**Formatting**: Times New Roman 12pt | 1.5 line spacing | APA citations | Anonymized

---

## 2. Introduction

India's banking sector has tripled in ten years—credit expanded from ₹66.91 lakh crore to ₹181.34 lakh crore between 2014 and 2024 (Press Information Bureau, 2025). NBFCs grew alongside, filling retail and infrastructure lending gaps. The IMF's 2025 Financial Sector Assessment Program noted this favorably: the system had become "more diverse and interconnected," and institutions were "generally resilient to severe macrofinancial solvency and liquidity shocks."

But resilience is not immunity.

On September 21, 2018, IL&FS—a shadow bank with ₹91,000 Crores debt across 348 subsidiaries built on just ₹9.83 Crores equity—defaulted on commercial paper. Rating agencies that had maintained investment-grade ratings just months prior scrambled to downgrade to junk status within weeks. The episode exposed what network theorists had long warned: individual institution health tells us little about systemic fragility. When interconnected pipes fail, the entire system seizes.

This paper introduces a Knowledge Graph-based framework for mapping contagion pathways in Indian financial networks. We construct a unified network of 2,858 systemically important entities with exposures exceeding ₹36.73 lakh crore, integrating CRISIL credit ratings, MCA filings for subsidiary and RPT data, Basel III Pillar 3 disclosures, and real-time news sentiment via FinBERT. The framework enables scenario simulation where users model hypothetical defaults and trace second and third-order effects before they occur.

The framework serves three constituencies. For regulators—RBI, SEBI—it offers an early warning system complementing entity-level supervision. For bank management calculating Expected Credit Loss under Ind AS 109, our network maps reveal counterparty exposures internal models miss. For institutional investors, stress scores provide an independent signal to supplement rating agency assessments.

The remainder of this paper proceeds as follows. Section 3 reviews literature on systemic risk and network contagion. Section 4 articulates research motivation and problem statement. Sections 5-9 detail data sources, framework architecture, stress scoring, graph construction, and contagion propagation. Section 10 presents empirical results. Section 11 validates via IL&FS case study. Section 12 discusses policy implications. Section 13 acknowledges limitations. Section 14 concludes.

---

## 3. Literature Review

### 3.1 Systemic Risk Theory

Systemic risk literature originates with Allen and Gale (2000), who demonstrated that liquidity withdrawal at one bank can cascade through entire banking systems depending on network topology. Their model showed that complete networks with symmetric connections absorb shocks better than incomplete networks where concentration creates fragility. This insight—that structure matters as much as individual health—forms the theoretical foundation for network-based risk assessment.

Acharya, Pedersen, Philippon, and Richardson (2017) formalized systemic risk measurement through Marginal Expected Shortfall (MES) and Systemic Expected Shortfall (SES). MES captures an institution's expected loss during market-wide downturns; SES extends this to system-level capital shortfall contribution. Their framework, developed by a former RBI Deputy Governor, provides mathematical rigor for identifying systemically important institutions. Brownlees and Engle (2017), including a Nobel laureate, introduced SRISK—capital shortfall conditional on prolonged market decline. SRISK is now used by CAFRAL and IIMs to assess Indian bank and NBFC vulnerability.

Battiston et al. (2012) introduced DebtRank, measuring how default at a single node propagates stress to connected institutions through exposure-weighted links. Adrian and Brunnermeier (2016) developed ΔCoVaR, capturing individual institution contribution to system-wide Value-at-Risk. Both approaches require network topology data that traditional entity-focused analysis ignores.

### 3.2 Network Contagion Models

The IMF's SyRIN framework (2018) introduced "Portfolio of Entities" approaches using the CIMDO method to infer multivariate densities of distress. We adapt SyRIN's multi-entity perspective to real-time Indian context, extending it with sentiment integration absent from the original framework.

Caccioli et al. (2020) demonstrated that systemic risk concentrates in highly-connected hubs rather than distributing across all nodes—financial networks exhibit "robust-yet-fragile" properties, absorbing random small-node failures while being vulnerable to hub failures. This finding informs our ₹50 Crore threshold: filtering peripheral nodes retains systemic weight while reducing complexity.

Epidemiological models, particularly SEIR (Susceptible-Exposed-Infected-Recovered), have been adapted for financial contagion simulation. These "financial virus" models treat stress propagation analogously to disease transmission through network links. Our contagion module adapts this approach for credit network topology.

### 3.3 Indian Credit Market Studies

Bajaj and Damodaran (2023) identified Domestic Systemically Important Banks (D-SIBs) in India using component expected shortfall. Critically, they mapped increasing NBFC contribution to aggregate network risk—validating our focus on the NBFC-Bank nexus. Dash et al. (2023) built network topology using ΔCoVaR for listed Indian banks, differentiating "good links" (liquidity sharing) from "bad links" (contagion channels) during the NPA crisis. Poddar et al. (2023) employed Panel Vector Autoregression to visualize bank interconnectedness, providing empirical evidence that competition exacerbates systemic risk spillovers during downturns.

Narayan and Kumar (2024) examined macroprudential policy across G20 nations including India, establishing regulatory context for RBI's approach. Their work underscores that Indian authorities recognize interconnectedness risks but lack real-time monitoring tools.

The RBI's Financial Stability Reports (2018-2025) and stress test results (2025) provide official acknowledgment: default by top three borrowers of any bank would raise system-level GNPA by 350 basis points, reducing CRAR and CET1 ratios by 90 and 80 basis points respectively.

### 3.4 NLP in Finance

FinBERT (Araci, 2019) pre-trained on financial corpus enables domain-specific sentiment analysis that generic models miss. Terms like "restructuring," "NPA," and "default" carry precise meanings in financial text that FinBERT captures. Recent work integrating NLP with knowledge graphs for financial networks (MDPI, 2024) demonstrates how unstructured news data can enhance structured relationship mapping—a methodology we operationalize.

### 3.5 Research Gap

Despite these advances, no existing framework integrates: (1) network mapping of lending, shareholding, and subsidiary relationships; (2) real-time sentiment analysis on entity-specific news; (3) credit fundamentals from rating agencies; and (4) scenario simulation for contagion propagation—into a unified operational system for Indian markets. Market-dependent measures (MES, SRISK) cannot assess unlisted entities. Static network models lack forward-looking sentiment signals. Entity-level stress tests miss network amplification. Rating agency assessments lag actual distress by months, as IL&FS demonstrated.

---

## 4. Research Motivation and Problem Statement

### 4.1 Why India

India's financial sector has undergone structural transformation since 2014. Credit to commercial sector nearly tripled; NBFCs emerged as critical providers accounting for roughly 25% of credit intermediation by 2024. The IMF's 2025 FSAP characterized this as making the system "more diverse and interconnected"—diversity reducing concentration risk, but interconnectedness introducing new contagion vulnerabilities.

Indian markets present unique research opportunities. Unlike developed markets where bilateral exposure data exists, Indian credit relationships must be inferred from regulatory disclosures. Unlike markets dominated by listed entities, Indian corporates include substantial unlisted exposure requiring non-market-based stress assessment. The IL&FS episode provided a natural experiment validating network-based concerns.

### 4.2 Why Credit Sector

Credit relationships create binding exposures: when borrowers default, lenders absorb losses. Unlike equity holdings where exposure ends at market value, credit exposures carry covenant obligations, collateral complications, and recovery uncertainty. The RBI's 2025 stress test quantifies this: concentrated credit defaults propagate to capital ratios rapidly.

The credit sector also possesses uniquely rich data. Banks must disclose borrower exposures through Basel III Pillar 3 requirements. Companies must report Related Party Transactions under Section 186(4) of Companies Act. Rating agencies publish continuous assessments. This data ecosystem enables network construction impossible in other sectors.

### 4.3 The Information Asymmetry Problem

Why do crises surprise regulators and investors? Consider information available to a bank's credit committee evaluating corporate borrowers: financial statements, credit rating, sector outlook. They do not observe the borrower's full subsidiary structure, real-time sentiment shifts signaling governance concerns, other creditors' stress levels, or second-order exposures through borrower's own loan book.

Regulators face analogous limitations. RBI supervises banks; SEBI oversees mutual funds and securities markets; MCA collects corporate filings. Each optimizes for mandate. None possesses unified network view revealing how NBFC stress propagates to banks through loan exposures, to mutual funds through commercial paper, to corporates through credit line reductions.

[COMMENT: RBI does have CRILC—Central Repository of Information on Large Credits—mandating banks report all exposures ≥₹5 Crore. But CRILC data is not available to market participants. Banks cannot see other banks' CRILC data. Hence the asymmetry persists for non-regulatory actors. Consider mentioning this nuance if relevant.]

### 4.4 Research Questions

This paper addresses three interrelated questions:

**RQ1**: Can a knowledge graph architecture effectively represent multi-layer relationships—lending, shareholding, subsidiary ownership, related-party transactions—characterizing Indian financial networks?

**RQ2**: Does integrating sentiment analysis via FinBERT with historical credit metrics and network position improve early warning capability relative to credit ratings alone?

**RQ3**: Can fixed-point contagion propagation algorithms, applied to constructed networks, replicate observed stress patterns from historical crises—specifically IL&FS 2018?

### 4.5 Scope and Boundaries

Our framework focuses on Indian credit sector: Scheduled Commercial Banks, NBFCs including Housing Finance Companies, and primary corporate borrowers. We exclude mutual fund portfolio holdings (data availability constraints), insurance sector interconnections (separate regulatory domain), OTC derivatives exposures (bilateral data not publicly available), and cross-border linkages (complexity beyond present scope).

The entity universe comprises 2,858 entities with exposures exceeding ₹50 Crores—a threshold mirroring RBI's CRILC monitoring intensity and supported by network theory showing systemic risk concentrates in hubs. This captures ₹36.73 lakh crore in total network exposure, approximately 97% of systemic weight while reducing complexity by 70%.

---

## 12. Discussion and Policy Implications

### 12.1 For Regulators (RBI/SEBI)

Our framework offers three capabilities current regulatory tools lack.

First, real-time network visibility. While RBI's CRILC captures large credit exposures ≥₹5 Crore, the data remains siloed within regulatory systems. Market participants—including banks assessing counterparty risk—cannot access consolidated network views. Our framework demonstrates that publicly available data (Pillar 3 disclosures, MCA filings, RPT reports) can construct meaningful network topology without requiring privileged regulatory data sharing.

Second, forward-looking stress signals. RBI's annual stress tests evaluate banks against macroeconomic scenarios using point-in-time data. Our framework integrates FinBERT sentiment analysis capturing governance news, rating watch signals, and market concerns that precede formal distress. The IL&FS simulation demonstrates detection of elevated risk 18-24 months before default—a window for regulatory intervention.

Third, scenario simulation capability. "What-if" analysis enables regulators to model hypothetical defaults before they occur. Rather than post-crisis forensics, regulators can identify contagion pathways pre-emptively. The framework's fixed-point iteration traces second and third-order effects that entity-level analysis misses.

[COMMENT: If you have specific RBI mandate citations or SEBI circular numbers regarding systemic risk monitoring, add them here to strengthen regulatory relevance.]

### 12.2 For Bank Management

For banks calculating Expected Credit Loss (ECL) under Ind AS 109, our framework addresses a critical gap: counterparty exposure beyond direct lending relationships. ECL models typically assess borrower credit risk individually. They do not capture that a borrower's other creditors' stress affects their own recovery probability—the network effect.

Our 97/70 rule—retaining 97% systemic exposure while reducing network complexity by 70%—provides computationally tractable input for stress testing. Banks can incorporate network position metrics into internal credit models: entities with high centrality in stressed sectors merit higher loss provisions regardless of individual rating.

The framework also enables concentration monitoring beyond single-name limits. Regulators cap individual borrower exposure at percentage of capital. But exposure to multiple borrowers connected through common subsidiaries or sectors creates correlated default risk that single-name limits miss. Graph queries identifying such clusters augment existing concentration monitoring.

### 12.3 For Institutional Investors

Rating agency assessments exhibit three limitations our framework addresses.

First, lag. IL&FS maintained investment grade until months before default. Our hybrid stress score—combining historical credit metrics with real-time sentiment—updates continuously. When governance news turns negative, stress scores adjust without waiting for formal rating review.

Second, conflict. The issuer-pays model creates incentives to maintain ratings. Our stress scores derive from public data without commercial relationship to rated entities.

Third, entity focus. Rating agencies assess entities individually without network context. Our graph-based approach reveals that a counterparty's stress—even if currently investment-grade—matters when they are connected to distressed entities through exposure chains.

Institutional investors can use framework outputs as independent signal: when our stress scores diverge from rating agency grades, further due diligence is warranted.

### 12.4 Framework Scalability

The architecture—MongoDB for document storage, Neo4j for graph queries—scales horizontally. Entity count can expand from 2,858 to full CRISIL universe (9,900+) with proportional compute increase. The ₹50 Crore threshold is configurable: stricter thresholds for faster computation, relaxed thresholds for broader coverage.

Real-time integration is architecturally feasible. News sentiment already updates continuously. Extending to streaming regulatory disclosures (as banks move toward more frequent reporting) requires data pipeline expansion without algorithm changes.

Cross-border extension would require mapping international credit relationships—data that exists for major multinational banks but requires additional data partnerships. The Knowledge Graph schema accommodates foreign entity nodes and cross-border edges; data availability is the constraint, not architecture.

### 12.5 Regulatory Adoption Considerations

For RBI to operationalize similar frameworks, three enabling conditions apply.

First, data standardization. Pillar 3 disclosures vary across banks in format and granularity. Standardized machine-readable formats would reduce ingestion complexity substantially.

Second, entity resolution infrastructure. Our CIN-based approach works because Companies Act mandates Corporate Identity Numbers. Extending to unregistered entities or trusts requires alternative identifiers or fuzzy matching that introduces uncertainty.

Third, model governance. Any regulatory tool requires validation, backtesting, and governance frameworks. Our IL&FS case study provides initial validation; production deployment would require ongoing model monitoring against actual defaults.

[COMMENT: If there are specific upcoming RBI initiatives or consultation papers on systemic risk monitoring technology, referencing them would strengthen relevance. Otherwise, this section stands as general policy discussion.]