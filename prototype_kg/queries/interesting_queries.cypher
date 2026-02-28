// ============================================================================
// prototype_kg/queries/interesting_queries.cypher
//
// Interesting analytical queries on the Financial Knowledge Graph.
// Run these in AuraDB Browser, or via run_queries.py.
//
// Node labels   : Bank, Company, Shareholder, Industry, PrioritySector
// Relationships : LENDS_TO, RELATED_PARTY, SHAREHOLDER_OF,
//                 SUBSIDIARY_OF, BELONGS_TO, PRIORITY_EXPOSURE
// ============================================================================


// ── Q1 ── Common Shareholders Across Banks ──────────────────────────────────
//
// Who holds a stake in MORE THAN ONE of the three target banks?
// These are cross-bank ownership nodes — could be LIC, FIIs, mutual funds, etc.
// Great for spotting concentrated public / institutional ownership.

MATCH (s)-[:SHAREHOLDER_OF]->(b:Bank)
WITH s, collect(DISTINCT b.bankSymbol) AS banks, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
RETURN
    labels(s)[0]                             AS entityType,
    CASE
        WHEN s:Shareholder THEN s.shareholderName
        WHEN s:Bank        THEN s.bankSymbol
        WHEN s:Company     THEN coalesce(s.mcaName, s.crisilName)
    END                                      AS entityName,
    bankCount,
    banks
ORDER BY bankCount DESC, entityName;


// ── Q2 ── Cross-Bank Direct Ownership ────────────────────────────────────────
//
// Which bank directly holds shares in another bank?
// Bank A → SHAREHOLDER_OF → Bank B  (e.g., if SBI holds a stake in HDFC)

MATCH (b1:Bank)-[r:SHAREHOLDER_OF]->(b2:Bank)
RETURN
    b1.bankSymbol                   AS ownerBank,
    b2.bankSymbol                   AS targetBank,
    r.shareholdingPercentage        AS stakePct,
    r.numberOfShares                AS shares,
    r.source                        AS source
ORDER BY r.shareholdingPercentage DESC;


// ── Q3 ── Dual-Bank Borrowers (concentrated credit risk) ─────────────────────
//
// Companies that borrow from TWO OR MORE of the target banks simultaneously.
// The combined exposure shows where credit risk is truly concentrated.

MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
WITH c, collect(b.bankSymbol) AS lenders, sum(r.totalAmount) AS combinedExposure
WHERE size(lenders) > 1
RETURN
    coalesce(c.mcaName, c.crisilName)   AS companyName,
    c.cin                               AS cin,
    c.industryName                      AS industry,
    lenders,
    size(lenders)                       AS numBanks,
    round(combinedExposure, 2)          AS totalExposureINRCr
ORDER BY numBanks DESC, totalExposureINRCr DESC
LIMIT 50;


// ── Q4 ── Triple-Bank Borrowers (highest concentration) ──────────────────────
//
// The riskiest set: companies with credit facilities from ALL THREE target banks.

MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
WITH c, collect(b.bankSymbol) AS lenders, sum(r.totalAmount) AS combinedExposure
WHERE size(lenders) >= 3
RETURN
    coalesce(c.mcaName, c.crisilName)   AS companyName,
    c.cin                               AS cin,
    c.industryName                      AS industry,
    lenders,
    round(combinedExposure, 2)          AS totalExposureINRCr
ORDER BY totalExposureINRCr DESC;


// ── Q5 ── Bank Loans to Related Parties of ANOTHER Bank ───────────────────────
//
// Bank A lends to a company that is a Related Party of Bank B.
// Cross-bank RPT exposure — a hidden systemic linkage.
// Pattern: (bankA)-[:LENDS_TO]->(c)<-[:RELATED_PARTY]-(bankB)  where bankA ≠ bankB

