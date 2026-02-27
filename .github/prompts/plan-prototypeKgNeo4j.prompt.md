# Plan: Neo4j Knowledge Graph — prototype_kg

**Decisions baked in:**
- Nodes are data-light — MongoDB stays the authoritative detail store; Neo4j carries only what's needed for graph traversal and visualization
- Shareholders: every named entity → `Shareholder` node, deduplicated across banks
- Bank subsidiaries appearing as shareholders get a `SUBSIDIARY_OF` edge to their parent bank
- Banks appearing as shareholders of other banks → reuse the `:Bank` node directly (cross-bank ownership via `Bank → SHAREHOLDER_OF → Bank`)
- RPT: company-to-company only (directors/humans filtered out); unmatched names get placeholder nodes flagged `resolved: false`, resolved in a second pass
- LENDS_TO: one aggregated edge per bank↔company pair (multi-facility amounts summed)
- Sector nodes are "super nodes" — authoritative exposure from `outstandingAdvances` (RBI data) is stored on the edge; CRISIL-sampled exposure is always a derived query, never a conflicting stored value
- Target: Neo4j AuraDB free tier (env-var–driven connection)

Data source for all ingestion: the three consolidated bank documents already in MongoDB `financial_kg.banks` (same shape as `prototype_kg/sample.json`).

---

## Node Labels & Properties

### `:Bank` — primary key `bankSymbol`
- `bankSymbol`, `bankName`
- 3 nodes total (SBIN, HDFCBANK, ICICIBANK)

### `:Company` — primary key `companyCode`
- `companyCode`, `companyName`, `companyIndustrialClassification`
- `source` (`"CRISIL"` | `"RPT"` | `"CRISIL+RPT"`), `resolved` (`true`/`false`)
- Created from `advances.companies` (CRISIL, ~1000+/bank) plus RPT counter-parties after human-entity filter

### `:Shareholder` — primary key `shareholderName` (deduplicated across banks)
- `shareholderName`, `shareholderCategory`
  - Categories: `MutualFund`, `FPI_Cat1`, `FPI_Cat2`, `InsuranceCompany`, `Bank`, `ProvidentFund`, `GovernmentPromoter`, `BodyCorporate`, `ResidentIndividual`, `NonResidentIndian`, `Custodian`
- **Note:** A `:Shareholder` node that is a known bank subsidiary (e.g. "HDFC Mutual Fund", "SBI Life Insurance") gets an additional `SUBSIDIARY_OF` edge pointing to its parent `:Bank` node. A `:Bank` node that appears as a shareholder of another bank is **not** duplicated — the existing `:Bank` node is reused directly with a `SHAREHOLDER_OF` edge.

### `:Sector` — primary key `nicSection` (NIC one-letter section code, A–S)
- `nicSection`, `sectorName`
- Acts as a **super node**: receives authoritative RBI exposure from the bank above, and company membership from below
- Created from the NIC taxonomy + `outstandingAdvances` RBI priority-sector crosswalk
- ~16–19 nodes (one per NIC section present in the data)

---

## Relationship Types & Properties

### `(:Bank)-[:LENDS_TO]->(:Company)` — one per bank-company pair
- `totalAmount` (INR Crore, sum of all facilities), `currency`="INR Crore"
- `facilityCount`, `facilityTypes` (array: `Bills Discounting`, `Working Capital`, `Term Loan`)
- `source`="CRISIL", `dataYear`=2025

### `(:Shareholder)-[:SHAREHOLDER_OF]->(:Bank)` — one per entity-bank pair
- `numberOfShares`, `shareholdingPercentage`
- `source`="SHP_XBRL"

### `(:Bank)-[:SHAREHOLDER_OF]->(:Bank)` — direct cross-bank ownership
- Same properties as above
- Created when a target bank's name matches a shareholder entity in another bank's SHP data
- Example: SBI directly holds shares in YES Bank (when YES Bank is added)

### `(:Shareholder)-[:SUBSIDIARY_OF]->(:Bank)` — bank-subsidiary linkage
- No additional properties needed
- Created when a shareholder name is found in the known-subsidiaries lookup table (stored in `config.py`)
- Example: `(:Shareholder {shareholderName: "HDFC Mutual Fund"})-[:SUBSIDIARY_OF]->(:Bank {bankSymbol: "HDFCBANK"})`

### `(:Bank)-[:RELATED_PARTY]->(:Company)` — company-only RPTs
- `relationship` (Associates, JV, Subsidiary, etc.), `transactionType`
- `actualAmount`, `reportingPeriod` (e.g. `"Q2FY26"`)
- `source`="Integrated_XBRL"

### `(:Bank)-[:PRIORITY_EXPOSURE]->(:Sector)` — authoritative RBI sector exposure
- `outstandingAmount` (INR Crore, from `outstandingAdvances`)
- `rbiCategory` (e.g. `"Agriculture"`, `"MSME"`, `"Housing"`) — the original RBI label before crosswalk
- `source`="RBI_OutstandingAdvances", `dataYear`=2025
- **This is the only stored bank→sector exposure value.** CRISIL-sampled sector exposure is always computed on demand via:
  ```cypher
  MATCH (b:Bank)-[:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(s:Sector)
  RETURN b.bankSymbol, s.sectorName, sum(r.totalAmount)
  ```

