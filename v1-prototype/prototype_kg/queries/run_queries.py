"""
prototype_kg/queries/run_queries.py

Runs the interesting analytical queries against the Neo4j AuraDB instance
and produces:
  - Tabular output for analytical / ranking queries  (printed + saved as CSV)
  - Interactive HTML graph visualisations for network queries (PyVis)

Usage
-----
  # Show available queries
  python run_queries.py --list

  # Run a single query by ID
  python run_queries.py --query Q1

  # Run all queries
  python run_queries.py --all

  # Run a specific group  (network | table | bar)
  python run_queries.py --group network

Outputs are written to   prototype_kg/queries/outputs/
"""

from __future__ import annotations

import argparse
import csv
import os
import sys

# ── Path fix: allow  `python run_queries.py`  from any cwd ──────────────────
_HERE = os.path.dirname(os.path.abspath(__file__))
_KG_ROOT = os.path.dirname(_HERE)
if _KG_ROOT not in sys.path:
    sys.path.insert(0, _KG_ROOT)

from config import get_driver   # noqa: E402 (after sys.path fix)

OUTPUT_DIR = os.path.join(_HERE, "outputs")
os.makedirs(OUTPUT_DIR, exist_ok=True)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Query registry
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

# viz_type : "table"   → print + CSV
#            "network" → PyVis HTML graph
#            "bar"     → Matplotlib grouped bar + PNG