MATCH (bankA:Bank)-[l:LENDS_TO]->(c:Company)<-[rpt:RELATED_PARTY]-(bankB:Bank)
WHERE bankA <> bankB
RETURN
    bankA.bankSymbol                     AS lendingBank,
    bankB.bankSymbol                     AS rptBank,
    coalesce(c.mcaName, c.crisilName)    AS companyName,
    c.cin                                AS cin,
    rpt.relationship                     AS rptRelationship,
    rpt.transactionType                  AS rptTransactionType,
    round(l.totalAmount, 2)              AS loanAmountINRCr
ORDER BY loanAmountINRCr DESC;


// ── Q6 ── Bank Lending to ITS OWN Subsidiaries ───────────────────────────────
//
// Intra-group exposure: Bank X lends to a company that is a subsidiary of Bank X.
// Key risk: self-dealing within a banking conglomerate.

MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:SUBSIDIARY_OF]->(b)
RETURN
    b.bankSymbol                         AS bank,
    coalesce(c.mcaName, c.crisilName)    AS subsidiary,
    c.cin                                AS cin,
    round(l.totalAmount, 2)              AS loanAmountINRCr,
    l.facilityTypes                      AS facilityTypes
ORDER BY bank, loanAmountINRCr DESC;


// ── Q7 ── 2-Hop Exposure: Bank → Subsidiary → Borrower From Another Bank ─────
//
// Bank A's subsidiary is also a borrower of Bank B.
// This creates indirect exposure between the two banks via the subsidiary.
// Pattern: (bankA)<-[:SUBSIDIARY_OF]-(sub)-[:LENDS_TO is reversed]
//           i.e. (bankB)-[:LENDS_TO]->(sub)-[:SUBSIDIARY_OF]->(bankA)

MATCH (bankB:Bank)-[l:LENDS_TO]->(sub:Company)-[:SUBSIDIARY_OF]->(bankA:Bank)
WHERE bankA <> bankB
RETURN
    bankA.bankSymbol                     AS parentBank,
    bankB.bankSymbol                     AS lendingBank,
    coalesce(sub.mcaName, sub.crisilName) AS subsidiary,
    sub.cin                              AS cin,
    round(l.totalAmount, 2)              AS exposureINRCr
ORDER BY exposureINRCr DESC;


// ── Q8 ── 2-Hop Exposure: Bank → Company → Shareholder of Another Bank ────────
//
// Bank A lends to Company X, and Company X is also a shareholder of Bank B.
// Bank B's health is partially tied to Company X's solvency,
// and Bank A holds credit risk on that same Company X.

MATCH (bankA:Bank)-[l:LENDS_TO]->(c:Company)-[s:SHAREHOLDER_OF]->(bankB:Bank)
WHERE bankA <> bankB
RETURN
    bankA.bankSymbol                     AS lendingBank,
    bankB.bankSymbol                     AS bankWhereCompanyHoldsStake,
    coalesce(c.mcaName, c.crisilName)    AS company,
    c.cin                                AS cin,
    round(l.totalAmount, 2)              AS creditExposureINRCr,
    round(s.shareholdingPercentage, 4)   AS stakeInBankB_Pct
ORDER BY creditExposureINRCr DESC;


// ── Q9 ── 3-Hop Exposure: Bank A → Company → Related Party → Bank B ──────────
//
// Bank A lends to Company X. Company X has a Related Party transaction with
// Bank B. This 3-hop chain links two banks through a corporate intermediary.

MATCH (bankA:Bank)-[:LENDS_TO]->(c:Company)
MATCH (bankB:Bank)-[rpt:RELATED_PARTY]->(c)
WHERE bankA <> bankB
WITH bankA, bankB, c, collect(DISTINCT rpt.transactionType) AS rptTypes, count(rpt) AS rptCount
RETURN
    bankA.bankSymbol                     AS lendingBank,
    bankB.bankSymbol                     AS rptCounterpartyBank,
    coalesce(c.mcaName, c.crisilName)    AS bridgeCompany,
    c.cin                                AS cin,
    rptCount,
    rptTypes