### `(:Company)-[:BELONGS_TO]->(:Sector)` — company sector membership
- `nicCode` (5-digit NIC code for precision)
- `source`="NIC_Mapping"

---

## Folder & File Structure

```
prototype_kg/
  config.py                    ← AuraDB URI/creds from env vars + known subsidiary lookup table
  schema.cypher                ← CONSTRAINT and INDEX DDL
  loader.py                    ← Main orchestrator; calls all builders in sequence
  nodes/
    bank_node.py               ← Build :Bank nodes
    company_node.py            ← Build :Company nodes (CRISIL + RPT, deduplicated)
    shareholder_node.py        ← Build :Shareholder nodes; resolve bank/subsidiary cases
    sector_node.py             ← Build :Sector nodes from NIC taxonomy
  relationships/
    lends_to.py                ← LENDS_TO edges, aggregated per bank-company pair
    shareholder_of.py          ← SHAREHOLDER_OF edges (Shareholder→Bank and Bank→Bank)
    subsidiary_of.py           ← SUBSIDIARY_OF edges for known bank subsidiaries
    related_party.py           ← Filter RPT → company-only; create RELATED_PARTY edges
    priority_exposure.py       ← PRIORITY_EXPOSURE edges from outstandingAdvances
    belongs_to.py              ← BELONGS_TO edges (Company→Sector via nicCode)
  resolution/
    entity_resolver.py         ← Match RPT names → companyCode; mark resolved/unresolved
  queries/
    direct_exposure.cypher     ← Total LENDS_TO amount per bank
    two_hop_exposure.cypher    ← Bank → Company → Bank indirect exposure
    sector_coverage_gap.cypher ← Compare RBI authoritative vs CRISIL-sampled per sector
    cross_bank_ownership.cypher← Bank→Bank SHAREHOLDER_OF paths
  requirements.txt
```

---

## Implementation Steps

1. **Schema setup** — `schema.cypher`: uniqueness constraints on `Bank.bankSymbol`, `Company.companyCode`, `Shareholder.shareholderName`, `Sector.nicSection`; indexes on `Company.resolved`, `LENDS_TO.totalAmount`

2. **Config & connection** — `config.py`: read `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD` from `.env`; expose `get_driver()` utility; include `KNOWN_SUBSIDIARIES` dict (subsidiary name → parent `bankSymbol`) and `RBI_TO_NIC_CROSSWALK` dict (RBI priority category → NIC section letter)

3. **Bank nodes** — `nodes/bank_node.py`: `MERGE (:Bank {bankSymbol, bankName})` for each of the 3 banks

4. **Sector nodes** — `nodes/sector_node.py`: create one `:Sector` node per NIC section present in the company data; properties: `nicSection`, `sectorName`

5. **Company nodes** — `nodes/company_node.py`: iterate `advances.companies` for each bank → `MERGE (:Company {companyCode})` with `companyName`, `companyIndustrialClassification`, `source`=`"CRISIL"`, `resolved=true`

6. **LENDS_TO edges** — `relationships/lends_to.py`: for each company, aggregate all facility amounts → `MERGE (b:Bank)-[r:LENDS_TO]->(c:Company)` with `totalAmount`, `facilityCount`, `facilityTypes`

7. **BELONGS_TO edges** — `relationships/belongs_to.py`: for each Company with a `nicCode`, extract the NIC section letter (first char of nicCode) → `MERGE (c:Company)-[:BELONGS_TO {nicCode}]->(s:Sector)`

8. **Shareholder nodes + cross-bank resolution** — `nodes/shareholder_node.py` + `relationships/shareholder_of.py`:
   - Walk `shareholdingPattern` tree for all entity lists
   - For each entity name: check if it matches a target bank (`bankSymbol` lookup) → if yes, use existing `:Bank` node for `SHAREHOLDER_OF` edge (Bank→Bank ownership)
   - Else check `KNOWN_SUBSIDIARIES` → if yes, `MERGE (:Shareholder)` + `MERGE (sh)-[:SUBSIDIARY_OF]->(parentBank)`
   - Else `MERGE (:Shareholder)` as normal
   - Create `SHAREHOLDER_OF` edge with `numberOfShares`, `shareholdingPercentage`

9. **PRIORITY_EXPOSURE edges** — `relationships/priority_exposure.py`: iterate `outstandingAdvances` subcategories per bank → apply `RBI_TO_NIC_CROSSWALK` → `MERGE (b:Bank)-[:PRIORITY_EXPOSURE {outstandingAmount, rbiCategory}]->(s:Sector)`

10. **RPT entity resolution + edges** — `resolution/entity_resolver.py`: filter out human names from RPT list (keep only entries with corporate keywords: "Ltd", "Limited", "Corp", "Bank", "Technologies", "Finance", "Insurance", "Capital") → fuzzy-match name to `companyCode` via `advances.companies` name lookup → `MERGE (:Company)` with `resolved` flag → `MERGE (b:Bank)-[:RELATED_PARTY {relationship, transactionType, actualAmount, reportingPeriod}]->(c:Company)`