QUERIES: dict[str, dict] = {

    # ── Shareholding ──────────────────────────────────────────────────────────

    "Q1": {
        "name": "Common Shareholders Across Banks",
        "group": "table",
        "description": (
            "Entities (Shareholder / Company / Bank) that hold a stake in "
            "MORE THAN ONE of the three target banks. "
            "Reveals concentrated institutional ownership."
        ),
        "cypher": """
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
            ORDER BY bankCount DESC, entityName
        """,
    },

    "Q2": {
        "name": "Cross-Bank Direct Ownership",
        "group": "network",
        "description": "Bank-to-Bank SHAREHOLDER_OF edges — direct cross-ownership stakes.",
        "cypher": """
            MATCH (b1:Bank)-[r:SHAREHOLDER_OF]->(b2:Bank)
            RETURN
                b1.bankSymbol               AS ownerBank,
                b2.bankSymbol               AS targetBank,
                r.shareholdingPercentage    AS stakePct,
                r.numberOfShares            AS shares,
                r.source                    AS source
            ORDER BY r.shareholdingPercentage DESC
        """,
        "network_config": {
            "source_col": "ownerBank",
            "target_col": "targetBank",
            "source_type": "Bank",
            "target_type": "Bank",
            "edge_label_col": "stakePct",
            "edge_label_fmt": "{:.2f}%",
        },
    },

    "Q16": {
        "name": "Shareholding Category Breakdown Per Bank",
        "group": "bar",
        "description": (
            "Aggregate % held by each category (Promoter, FII, DII, Public…) "
            "in each bank — stacked bar chart."
        ),
        "cypher": """
            MATCH (s:Shareholder)-[r:SHAREHOLDER_OF]->(b:Bank)
            RETURN
                b.bankSymbol                               AS bank,
                s.shareholderCategory                      AS category,
                round(sum(r.shareholdingPercentage), 4)    AS totalCategoryPct,
                count(DISTINCT s)                          AS numShareholders
            ORDER BY bank, totalCategoryPct DESC
        """,
        "bar_config": {"x_col": "bank", "y_col": "totalCategoryPct", "group_col": "category"},
    },

    "Q17": {
        "name": "Top Ownership 'Reach' Entities",
        "group": "table",
        "description": "Entities ranked by how many distinct nodes they hold a stake in.",
        "cypher": """
            MATCH (owner)-[r:SHAREHOLDER_OF]->(target)
            WITH owner,
                 count(DISTINCT target)             AS totalHoldings,
                 sum(r.shareholdingPercentage)       AS sumPct
            RETURN
                labels(owner)[0]                    AS entityType,
                CASE
                    WHEN owner:Shareholder THEN owner.shareholderName
                    WHEN owner:Bank        THEN owner.bankSymbol
                    WHEN owner:Company     THEN coalesce(owner.mcaName, owner.crisilName)
                END                                 AS entityName,
                totalHoldings,
                round(sumPct, 4)                    AS totalStakePct
            ORDER BY totalHoldings DESC, totalStakePct DESC
            LIMIT 30
        """,
    },

    # ── Lending / Credit ──────────────────────────────────────────────────────

    "Q3": {
        "name": "Dual-Bank Borrowers",
        "group": "network",
        "description": (
            "Companies borrowing from 2+ banks simultaneously. "
            "Network: banks pointing to shared borrowers (sized by combined exposure)."
        ),
        "cypher": """
            MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)
            WITH c, collect(b.bankSymbol) AS lenders,
                 sum(l.totalAmount) AS combinedExposure
            WHERE size(lenders) > 1
            UNWIND lenders AS lender
            RETURN
                lender                                       AS bank,
                coalesce(c.mcaName, c.crisilName)            AS company,
                c.cin                                        AS cin,
                c.industryName                               AS industry,
                round(combinedExposure, 2)                   AS totalExposureINRCr
            ORDER BY totalExposureINRCr DESC
            LIMIT 100
        """,
        "network_config": {
            "source_col": "bank",
            "target_col": "company",
            "source_type": "Bank",
            "target_type": "Company",
            "edge_label_col": "totalExposureINRCr",
            "edge_label_fmt": "₹{:.0f} Cr",
            "node_size_col": "totalExposureINRCr",
        },
    },

    "Q4": {
        "name": "Triple-Bank Borrowers",
        "group": "table",
        "description": "Companies with credit facilities from ALL THREE target banks (highest concentration).",
        "cypher": """
            MATCH (b:Bank)-[r:LENDS_TO]->(c:Company)
            WITH c, collect(b.bankSymbol) AS lenders, sum(r.totalAmount) AS combinedExposure
            WHERE size(lenders) >= 3
            RETURN
                coalesce(c.mcaName, c.crisilName)   AS companyName,
                c.cin                               AS cin,
                c.industryName                      AS industry,
                lenders,
                round(combinedExposure, 2)          AS totalExposureINRCr
            ORDER BY totalExposureINRCr DESC
        """,
    },

    "Q11": {
        "name": "Top Industry Concentration Per Bank",
        "group": "table",
        "description": "Per bank: which CRISIL industry takes the largest share of tracked lending?",
        "cypher": """
            MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(i:Industry)
            WITH b.bankSymbol AS bank, i.industryName AS industry,
                 sum(l.totalAmount) AS sectorExposure, count(DISTINCT c) AS numCos
            ORDER BY bank, sectorExposure DESC
            RETURN bank, industry,
                   round(sectorExposure, 2) AS exposureINRCr,
                   numCos
            LIMIT 60
        """,
    },

    "Q12": {
        "name": "Industry Breakdown Per Bank (Bar Chart)",
        "group": "bar",
        "description": "Stacked-bar: total CRISIL-tracked exposure per bank broken down by industry (top 10 industries).",
        "cypher": """
            MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:BELONGS_TO]->(i:Industry)
            RETURN
                b.bankSymbol                            AS bank,
                i.industryName                          AS industry,
                round(sum(l.totalAmount), 2)            AS totalExposureINRCr,
                count(DISTINCT c)                       AS numCompanies
            ORDER BY bank, totalExposureINRCr DESC
        """,
        "bar_config": {"x_col": "bank", "y_col": "totalExposureINRCr", "group_col": "industry"},
    },

    "Q13": {
        "name": "Priority Sector Exposure Comparison",
        "group": "bar",
        "description": "Side-by-side: how much does each bank lend to each RBI priority sector?",
        "cypher": """
            MATCH (b:Bank)-[r:PRIORITY_EXPOSURE]->(p:PrioritySector)
            RETURN
                p.rbiCategoryLabel              AS prioritySector,
                b.bankSymbol                    AS bank,
                round(r.outstandingAmount, 2)   AS outstandingINRCr
            ORDER BY prioritySector, outstandingINRCr DESC
        """,
        "bar_config": {"x_col": "prioritySector", "y_col": "outstandingINRCr", "group_col": "bank"},
    },

    # ── Cross-bank systemic linkages ─────────────────────────────────────────

    "Q5": {
        "name": "Bank Loans to Related Parties of Another Bank",
        "group": "network",
        "description": (
            "Bank A lends to a company that is a Related Party of Bank B (A ≠ B). "
            "A hidden cross-bank systemic linkage channel."
        ),
        "cypher": """
            MATCH (bankA:Bank)-[l:LENDS_TO]->(c:Company)<-[rpt:RELATED_PARTY]-(bankB:Bank)
            WHERE bankA <> bankB
            RETURN
                bankA.bankSymbol                        AS lendingBank,
                bankB.bankSymbol                        AS rptBank,
                coalesce(c.mcaName, c.crisilName)       AS companyName,
                c.cin                                   AS cin,
                rpt.relationship                        AS rptRelationship,
                round(l.totalAmount, 2)                 AS loanAmountINRCr
            ORDER BY loanAmountINRCr DESC
        """,
        "network_config": {
            "source_col": "lendingBank",
            "target_col": "companyName",
            "source_type": "Bank",
            "target_type": "Company",
            "edge_label_col": "loanAmountINRCr",
            "edge_label_fmt": "₹{:.0f} Cr",
            "extra_nodes": [{"col": "rptBank", "type": "Bank", "edge_to": "companyName", "edge_label": "RPT"}],
        },
    },

    "Q6": {
        "name": "Bank Lending to Its Own Subsidiaries",
        "group": "table",
        "description": "Intra-group exposure: Bank X lends to a company that is a subsidiary of Bank X.",
        "cypher": """
            MATCH (b:Bank)-[l:LENDS_TO]->(c:Company)-[:SUBSIDIARY_OF]->(b)
            RETURN
                b.bankSymbol                            AS bank,
                coalesce(c.mcaName, c.crisilName)       AS subsidiary,
                c.cin                                   AS cin,
                round(l.totalAmount, 2)                 AS loanAmountINRCr,
                l.facilityTypes                         AS facilityTypes
            ORDER BY bank, loanAmountINRCr DESC
        """,
    },

    "Q7": {
        "name": "2-Hop: Bank Lending to Subsidiary of Another Bank",
        "group": "network",
        "description": (
            "Bank B lends to Company X, and Company X is a subsidiary of Bank A. "
            "Indirect inter-bank exposure via a shared subsidiary."
        ),
        "cypher": """
            MATCH (bankB:Bank)-[l:LENDS_TO]->(sub:Company)-[:SUBSIDIARY_OF]->(bankA:Bank)
            WHERE bankA <> bankB
            RETURN
                bankA.bankSymbol                        AS parentBank,
                bankB.bankSymbol                        AS lendingBank,
                coalesce(sub.mcaName, sub.crisilName)   AS subsidiary,
                sub.cin                                 AS cin,
                round(l.totalAmount, 2)                 AS exposureINRCr
            ORDER BY exposureINRCr DESC
        """,
        "network_config": {
            "source_col": "lendingBank",
            "target_col": "subsidiary",
            "source_type": "Bank",
            "target_type": "Company",
            "edge_label_col": "exposureINRCr",
            "edge_label_fmt": "₹{:.0f} Cr",
            "extra_nodes": [{"col": "parentBank", "type": "Bank", "edge_to": "subsidiary", "edge_label": "SUBSIDIARY_OF"}],
        },
    },

    "Q8": {
        "name": "2-Hop: Bank → Borrower → Shareholder of Another Bank",
        "group": "network",
        "description": (
            "Bank A lends to Company X, which also holds a stake in Bank B. "
            "Bank B's health is exposed to Company X solvency — same company "
            "that Bank A has credit risk on."
        ),
        "cypher": """
            MATCH (bankA:Bank)-[l:LENDS_TO]->(c:Company)-[s:SHAREHOLDER_OF]->(bankB:Bank)
            WHERE bankA <> bankB
            RETURN
                bankA.bankSymbol                        AS lendingBank,
                bankB.bankSymbol                        AS bankWithStake,
                coalesce(c.mcaName, c.crisilName)       AS company,
                c.cin                                   AS cin,
                round(l.totalAmount, 2)                 AS creditExposureINRCr,
                round(s.shareholdingPercentage, 4)      AS stakeInBankPct
            ORDER BY creditExposureINRCr DESC
        """,
        "network_config": {
            "source_col": "lendingBank",
            "target_col": "company",
            "source_type": "Bank",
            "target_type": "Company",
            "edge_label_col": "creditExposureINRCr",
            "edge_label_fmt": "₹{:.0f} Cr",
            "extra_nodes": [{"col": "bankWithStake", "type": "Bank", "edge_to": "company", "edge_label": "SHAREHOLDER_OF (via company)"}],
        },
    },

    "Q9": {
        "name": "3-Hop: Bank A → Borrower ← RPT Bank B",
        "group": "network",
        "description": (
            "Bank A lends to Company X. Bank B has a Related Party Txn with Company X. "
            "These two banks are linked through a corporate intermediary."
        ),
        "cypher": """
            MATCH (bankA:Bank)-[:LENDS_TO]->(c:Company)
            MATCH (bankB:Bank)-[rpt:RELATED_PARTY]->(c)
            WHERE bankA <> bankB
            WITH bankA, bankB, c,
                 collect(DISTINCT rpt.transactionType) AS rptTypes,
                 count(rpt) AS rptCount
            RETURN
                bankA.bankSymbol                        AS lendingBank,
                bankB.bankSymbol                        AS rptCounterpartyBank,
                coalesce(c.mcaName, c.crisilName)       AS bridgeCompany,
                c.cin                                   AS cin,
                rptCount,
                rptTypes
            ORDER BY rptCount DESC
            LIMIT 50
        """,
        "network_config": {
            "source_col": "lendingBank",
            "target_col": "bridgeCompany",
            "source_type": "Bank",
            "target_type": "Company",
            "extra_nodes": [{"col": "rptCounterpartyBank", "type": "Bank", "edge_to": "bridgeCompany", "edge_label": "RELATED_PARTY"}],
        },
    },

    "Q10": {
        "name": "Conflict of Interest: Shareholder in Bank AND Its Borrower",
        "group": "table",
        "description": (
            "A shareholder holds stake in Bank B AND also in Company C which "
            "borrows from Bank B. Potential conflict of interest."
        ),
        "cypher": """
            MATCH (s)-[:SHAREHOLDER_OF]->(b:Bank)
            MATCH (b)-[:LENDS_TO]->(c:Company)
            MATCH (s)-[:SHAREHOLDER_OF]->(c)
            RETURN
                CASE
                    WHEN s:Shareholder THEN s.shareholderName
                    WHEN s:Bank        THEN s.bankSymbol
                    WHEN s:Company     THEN coalesce(s.mcaName, s.crisilName)
                END                                     AS shareholder,
                labels(s)[0]                            AS shareholderType,
                b.bankSymbol                            AS bank,
                coalesce(c.mcaName, c.crisilName)       AS borrowingCompany,
                c.cin                                   AS cin
            ORDER BY shareholder, bank
        """,
    },

    "Q14": {
        "name": "Bank-to-Bank RPT Network",
        "group": "network",
        "description": "Direct Related Party Transactions declared between the three banks themselves.",
        "cypher": """
            MATCH (b1:Bank)-[r:RELATED_PARTY]->(b2:Bank)
            RETURN
                b1.bankSymbol           AS fromBank,
                b2.bankSymbol           AS toBank,
                r.relationship          AS relationship,
                r.transactionType       AS transactionType,
                r.reportingPeriod       AS period,
                r.actualAmount          AS amountINRCr
            ORDER BY b1.bankSymbol, amountINRCr DESC
        """,
        "network_config": {
            "source_col": "fromBank",
            "target_col": "toBank",
            "source_type": "Bank",
            "target_type": "Bank",
            "edge_label_col": "transactionType",
        },
    },

    "Q15": {
        "name": "Companies That Are Both RPT Counterparty and Borrower",
        "group": "network",
        "description": (
            "Companies with RPT with one bank AND credit facilities from another (or same). "
            "Dual exposure in different contract types."
        ),
        "cypher": """
            MATCH (bankRPT:Bank)-[:RELATED_PARTY]->(c:Company)
            MATCH (bankLend:Bank)-[l:LENDS_TO]->(c)
            RETURN
                coalesce(c.mcaName, c.crisilName)       AS company,
                c.cin                                   AS cin,
                bankRPT.bankSymbol                      AS rptWithBank,
                bankLend.bankSymbol                     AS borrowsFromBank,
                round(l.totalAmount, 2)                 AS loanAmountINRCr,
                (bankRPT = bankLend)                    AS sameBank
            ORDER BY sameBank DESC, loanAmountINRCr DESC
        """,
        "network_config": {
            "source_col": "borrowsFromBank",
            "target_col": "company",
            "source_type": "Bank",
            "target_type": "Company",
            "edge_label_col": "loanAmountINRCr",
            "edge_label_fmt": "₹{:.0f} Cr",
            "extra_nodes": [{"col": "rptWithBank", "type": "Bank", "edge_to": "company", "edge_label": "RELATED_PARTY"}],
        },
    },

    "Q20": {
        "name": "Systemic Risk Score (Degree Centrality Proxy)",
        "group": "table",
        "description": (
            "Rank companies by how many distinct banks are connected to them "
            "via ANY relationship type. "
            "High score ≈ high systemic importance / contagion potential."
        ),
        "cypher": """
            MATCH (b:Bank)-[r]->(c:Company)
            WITH c,
                 count(DISTINCT b)                 AS bankConnections,
                 count(DISTINCT type(r))            AS relationshipTypes,
                 collect(DISTINCT b.bankSymbol)     AS connectedBanks,
                 collect(DISTINCT type(r))          AS relTypes
            RETURN
                coalesce(c.mcaName, c.crisilName)   AS company,
                c.cin                               AS cin,
                c.industryName                      AS industry,
                bankConnections,
                relationshipTypes,
                connectedBanks,
                relTypes
            ORDER BY bankConnections DESC, relationshipTypes DESC
            LIMIT 30
        """,
    },
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Colour / style helpers
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

NODE_COLOURS = {
    "Bank":         "#E8623A",   # burnt orange
    "Company":      "#4A90D9",   # steel blue
    "Shareholder":  "#6BAF6B",   # green
    "Industry":     "#B07FD0",   # purple
    "PrioritySector": "#F0C040", # amber
}

NODE_SHAPES = {
    "Bank":         "star",
    "Company":      "dot",
    "Shareholder":  "diamond",
    "Industry":     "square",
    "PrioritySector": "triangle",
}

EDGE_COLOURS = {
    "LENDS_TO":        "#E8623A",
    "RELATED_PARTY":   "#D94A4A",
    "SHAREHOLDER_OF":  "#6BAF6B",
    "SUBSIDIARY_OF":   "#9C6B2E",
    "BELONGS_TO":      "#B07FD0",
    "PRIORITY_EXPOSURE": "#F0C040",
    "DEFAULT":         "#AAAAAA",
}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PyVis network builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_network_html(query_id: str, meta: dict, records: list[dict]) -> str:
    """
    Build a PyVis network HTML file from flat query results.
    Returns the output file path.
    """
    try:
        from pyvis.network import Network
    except ImportError:
        print("  [warn] pyvis not installed — skipping graph visualisation.")
        print("         Run:  pip install pyvis")
        return ""

    cfg = meta.get("network_config", {})
    src_col  = cfg.get("source_col")
    tgt_col  = cfg.get("target_col")
    src_type = cfg.get("source_type", "Company")
    tgt_type = cfg.get("target_type", "Company")
    edge_lbl_col = cfg.get("edge_label_col")
    edge_lbl_fmt = cfg.get("edge_label_fmt", "{}")
    extra_nodes  = cfg.get("extra_nodes", [])   # additional node columns

    net = Network(
        height="750px",
        width="100%",
        bgcolor="#1a1a2e",
        font_color="#e0e0e0",
        directed=True,
        notebook=False,
        cdn_resources="cdn",
    )
    net.force_atlas_2based(gravity=-30, central_gravity=0.005, spring_length=150, spring_strength=0.08)

    added_nodes: set[str] = set()

    def _node_id(name: str, ntype: str) -> str:
        return f"{ntype}::{name}"

    def _add_node(label: str, ntype: str):
        nid = _node_id(label, ntype)
        if nid not in added_nodes:
            net.add_node(
                nid,
                label=label,
                color=NODE_COLOURS.get(ntype, "#AAAAAA"),
                shape=NODE_SHAPES.get(ntype, "dot"),
                size=25 if ntype == "Bank" else 15,
                title=f"{ntype}: {label}",
                font={"size": 12, "color": "#ffffff"},
            )
            added_nodes.add(nid)
        return nid

    for row in records:
        src_label = str(row.get(src_col, ""))
        tgt_label = str(row.get(tgt_col, ""))
        if not src_label or not tgt_label:
            continue

        sid = _add_node(src_label, src_type)
        tid = _add_node(tgt_label, tgt_type)

        # Edge label
        edge_lbl = ""
        if edge_lbl_col and row.get(edge_lbl_col) is not None:
            try:
                edge_lbl = edge_lbl_fmt.format(float(row[edge_lbl_col]))
            except (ValueError, TypeError):
                edge_lbl = str(row[edge_lbl_col])

        net.add_edge(
            sid, tid,
            label=edge_lbl,
            color=EDGE_COLOURS.get("LENDS_TO", "#AAAAAA"),
            arrows="to",
            title=edge_lbl,
            font={"size": 9, "color": "#dddddd"},
        )

        # Extra annotation nodes (e.g., RPT bank pointing to same company)
        for en in extra_nodes:
            extra_label = str(row.get(en["col"], ""))
            if not extra_label:
                continue
            eid = _add_node(extra_label, en["type"])
            target_nid = _node_id(str(row.get(en["edge_to"], "")), tgt_type)
            if target_nid in added_nodes:
                net.add_edge(
                    eid, target_nid,
                    label=en.get("edge_label", ""),
                    color=EDGE_COLOURS.get("RELATED_PARTY", "#AAAAAA"),
                    arrows="to",
                    dashes=True,
                    font={"size": 9, "color": "#dddddd"},
                )

    out_path = os.path.join(OUTPUT_DIR, f"{query_id}_graph.html")
    net.write_html(out_path)
    return out_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Matplotlib bar chart builder
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _build_bar_chart(query_id: str, meta: dict, records: list[dict]) -> str:
    """
    Build a grouped / stacked bar chart and save as PNG.
    Returns the output file path or empty string on failure.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import numpy as np
    except ImportError:
        print("  [warn] matplotlib not installed — skipping bar chart.")
        print("         Run:  pip install matplotlib")
        return ""

    cfg      = meta.get("bar_config", {})
    x_col    = cfg.get("x_col")
    y_col    = cfg.get("y_col")
    grp_col  = cfg.get("group_col")

    # Aggregate into pivot  {x: {group: y}}
    pivot: dict[str, dict[str, float]] = {}
    for row in records:
        x   = str(row.get(x_col, ""))
        g   = str(row.get(grp_col, ""))
        val = float(row.get(y_col) or 0)
        pivot.setdefault(x, {})[g] = pivot.get(x, {}).get(g, 0) + val

    # Keep top-10 groups by total value to avoid clutter
    group_totals: dict[str, float] = {}
    for gmap in pivot.values():
        for g, v in gmap.items():
            group_totals[g] = group_totals.get(g, 0) + v
    top_groups = sorted(group_totals, key=group_totals.get, reverse=True)[:10]

    x_labels = sorted(pivot.keys())
    n_x      = len(x_labels)
    n_g      = len(top_groups)

    if n_x == 0 or n_g == 0:
        print("  [warn] No data to plot.")
        return ""

    fig, ax = plt.subplots(figsize=(max(12, n_x * 2.5), 7))
    bar_width = 0.8 / n_g
    x_pos     = np.arange(n_x)

    cmap    = plt.get_cmap("tab20")
    colours = [cmap(i / max(n_g - 1, 1)) for i in range(n_g)]

    for gi, group in enumerate(top_groups):
        values = [pivot.get(x, {}).get(group, 0) for x in x_labels]
        offset = (gi - n_g / 2 + 0.5) * bar_width
        bars = ax.bar(x_pos + offset, values, bar_width * 0.9,
                      label=group, color=colours[gi], alpha=0.85)
        # Value labels on bars > 0
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(
                    bar.get_x() + bar.get_width() / 2,
                    bar.get_height() + max(values) * 0.005,
                    f"{val:,.0f}",
                    ha="center", va="bottom", fontsize=6, rotation=90,
                )

    ax.set_xticks(x_pos)
    ax.set_xticklabels(x_labels, rotation=30, ha="right", fontsize=9)
    ax.set_title(meta["name"], fontsize=13, pad=12)
    ax.set_ylabel(f"{y_col} (INR Cr)", fontsize=10)
    ax.legend(
        title=grp_col,
        loc="upper right",
        fontsize=7,
        title_fontsize=8,
        ncol=max(1, n_g // 10),
    )
    ax.set_facecolor("#f9f9f9")
    fig.tight_layout()

    out_path = os.path.join(OUTPUT_DIR, f"{query_id}_bar.png")
    plt.savefig(out_path, dpi=150)
    plt.close()
    return out_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CSV table writer
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _save_csv(query_id: str, records: list[dict]) -> str:
    if not records:
        return ""
    out_path = os.path.join(OUTPUT_DIR, f"{query_id}_results.csv")
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=records[0].keys())
        writer.writeheader()
        writer.writerows(records)
    return out_path


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Print table helper
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _print_table(records: list[dict], max_rows: int = 30):
    if not records:
        print("  (no results)")
        return
    try:
        from tabulate import tabulate
        print(tabulate(records[:max_rows], headers="keys", tablefmt="rounded_outline",
                       maxcolwidths=40))
    except ImportError:
        # Fallback: plain print
        headers = list(records[0].keys())
        col_w   = {h: max(len(h), max(len(str(r.get(h, ""))) for r in records[:max_rows])) for h in headers}
        sep     = "  ".join("-" * col_w[h] for h in headers)
        hdr     = "  ".join(h.ljust(col_w[h]) for h in headers)
        print(hdr)
        print(sep)
        for row in records[:max_rows]:
            print("  ".join(str(row.get(h, "")).ljust(col_w[h]) for h in headers))
    if len(records) > max_rows:
        print(f"  … {len(records) - max_rows} more rows (saved to CSV)")


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# Core runner
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def run_query(driver, query_id: str, params: dict | None = None):
    meta = QUERIES.get(query_id)
    if meta is None:
        print(f"[error] Unknown query ID: {query_id}")
        return

    group = meta.get("group", "table")
    print(f"\n{'━' * 72}")
    print(f"  {query_id}  ·  {meta['name']}")
    print(f"  {meta['description']}")
    print(f"{'━' * 72}")

    with driver.session() as session:
        result = session.run(meta["cypher"], **(params or {}))
        records = [dict(r) for r in result]

    print(f"  → {len(records)} result(s)")

    if not records:
        print("  (no data — check that the graph is populated)")
        return

    # Always save CSV
    csv_path = _save_csv(query_id, records)
    if csv_path:
        print(f"  CSV → {csv_path}")

    if group == "table":
        _print_table(records)

    elif group == "network":
        _print_table(records, max_rows=10)
        html_path = _build_network_html(query_id, meta, records)
        if html_path:
            print(f"  Graph → {html_path}")

    elif group == "bar":
        bar_path = _build_bar_chart(query_id, meta, records)
        if bar_path:
            print(f"  Bar chart → {bar_path}")
        _print_table(records, max_rows=10)


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# CLI
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

def _list_queries():
    groups_order = ["table", "network", "bar"]
    by_group: dict[str, list] = {g: [] for g in groups_order}
    for qid, meta in QUERIES.items():
        by_group.setdefault(meta.get("group", "table"), []).append((qid, meta))

    for grp in groups_order:
        items = by_group.get(grp, [])
        if not items:
            continue
        print(f"\n  ── {grp.upper()} queries ──")
        for qid, meta in sorted(items):
            print(f"    {qid:4s}  {meta['name']}")
            print(f"          {meta['description'][:80]}")


def main():
    parser = argparse.ArgumentParser(
        description="Run Knowledge Graph analytical queries and produce visualisations."
    )
    parser.add_argument("--list",   action="store_true",  help="List all available queries")
    parser.add_argument("--all",    action="store_true",  help="Run all queries")
    parser.add_argument("--query",  type=str, metavar="ID",   help="Run a specific query (e.g. Q1)")
    parser.add_argument("--group",  type=str, metavar="GROUP", help="Run all queries in a group (table|network|bar)")
    args = parser.parse_args()

    if args.list:
        print("\nAvailable queries:")
        _list_queries()
        return

    if not (args.all or args.query or args.group):
        parser.print_help()
        return

    driver = get_driver()
    try:
        if args.query:
            run_query(driver, args.query.upper())

        elif args.group:
            ids_in_group = [
                qid for qid, meta in QUERIES.items()
                if meta.get("group") == args.group.lower()
            ]
            if not ids_in_group:
                print(f"[error] No queries found for group '{args.group}'")
            for qid in sorted(ids_in_group):
                run_query(driver, qid)

        elif args.all:
            for qid in sorted(QUERIES.keys()):
                run_query(driver, qid)

    finally:
        driver.close()
        print(f"\n  Outputs written to: {OUTPUT_DIR}\n")


if __name__ == "__main__":
    main()
