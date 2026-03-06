// prototype_kg/schema.cypher
// Run once against AuraDB to establish constraints and indexes.
// Execute via: neo4j-shell, cypher-shell, or the AuraDB Browser.

// ── Uniqueness constraints (also create backing index) ───────────────────────

CREATE CONSTRAINT bank_symbol_unique IF NOT EXISTS
  FOR (b:Bank) REQUIRE b.bankSymbol IS UNIQUE;

// Company nodes are keyed by CIN (real or synthetic dummyCIN)
CREATE CONSTRAINT company_cin_unique IF NOT EXISTS
  FOR (c:Company) REQUIRE c.cin IS UNIQUE;

CREATE CONSTRAINT shareholder_name_unique IF NOT EXISTS
  FOR (s:Shareholder) REQUIRE s.shareholderName IS UNIQUE;

// CRISIL Industry taxonomy (Company -> Industry)
CREATE CONSTRAINT industry_code_unique IF NOT EXISTS
  FOR (i:Industry) REQUIRE i.industryCode IS UNIQUE;

// RBI Priority Sector taxonomy (Bank -> PrioritySector)
CREATE CONSTRAINT priority_sector_rbi_key_unique IF NOT EXISTS
  FOR (p:PrioritySector) REQUIRE p.rbiCategory IS UNIQUE;

// ── Additional indexes ────────────────────────────────────────────────────────

// Fast lookup for unresolved RPT stubs
CREATE INDEX company_resolved_idx IF NOT EXISTS
  FOR (c:Company) ON (c.resolved);

// Fast lookup for lender stub nodes (isStub=true are unresolved lenders)
CREATE INDEX company_is_stub_idx IF NOT EXISTS
  FOR (c:Company) ON (c.isStub);

// Fast lookup by nodeSource (e.g. 'LenderStub', 'CRISIL', 'MCA')
CREATE INDEX company_node_source_idx IF NOT EXISTS
  FOR (c:Company) ON (c.nodeSource);

// Fast lookup for CRISIL industry membership queries
CREATE INDEX company_industry_code_idx IF NOT EXISTS
  FOR (c:Company) ON (c.industryCode);

// Fast lookup by NSE symbol
CREATE INDEX company_nse_symbol_idx IF NOT EXISTS
  FOR (c:Company) ON (c.nseSymbol);

// Fast lookup by CRISIL companyCode
CREATE INDEX company_code_idx IF NOT EXISTS
  FOR (c:Company) ON (c.companyCode);

// Fast lookup by NIC code
CREATE INDEX company_nic_code_idx IF NOT EXISTS
  FOR (c:Company) ON (c.nicCode);

// Fast lookup for shareholder category filtering
CREATE INDEX shareholder_category_idx IF NOT EXISTS
  FOR (s:Shareholder) ON (s.shareholderCategory);

// Fast lookup for RBI priority sector label
CREATE INDEX priority_sector_label_idx IF NOT EXISTS
  FOR (p:PrioritySector) ON (p.rbiCategoryLabel);

