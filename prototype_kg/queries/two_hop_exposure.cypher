// queries/two_hop_exposure.cypher
// Indirect bank-to-bank exposure via shared borrowers.
// Bank A and Bank B both lend to Company C → indirect contagion path.

// ── 1. Shared borrowers between each pair of banks ──────────────────────────
MATCH (b1:Bank)-[r1:LENDS_TO]->(c:Company)<-[r2:LENDS_TO]-(b2:Bank)
WHERE b1.bankSymbol < b2.bankSymbol      // avoid duplicate pairs
RETURN
    b1.bankSymbol                           AS bank1,
    b2.bankSymbol                           AS bank2,
    count(DISTINCT c)                       AS sharedCompanies,
    round(sum(r1.totalAmount), 2)           AS bank1ExposureThrough,
    round(sum(r2.totalAmount), 2)           AS bank2ExposureThrough
ORDER BY sharedCompanies DESC;


// ── 2. Top shared borrowers with exposure from both banks ────────────────────
MATCH (b1:Bank)-[r1:LENDS_TO]->(c:Company)<-[r2:LENDS_TO]-(b2:Bank)
WHERE b1.bankSymbol < b2.bankSymbol
RETURN
    c.companyName                       AS company,
    c.companyCode                       AS code,
    b1.bankSymbol                       AS bank1,
    round(r1.totalAmount, 2)            AS bank1Crore,
    b2.bankSymbol                       AS bank2,
    round(r2.totalAmount, 2)            AS bank2Crore,
    round(r1.totalAmount + r2.totalAmount, 2) AS combinedExposureCrore
ORDER BY combinedExposureCrore DESC
LIMIT 25;


// ── 3. Companies exposed to all 3 target banks ──────────────────────────────
MATCH (c:Company)
WHERE (:Bank)-[:LENDS_TO]->(c) AND
      size([(b:Bank)-[:LENDS_TO]->(c) | b]) = 3
MATCH (b:Bank)-[r:LENDS_TO]->(c)
RETURN
    c.companyName               AS company,
    c.companyCode               AS code,
    collect(b.bankSymbol + ': ' + toString(round(r.totalAmount, 2)) + ' Cr') AS exposures,
    round(sum(r.totalAmount), 2) AS totalExposureAllBanks
ORDER BY totalExposureAllBanks DESC;
