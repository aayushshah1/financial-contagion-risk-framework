// queries/cross_bank_ownership.cypher
// Trace direct and indirect ownership links between banks.

// ── 1. Direct cross-bank ownership (Bank owns shares of another Bank) ────────
MATCH (b1:Bank)-[r:SHAREHOLDER_OF]->(b2:Bank)
RETURN
    b1.bankSymbol                       AS ownerBank,
    b2.bankSymbol                       AS targetBank,
    r.numberOfShares                    AS shares,
    r.shareholdingPercentage            AS holdingPct
ORDER BY holdingPct DESC;


// ── 2. Indirect ownership via known subsidiaries ─────────────────────────────
// e.g. HDFC AMC (subsidiary of HDFCBANK) holds shares in SBIN
MATCH (sh:Shareholder)-[:SUBSIDIARY_OF]->(parent:Bank),
      (sh)-[r:SHAREHOLDER_OF]->(target:Bank)
WHERE parent <> target
RETURN
    parent.bankSymbol                   AS ownerBank,
    sh.shareholderName                  AS vehicle,
    sh.shareholderCategory              AS vehicleType,
    target.bankSymbol                   AS targetBank,
    r.shareholdingPercentage            AS holdingPct
ORDER BY holdingPct DESC;


// ── 3. All ownership paths between banks (direct + 1-hop via subsidiary) ─────
MATCH path = (b1:Bank)-[:SHAREHOLDER_OF|SUBSIDIARY_OF*1..2]->(b2:Bank)
WHERE b1 <> b2
RETURN
    b1.bankSymbol                       AS from,
    [n IN nodes(path) | coalesce(n.bankSymbol, n.shareholderName)] AS pathNodes,
    b2.bankSymbol                       AS to,
    length(path)                        AS hops
ORDER BY hops, from, to;


// ── 4. Top institutional shareholders common across all 3 banks ──────────────
MATCH (sh:Shareholder)-[r:SHAREHOLDER_OF]->(b:Bank)
WITH sh, count(DISTINCT b) AS bankCount, collect(b.bankSymbol + ':' + toString(round(r.shareholdingPercentage, 2)) + '%') AS holdings
WHERE bankCount > 1
RETURN
    sh.shareholderName                  AS shareholder,
    sh.shareholderCategory              AS category,
    bankCount,
    holdings
ORDER BY bankCount DESC, shareholder;


// ── 5. Companies with facilities from 2+ banks, showing relationship details ─────
MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
WITH c, collect({bank: b.bankSymbol, amount: r.totalAmount, types: r.facilityTypes}) AS exposures, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
RETURN
    c.companyName                      AS company,
    c.companyCode                      AS code,
    bankCount,
    exposures
ORDER BY bankCount DESC, company;


// ── 6. Shareholders with stakes in 2+ banks, showing relationship details ─────
MATCH (sh:Shareholder)-[r:SHAREHOLDER_OF]->(b:Bank)
WITH sh, collect({bank: b.bankSymbol, pct: r.shareholdingPercentage, shares: r.numberOfShares}) AS holdings, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
RETURN
    sh.shareholderName                 AS shareholder,
    sh.shareholderCategory             AS category,
    bankCount,
    holdings
ORDER BY bankCount DESC, shareholder;


// ── 7. Companies with facilities from 2+ banks, as a graph ─────
MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
WITH c, collect(b) AS banks, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
UNWIND banks AS b
MATCH (b)-[r:LENDS_TO]->(c)
RETURN b, r, c;

// ── 8. Shareholders with stakes in 2+ banks, as a graph ─────
MATCH (sh:Shareholder)-[r:SHAREHOLDER_OF]->(b:Bank)
WITH sh, collect(b) AS banks, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
UNWIND banks AS b
MATCH (sh)-[r:SHAREHOLDER_OF]->(b)
RETURN sh, r, b;

// ── 9. Any node (Company or Shareholder) connected to 2+ banks, as a graph ─────
MATCH (b:Bank)-[r]->(n)
WHERE n:Company OR n:Shareholder
WITH n, collect(DISTINCT b) AS banks, count(DISTINCT b) AS bankCount
WHERE bankCount > 1
UNWIND banks AS b
MATCH (b)-[r]->(n)
WHERE n:Company OR n:Shareholder
RETURN b, r, n;
