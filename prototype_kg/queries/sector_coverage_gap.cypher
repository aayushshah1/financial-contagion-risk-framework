// queries/sector_coverage_gap.cypher
// Compare RBI-authoritative sector exposure (PRIORITY_EXPOSURE)
// vs CRISIL-sampled exposure (aggregated from LENDS_TO + BELONGS_TO).
// The gap is a direct measure of how much of the bank's actual exposure
// is captured in the CRISIL company-level data.

// ── 1. Coverage gap per bank per sector ─────────────────────────────────────
MATCH (b:Bank)-[pe:PRIORITY_EXPOSURE]->(s:Sector)
OPTIONAL MATCH (b)-[lt:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(s)
WITH
    b.bankSymbol                        AS bank,
    s.industryName                      AS sector,
    s.industryCode                      AS industryCode,
    s.nicSection                        AS nicSection,
    pe.rbiCategoryLabel                 AS rbiCategory,
    pe.outstandingAmount                AS rbiAuthoritative,
    sum(coalesce(lt.totalAmount, 0))    AS crisilSampled
RETURN
    bank,
    rbiCategory,
    sector,
    nicSection,
    round(rbiAuthoritative, 2)          AS rbiAuthoritativeINRCrore,
    round(crisilSampled, 2)             AS crisilSampledINRCrore,
    round(rbiAuthoritative - crisilSampled, 2) AS coverageGapINRCrore,
    CASE
        WHEN rbiAuthoritative > 0
        THEN round(100.0 * crisilSampled / rbiAuthoritative, 1)
        ELSE null
    END                                 AS crisilCoveragePct
ORDER BY bank, rbiAuthoritative DESC;


// ── 2. Aggregate coverage per bank (all sectors combined) ───────────────────
MATCH (b:Bank)-[pe:PRIORITY_EXPOSURE]->(s:Sector)
OPTIONAL MATCH (b)-[lt:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(s)
WITH
    b.bankSymbol                        AS bank,
    pe.outstandingAmount                AS rbi,
    sum(coalesce(lt.totalAmount, 0))    AS crisil
WITH
    bank,
    sum(rbi)    AS totalRBI,
    sum(crisil) AS totalCRISIL
RETURN
    bank,
    round(totalRBI, 2)                  AS totalRBIAuthoritative,
    round(totalCRISIL, 2)               AS totalCRISILSampled,
    round(totalRBI - totalCRISIL, 2)    AS totalGap,
    round(100.0 * totalCRISIL / totalRBI, 1) AS overallCoveragePct
ORDER BY bank;


// ── 3. Companies in high-gap sectors (potential data-quality targets) ────────
MATCH (b:Bank)-[pe:PRIORITY_EXPOSURE]->(s:Sector)
OPTIONAL MATCH (b)-[lt:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(s)
WITH s, pe.outstandingAmount - sum(coalesce(lt.totalAmount, 0)) AS gap
WHERE gap > 1000        // gap greater than 1000 INR Crore
WITH s, gap ORDER BY gap DESC LIMIT 5
MATCH (c:Company)-[:BELONGS_TO]->(s)
RETURN
    s.industryName      AS sector,
    round(gap, 2)       AS gapINRCrore,
    count(c)            AS companiesInCRISIL
ORDER BY gapINRCrore DESC;