11. **Loader orchestration** — `loader.py`: runs all steps in order; logs node/edge counts after each step

---

## Key Design Decisions

- **Data-light philosophy**: Neo4j nodes carry only identity + graph-traversal-relevant properties; all detailed financials stay in MongoDB. Never store something on a Neo4j node that you won't filter/traverse on.
- **Entity deduplication**: `MERGE` on unique key prevents duplicates across banks (a company borrowing from both SBI and HDFC = one Company node with two LENDS_TO edges)
- **RPT company-filter heuristic**: keep names containing `"Ltd"`, `"Limited"`, `"Corp"`, `"Technologies"`, `"Bank"`, `"Finance"`, `"Insurance"`, `"Capital"`, etc.; discard personal names
- **Shareholder dedup across banks**: `"LIC of India"` is `MERGE`-d once; `SHAREHOLDER_OF` edge carries per-bank percentages
- **Bank-as-shareholder (same entity, two roles)**: Handled by reusing the existing `:Bank` node — no duplicate node, just a self-referential graph edge. This enables `MATCH (:Bank)-[:SHAREHOLDER_OF]->(:Bank)` queries directly.
- **Bank subsidiaries as shareholders**: `SUBSIDIARY_OF` edge makes cross-bank indirect ownership traversable: `MATCH (sh:Shareholder)-[:SUBSIDIARY_OF]->(parent:Bank)-[...]->(anotherBank:Bank)` reveals indirect cross-holdings.
- **Sector as super node — one authoritative edge, one derived query**: `PRIORITY_EXPOSURE` stores the RBI-certified total. CRISIL-sampled exposure is *never* stored to avoid a false reconciliation. The difference between the two, when queried together, is a direct measure of CRISIL data coverage.
- **RBI-to-NIC crosswalk** lives in `config.py` (e.g. Agriculture→A, Housing→L, Education→P, MSME→C/D/G); approximate but good enough for prototype; can be refined later.

---

## Verification Queries

After running `loader.py`, validate in AuraDB Browser:

```cypher
// Node counts by label
MATCH (n) RETURN labels(n), count(n)

// Edge counts by type
MATCH ()-[r]->() RETURN type(r), count(r)

// Unresolved RPT company nodes
MATCH (c:Company {resolved: false}) RETURN count(c)

// Direct exposure per bank
MATCH (b:Bank)-[r:LENDS_TO]->(:Company)
RETURN b.bankSymbol, count(r) AS companies, sum(r.totalAmount) AS totalExposure
ORDER BY totalExposure DESC

// Companies borrowing from multiple target banks (shared exposure / overlap risk)
MATCH (b1:Bank)-[r1:LENDS_TO]->(c:Company)<-[r2:LENDS_TO]-(b2:Bank)
WHERE b1 <> b2
RETURN c.companyName, collect(b1.bankSymbol + ': ' + toString(r1.totalAmount)) AS exposures

// Sector coverage gap: RBI authoritative vs CRISIL-sampled
MATCH (b:Bank)-[pe:PRIORITY_EXPOSURE]->(s:Sector)
OPTIONAL MATCH (b)-[lt:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(s)
RETURN b.bankSymbol, s.sectorName, pe.rbiCategory,
       pe.outstandingAmount AS rbiAuthoritative,
       sum(lt.totalAmount) AS crisilSampled,
       pe.outstandingAmount - sum(lt.totalAmount) AS coverageGap

// Direct cross-bank ownership (Bank owns shares of Bank)
MATCH (b1:Bank)-[r:SHAREHOLDER_OF]->(b2:Bank)
RETURN b1.bankSymbol, b2.bankSymbol, r.shareholdingPercentage

// Indirect cross-bank ownership via subsidiaries
MATCH (sh:Shareholder)-[:SUBSIDIARY_OF]->(parent:Bank),
      (sh)-[r:SHAREHOLDER_OF]->(target:Bank)
WHERE parent <> target
RETURN parent.bankSymbol AS ownerBank, sh.shareholderName AS vehicle,
       target.bankSymbol AS targetBank, r.shareholdingPercentage
```

---

## Expected Scale (3 banks)

| Entity | Estimated Count |
|---|---|
| `:Bank` nodes | 3 |
| `:Company` nodes | ~2,000–3,000 (after dedup across banks) |
| `:Shareholder` nodes | ~500–2,000 (after dedup across banks) |
| `:Sector` nodes | ~16–19 (one per NIC section) |
| `LENDS_TO` edges | ~3,000–4,000 |
| `SHAREHOLDER_OF` (Shareholder→Bank) | ~500–2,000 |
| `SHAREHOLDER_OF` (Bank→Bank) | 0–few (as data grows) |
| `SUBSIDIARY_OF` edges | ~10–30 (known subsidiaries) |
| `RELATED_PARTY` edges | ~50–200 (company-only RPTs) |
| `PRIORITY_EXPOSURE` edges | ~30–60 (3 banks × ~10–20 RBI categories) |
| `BELONGS_TO` edges | ~2,000–3,000 (one per Company with nicCode) |
