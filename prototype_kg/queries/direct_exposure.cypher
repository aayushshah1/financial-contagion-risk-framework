// queries/direct_exposure.cypher
// Total LENDS_TO exposure per bank, ranked by exposure.
// Also shows the split of exposure across facility types.

// ── 1. Total exposure per bank ──────────────────────────────────────────────
MATCH (b:Bank)-[r:LENDS_TO]->(:Company)
RETURN
    b.bankSymbol                        AS bank,
    count(r)                            AS companiesExposed,
    round(sum(r.totalAmount), 2)        AS totalExposureINRCrore
ORDER BY totalExposureINRCrore DESC;


// ── 2. Top 20 companies by total borrowing (across all 3 banks) ─────────────
MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
WITH c, sum(r.totalAmount) AS totalBorrowed, collect(b.bankSymbol) AS lenders
RETURN
    c.companyName                       AS company,
    c.companyCode                       AS code,
    c.companyIndustrialClassification   AS classification,
    round(totalBorrowed, 2)             AS totalBorrowedINRCrore,
    lenders
ORDER BY totalBorrowed DESC
LIMIT 20;


// ── 3. Exposure breakdown by facility type per bank ─────────────────────────
MATCH (b:Bank)-[r:LENDS_TO]->(:Company)
UNWIND r.facilityTypes AS fType
RETURN
    b.bankSymbol    AS bank,
    fType           AS facilityType,
    count(*)        AS count,
    round(sum(r.totalAmount), 2) AS totalINRCrore
ORDER BY bank, totalINRCrore DESC;