ORDER BY rptCount DESC;


// ── Q10 ── Shareholders Who Own Both a Bank AND a Company Borrowing From That Bank
//
// A shareholder S holds stake in Bank B, and also holds stake in Company C
// which borrows from Bank B. Potential conflict of interest / circular incentive.

MATCH (s)-[:SHAREHOLDER_OF]->(b:Bank)
MATCH (b)-[:LENDS_TO]->(c:Company)
MATCH (s)-[:SHAREHOLDER_OF]->(c)
RETURN
    CASE
        WHEN s:Shareholder THEN s.shareholderName
        WHEN s:Bank        THEN s.bankSymbol
        WHEN s:Company     THEN coalesce(s.mcaName, s.crisilName)
    END                                  AS shareholder,
    labels(s)[0]                         AS shareholderType,
    b.bankSymbol                         AS bank,
    coalesce(c.mcaName, c.crisilName)    AS borrowingCompany,
    c.cin                                AS cin
ORDER BY shareholder, bank;


// ── Q11 ── Industry Concentration in Each Bank's Loan Portfolio ───────────────
//
// For each bank, which industry takes the largest share of CRISIL-tracked loans?
// Helps identify sector concentration risk per bank.

MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(i:Industry)
WITH b.bankSymbol AS bank, i.industryName AS industry, sum(l.totalAmount) AS sectorExposure
WITH bank, industry, round(sectorExposure, 2) AS sectorExposure
ORDER BY bank, sectorExposure DESC
WITH bank, collect({industry: industry, exposure: sectorExposure}) AS byIndustry
RETURN
    bank,
    byIndustry[0].industry              AS topIndustry,
    byIndustry[0].exposure              AS topExposureINRCr,
    [x IN byIndustry[0..5] | x.industry] AS top5Industries,
    reduce(total = 0.0, x IN byIndustry | total + x.exposure) AS totalTrackedExposureINRCr;


// ── Q12 ── Full Industry Breakdown Per Bank (for bar-chart) ───────────────────
//
// Tabular output: bank, industry, total exposure — feed into a grouped bar chart.

MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(i:Industry)
RETURN
    b.bankSymbol                         AS bank,
    i.industryName                       AS industry,
    round(sum(l.totalAmount), 2)         AS totalExposureINRCr,
    count(DISTINCT c)                    AS numCompanies
ORDER BY bank, totalExposureINRCr DESC;


// ── Q13 ── Priority Sector Exposure Comparison Across Banks ───────────────────
//
// Side-by-side: how much does each bank lend to each RBI priority sector?

MATCH (b:Bank)-[r:PRIORITY_EXPOSURE]->(p:PrioritySector)
RETURN
    p.rbiCategoryLabel                   AS prioritySector,
    b.bankSymbol                         AS bank,
    round(r.outstandingAmount, 2)        AS outstandingINRCr
ORDER BY prioritySector, outstandingINRCr DESC;


// ── Q14 ── Bank-to-Bank RPT Network ──────────────────────────────────────────
//
// Direct Related Party Transactions between the three banks themselves.
// Reveals bilateral contra-party exposures declared in integrated filings.

MATCH (b1:Bank)-[r:RELATED_PARTY]->(b2:Bank)
RETURN
    b1.bankSymbol                        AS fromBank,
    b2.bankSymbol                        AS toBank,
    r.relationship                       AS relationship,
    r.transactionType                    AS transactionType,
    r.reportingPeriod                    AS period,
    r.actualAmount                       AS amountINRCr
ORDER BY b1.bankSymbol, amountINRCr DESC;


// ── Q15 ── Companies That Are Both RPT Counterparty and Borrower ──────────────
//
// A company that has an RPT relationship with Bank A AND borrows from Bank B.
// Or even borrows from Bank A itself — double exposure in different contract types.

MATCH (bankRPT:Bank)-[:RELATED_PARTY]->(c:Company)
MATCH (bankLend:Bank)-[l:LENDS_TO]->(c)
RETURN
    coalesce(c.mcaName, c.crisilName)    AS company,
    c.cin                                AS cin,
    bankRPT.bankSymbol                   AS rptWithBank,
    bankLend.bankSymbol                  AS borrowsFromBank,
    round(l.totalAmount, 2)              AS loanAmountINRCr,
    (bankRPT = bankLend)                 AS sameBank
ORDER BY sameBank DESC, loanAmountINRCr DESC;


// ── Q16 ── Shareholder Category Stakes in Banks ───────────────────────────────
//
// Aggregate shareholding by category (Promoter, FII, DII, Public, etc.) per bank.

MATCH (s:Shareholder)-[r:SHAREHOLDER_OF]->(b:Bank)
RETURN
    b.bankSymbol                         AS bank,
    s.shareholderCategory                AS category,
    round(sum(r.shareholdingPercentage), 4) AS totalCategoryPct,
    count(DISTINCT s)                    AS numShareholders
ORDER BY bank, totalCategoryPct DESC;


// ── Q17 ── Top Shareholder Entities Across the Entire Graph ──────────────────
//
// Entities (Shareholders, Banks, Companies) ranked by number of distinct
// nodes they hold a stake in — measures ownership "reach".

MATCH (owner)-[r:SHAREHOLDER_OF]->(target)
WITH owner,
     count(DISTINCT target)              AS totalHoldings,
     sum(r.shareholdingPercentage)       AS sumPct
RETURN
    labels(owner)[0]                     AS entityType,
    CASE
        WHEN owner:Shareholder THEN owner.shareholderName
        WHEN owner:Bank        THEN owner.bankSymbol
        WHEN owner:Company     THEN coalesce(owner.mcaName, owner.crisilName)
    END                                  AS entityName,
    totalHoldings,
    round(sumPct, 4)                     AS totalStakePct
ORDER BY totalHoldings DESC, totalStakePct DESC
LIMIT 30;


// ── Q18 ── Common Borrowers Across All Three Banks (network subgraph) ─────────
//
// Return the full subgraph of banks + companies where the company borrows
// from ≥ 2 banks. Useful for direct graph visualization in Browser.

MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)
WITH c, collect(b) AS banks, sum(l.totalAmount) AS total
WHERE size(banks) > 1
UNWIND banks AS b
MATCH (b)-[l2:LENDS_TO]->(c)
RETURN b, l2, c;


// ── Q19 ── Full Exposure Web for ONE Company (ego-graph) ──────────────────────
//
// Replace the CIN below with any company CIN to get its full exposure web:
// who lends, who holds shares, which bank has RPT, industry, parent.
// Great for single-entity deep-dive in the Browser.

// :param cin => "L65910MH1994PLC080618"  -- example; replace as needed

MATCH path = (n)-[r]-(c:Company {cin: $cin})
RETURN path;


// ── Q20 ── Systemic Risk Score (Degree Centrality Proxy) ─────────────────────
//
// Rank companies by how many distinct banks are connected to them
// via any type of relationship (lending, RPT, shareholding, subsidiary).
// High score = high systemic importance / contagion potential.

MATCH (b:Bank)-[r]->(c:Company)
WITH c,
     count(DISTINCT b)                   AS bankConnections,
     count(DISTINCT type(r))             AS relationshipTypes,
     collect(DISTINCT b.bankSymbol)      AS connectedBanks,
     collect(DISTINCT type(r))           AS relTypes
RETURN
    coalesce(c.mcaName, c.crisilName)    AS company,
    c.cin                                AS cin,
    c.industryName                       AS industry,
    bankConnections,
    relationshipTypes,
    connectedBanks,
    relTypes
ORDER BY bankConnections DESC, relationshipTypes DESC
LIMIT 30;
