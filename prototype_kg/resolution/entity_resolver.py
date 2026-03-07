"""
prototype_kg/resolution/entity_resolver.py

4-pass entity name resolution pipeline, unified through a GlobalEntityRegistry (GER).

The GER is built once per pipeline run from all bank + company documents and
shared across every node/edge builder.  It resolves a free-text name to one of:
  ("Bank",    bankSymbol, confidence)
  ("Company", cin,        confidence)
  (None,      None,       0.0)           ← create a :Shareholder stub

Resolution passes:
  Pass 1 — Canonical exact match (bank name variants and CIN/crisilName/mcaName indexes)
  Pass 2 — Normalised exact match (strip suffixes, punctuation, collapse whitespace)
  Pass 3 — Company fuzzy: token_set_ratio (threshold ≥ 88) + generic-token veto + identity anchor
  Pass 4 — Abbreviation expansion (bank short-codes like SBI, HDFC, ICICI)

Bank matching is intentionally exact-only (Passes 1, 2, 4). No substring or fuzzy
matching is attempted for banks so that subsidiary/foreign entities like
"State Bank of India (UK) Limited" or "SBI-SG Global Securities" are never
resolved to the parent bank node.

The generic-token veto prevents false positives caused by common suffixes like
"International Private Limited" matching unrelated entities.

Public API:
    GlobalEntityRegistry(bank_docs, company_docs)
        .resolve(name) → (node_type | None, canonical_id | None, confidence: float)
        .company_index  → {normalized_name: cin}   (for backwards-compat callers)
        .company_by_cin → {cin: doc}

    # Legacy thin wrappers (kept for callers not yet updated):
    resolve_to_bank(name) → (bankSymbol | None, confidence: float)
    resolve_to_company(name, company_index) → (cin | None, confidence: float, candidates)
"""

from __future__ import annotations
import logging
import os
import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz, process
from config import BANK_NAME_TO_SYMBOL, BANK_REGISTRY, GENERIC_NAME_TOKENS

# ---------------------------------------------------------------------------
# Resolution logger
# Disabled by default (no handlers).  Call configure_resolution_logging() once
# at pipeline startup to write a detailed trace to a log file.
# ---------------------------------------------------------------------------

_res_logger = logging.getLogger("prototype_kg.resolution")
_res_logger.setLevel(logging.DEBUG)
_res_logger.propagate = False   # don't forward to the root logger

_LOG_SEP = "─" * 72


def configure_resolution_logging(
    log_file: str | None = None,
    level: int = logging.DEBUG,
    *,
    to_console: bool = False,
) -> str:
    """
    Enable per-call resolution tracing.

    Call this once before running the KG pipeline.  Each call to
    ``GER.resolve()`` will append a block like:

        ────────────────────────────────────────────────────────────────────────
        RESOLVE  "HDFC Bank Limited"
          norm1  : "hdfc bank limited"
          norm2  : "hdfc bank "
          Pass 1  exact bank   : HIT → HDFCBANK
          → ACCEPTED  Bank / HDFCBANK  (conf=1.0)

    Args:
        log_file:   Path for the log file.  Defaults to
                    ``prototype_kg/logs/resolution.log``.
        level:      Python logging level (default DEBUG = all passes).
        to_console: Also echo entries to stdout.

    Returns:
        Absolute path of the log file being written.
    """
    if log_file is None:
        _pkg_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        logs_dir = os.path.join(_pkg_dir, "logs")
        os.makedirs(logs_dir, exist_ok=True)
        log_file = os.path.join(logs_dir, "resolution.log")
    else:
        _dir = os.path.dirname(os.path.abspath(log_file))
        if _dir:
            os.makedirs(_dir, exist_ok=True)

    _fmt = logging.Formatter("%(message)s")

    _fh = logging.FileHandler(log_file, encoding="utf-8", mode="a")
    _fh.setLevel(level)
    _fh.setFormatter(_fmt)
    _res_logger.addHandler(_fh)

    if to_console:
        _ch = logging.StreamHandler()
        _ch.setLevel(level)
        _ch.setFormatter(_fmt)
        _res_logger.addHandler(_ch)

    _res_logger.info(
        f"\n{'='*72}\n"
        f"[GER] Resolution logging started  →  {log_file}\n"
        f"{'='*72}"
    )
    return log_file

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

FUZZY_THRESHOLD           = 88    # min token_set_ratio score to accept a match
FUZZY_SORT_THRESHOLD      = 72    # min token_sort_ratio score (both must pass)
                                  # prevents subset-name false positives, e.g.
                                  # "Rane (Madras)" vs "Rane Holdings"
ABBREV_MAX_LEN            = 6     # names ≤ this length + all-uppercase → abbreviation
GENERIC_OVERLAP_THRESHOLD = 0.60  # veto if > this fraction of shared tokens are generic

# Legal/form suffixes to strip before normalised exact match
_SUFFIX_RE = re.compile(
    r"\b(ltd|limited|pvt|private|inc|incorporated|corp|corporation|"
    r"co|company|llp|llc|plc|ag|sa|nv|bv)\b\.?",
    re.IGNORECASE,
)

# Characters to collapse to a single space
_PUNCT_RE = re.compile(r"[&\-–,.\(\)/\\]+")

# Bank abbreviation table extended dynamically from BANK_REGISTRY in GER.__init__
_STATIC_BANK_ABBREVIATIONS: dict[str, str] = {
    "SBI":   "SBIN",
    "HDFC":  "HDFCBANK",
    "ICICI": "ICICIBANK",
}


# ---------------------------------------------------------------------------
# Normalisation helpers (module-level so they can be used standalone)
# ---------------------------------------------------------------------------

def _normalize(name: str) -> str:
    """Full normalization: lowercase → strip punctuation → strip legal suffixes → collapse whitespace."""
    n = name.lower()
    n = _PUNCT_RE.sub(" ", n)
    n = _SUFFIX_RE.sub(" ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def _is_abbreviation(name: str) -> bool:
    return len(name) <= ABBREV_MAX_LEN and name.isupper()


def _identity_anchor(norm: str) -> str | None:
    """
    Return the first distinctive (non-generic) token from a normalised name.
    Splits on whitespace AND hyphens so that compound prefixes like 'sbi-sg'
    yield 'sbi' rather than 'sbi-sg' as a single indivisible token.
    Returns None when every token is generic — no reliable anchor exists,
    so fuzzy matching should be skipped entirely to avoid false positives.
    """
    tokens = re.split(r"[\s\-]+", norm)
    for t in tokens:
        if _is_distinctive_token(t):
            return t
    return None


# ---------------------------------------------------------------------------
# Generic-token overlap veto
# ---------------------------------------------------------------------------

def _is_distinctive_token(token: str) -> bool:
    """A token is distinctive if it is NOT in the generic stop-list and is longer than 1 char."""
    return len(token) > 1 and token not in GENERIC_NAME_TOKENS


def _generic_overlap_veto(norm_a: str, norm_b: str) -> bool:
    """
    Return True (veto) when the names share no distinctive tokens, or when
    more than GENERIC_OVERLAP_THRESHOLD of the shared tokens are generic.

    Prevents spurious matches like:
      "D D International Private Ltd" ↔ "XYZ International Private Ltd"
    where the only shared tokens are all in the generic stop-list.
    """
    tokens_a = set(norm_a.split())
    tokens_b = set(norm_b.split())
    shared   = tokens_a & tokens_b

    if not shared:
        return False

    generic_count = sum(1 for t in shared if not _is_distinctive_token(t))

    if generic_count == len(shared):
        return True

    if generic_count / len(shared) > GENERIC_OVERLAP_THRESHOLD:
        return True

    # Both sides must have at least one distinctive token
    distinctive_a = {t for t in tokens_a if _is_distinctive_token(t)}
    distinctive_b = {t for t in tokens_b if _is_distinctive_token(t)}
    if not distinctive_a or not distinctive_b:
        return True

    return False


# ---------------------------------------------------------------------------
# Global Entity Registry
# ---------------------------------------------------------------------------

class GlobalEntityRegistry:
    """
    Central entity resolution registry built once per pipeline run.

    Indexes:
      _bank_index       : {normalized_name: bankSymbol}   — from BANK_REGISTRY.nameVariants
      _company_index    : {normalized_name: cin}           — from crisilName + mcaName
      company_by_cin    : {cin: doc}                       — full company doc lookup
      _abbreviations    : {UPPER_ABBREV: bankSymbol}

    resolve(name) → (node_type, canonical_id, confidence)
      node_type ∈ {"Bank", "Company", None}
      canonical_id: bankSymbol, cin, or None
    """

    def __init__(self, bank_docs: list[dict], company_docs: list[dict]) -> None:
        # ── Bank index ───────────────────────────────────────────────────────
        self._bank_index: dict[str, str] = dict(BANK_NAME_TO_SYMBOL)  # copy
        # Also add normalized bankName from each bank doc (covers runtime additions)
        for doc in bank_docs:
            sym  = doc.get("bankSymbol", "")
            name = doc.get("bankName", "")
            if sym and name:
                self._bank_index[name.lower().strip()] = sym
                self._bank_index[_normalize(name)]     = sym

        # ── Abbreviation table ──────────────────────────────────────────────
        self._abbreviations: dict[str, str] = dict(_STATIC_BANK_ABBREVIATIONS)
        for sym, data in BANK_REGISTRY.items():
            # Use the bankSymbol itself as a potential abbreviation key
            if len(sym) <= ABBREV_MAX_LEN:
                self._abbreviations[sym.upper()] = sym

        # ── Company index (keyed by CIN) ────────────────────────────────────
        self._company_index: dict[str, str] = {}   # normalized_name → cin
        self.company_by_cin: dict[str, dict] = {}  # cin → doc
        self.companycode_to_cin: dict[str, str] = {}  # companyCode → cin (for lends_to bridge)

        for doc in company_docs:
            cin = str(doc.get("cin") or "").strip()
            if not cin:
                continue

            self.company_by_cin[cin] = doc

            # Bridge: companyCode → cin
            code = str(doc.get("companyCode") or "").strip()
            if code:
                self.companycode_to_cin[code] = cin

            # Index all name variants that point to this CIN
            for field_name in ("crisilName", "mcaName"):
                raw = str(doc.get(field_name) or "").strip()
                if raw:
                    self._company_index[raw.lower().strip()] = cin
                    self._company_index[_normalize(raw)]     = cin

        # Pre-build sorted list of company index keys for fuzzy search
        self._company_keys: list[str] = sorted(self._company_index.keys())

        total_banks     = len({v for v in self._bank_index.values()})
        total_companies = len(self.company_by_cin)
        print(
            f"[GER] Registry built: {total_banks} bank(s), "
            f"{total_companies} company doc(s), "
            f"{len(self._company_index)} name→CIN entries, "
            f"{len(self.companycode_to_cin)} companyCode→CIN entries."
        )

    # ── Public property for backwards-compat callers ─────────────────────
    @property
    def company_index(self) -> dict[str, str]:
        """Return the {normalized_name: cin} index."""
        return self._company_index

    # ── Core resolution ───────────────────────────────────────────────────

    def resolve(
        self,
        name: str,
        *,
        top_candidates: int = 3,
    ) -> tuple[str | None, str | None, float]:
        """
        Resolve a free-text entity name.

        Returns:
            ("Bank",    bankSymbol, confidence)   — entity is a target bank
            ("Company", cin,        confidence)   — entity matched a company doc
            (None,      None,       0.0)          — unresolved; caller creates :Shareholder
        """
        if not name or not name.strip():
            return None, None, 0.0

        _log = _res_logger.isEnabledFor(logging.DEBUG)
        trace: list[str] = []

        norm  = name.lower().strip()
        norm2 = _normalize(name)

        if _log:
            trace.append(_LOG_SEP)
            trace.append(f'RESOLVE  "{name}"')
            trace.append(f'  norm1  : "{norm}"')
            trace.append(f'  norm2  : "{norm2}"')

        # ── Pass 1: exact bank lookup ───────────────────────────────────────
        sym = self._bank_index.get(norm) or self._bank_index.get(norm2)
        if sym:
            if _log:
                trace.append(f"  Pass 1  exact bank   : HIT \u2192 {sym}")
                trace.append(f"  \u2192 ACCEPTED  Bank / {sym}  (conf=1.0)")
                _res_logger.debug("\n".join(trace))
            return "Bank", sym, 1.0

        if _log:
            trace.append("  Pass 1  exact bank   : miss")

        # ── Pass 2: exact company lookup ────────────────────────────────────
        cin = self._company_index.get(norm) or self._company_index.get(norm2)
        if cin:
            if _log:
                trace.append(f"  Pass 2  exact company: HIT \u2192 {cin}")
                trace.append(f"  \u2192 ACCEPTED  Company / {cin}  (conf=1.0)")
                _res_logger.debug("\n".join(trace))
            return "Company", cin, 1.0

        if _log:
            trace.append("  Pass 2  exact company: miss")

        # ── Pass 3: fuzzy company — dual-ratio gate + generic-token veto + identity anchor ────
        # Identity anchor gate: find the first distinctive token in the query name.
        # If no anchor exists (all tokens are generic) skip fuzzy entirely — a stub
        # is safer than a false match. If an anchor is found, the best candidate
        # must contain that anchor as a substring before scores are even checked.
        if self._company_keys:
            anchor = _identity_anchor(norm2)
            if _log:
                if anchor:
                    trace.append(f"  Pass 3  fuzzy company: anchor='{anchor}'")
                else:
                    trace.append("  Pass 3  fuzzy company: anchor=None — all-generic name, skipped")

            if anchor is not None:
                results = process.extract(
                    norm2,
                    self._company_keys,
                    scorer=fuzz.token_set_ratio,
                    limit=top_candidates,
                )

                if _log:
                    if results:
                        trace.append(f"    candidates (token_set_ratio, top {len(results)}):")
                        for _rn, _rs, _ in results:
                            _marker = "  " if _rs < FUZZY_THRESHOLD else "* "
                            trace.append(f"      {_marker}[{int(_rs):3d}] {repr(_rn)}")
                    else:
                        trace.append("    no candidates returned")

                if results and results[0][1] >= FUZZY_THRESHOLD:
                    best_norm, best_score, _ = results[0]
                    sort_score = fuzz.token_sort_ratio(norm2, best_norm)
                    veto       = _generic_overlap_veto(norm2, best_norm)
                    anchor_ok  = anchor in best_norm

                    if _log:
                        trace.append(f"    top candidate: {repr(best_norm)}")
                        trace.append(
                            f"      token_set_ratio : {int(best_score):3d}  "
                            f"(threshold {FUZZY_THRESHOLD}) "
                            f"{'PASS' if best_score >= FUZZY_THRESHOLD else 'FAIL'}"
                        )
                        trace.append(
                            f"      token_sort_ratio: {int(sort_score):3d}  "
                            f"(threshold {FUZZY_SORT_THRESHOLD}) "
                            f"{'PASS' if sort_score >= FUZZY_SORT_THRESHOLD else 'FAIL'}"
                        )
                        trace.append(
                            f"      generic veto    : {'TRIGGERED' if veto else 'clear'}"
                        )
                        trace.append(
                            f"      anchor in cand  : {anchor_ok}  "
                            f"('{anchor}' in {repr(best_norm)})"
                        )

                    if sort_score >= FUZZY_SORT_THRESHOLD and not veto and anchor_ok:
                        cin_match = self._company_index[best_norm]
                        if _log:
                            trace.append(
                                f"  \u2192 ACCEPTED  Company / {cin_match}  "
                                f"(conf={best_score/100:.2f})"
                            )
                            _res_logger.debug("\n".join(trace))
                        return "Company", cin_match, best_score / 100

                    if _log:
                        reasons: list[str] = []
                        if sort_score < FUZZY_SORT_THRESHOLD:
                            reasons.append(
                                f"sort_ratio {int(sort_score)} < {FUZZY_SORT_THRESHOLD}"
                            )
                        if veto:
                            reasons.append("generic-token veto")
                        if not anchor_ok:
                            reasons.append(f"anchor '{anchor}' not in candidate")
                        trace.append(f"    \u2192 REJECTED  ({'; '.join(reasons)})")

                elif _log:
                    top_score = results[0][1] if results else 0
                    trace.append(
                        f"    top score {top_score} below threshold {FUZZY_THRESHOLD}"
                        " — no match"
                    )

        if _log:
            trace.append("  Pass 3  fuzzy company: no match")

        # ── Pass 4: abbreviation expansion ──────────────────────────────────
        # Secondary guard: hyphenated names like 'SBI-SG' are compound identifiers,
        # not abbreviations — expanding them to a bank symbol would be wrong.
        if _is_abbreviation(name.strip()) and "-" not in name:
            expanded_sym = self._abbreviations.get(name.strip().upper())
            if _log:
                trace.append(
                    f"  Pass 4  abbreviation : '{name.strip()}' "
                    f"\u2192 {expanded_sym or 'no match in table'}"
                )
            if expanded_sym:
                if _log:
                    trace.append(
                        f"  \u2192 ACCEPTED  Bank / {expanded_sym}  (conf=0.9)"
                    )
                    _res_logger.debug("\n".join(trace))
                return "Bank", expanded_sym, 0.9
        elif _log:
            trace.append(
                f"  Pass 4  abbreviation : '{name.strip()}' "
                "— not a short uppercase token, skipped"
            )

        if _log:
            trace.append("  \u2192 UNRESOLVED  (Shareholder stub)")
            _res_logger.debug("\n".join(trace))
        return None, None, 0.0

    def resolve_with_candidates(
        self,
        name: str,
        *,
        top_candidates: int = 3,
    ) -> tuple[str | None, str | None, float, list[dict]]:
        """
        Same as resolve() but also returns top fuzzy candidates for unresolved nodes.

        Returns:
            (node_type, canonical_id, confidence, candidates)
            candidates: list of {normalizedName, cin, score}
        """
        if not name or not name.strip():
            return None, None, 0.0, []

        norm2 = _normalize(name)
        candidates: list[dict] = []

        # Run standard resolution first
        node_type, canonical_id, confidence = self.resolve(
            name, top_candidates=top_candidates
        )
        if node_type is not None:
            return node_type, canonical_id, confidence, []

        # Build candidates list from fuzzy company search (for unresolved stubs)
        if self._company_keys:
            results = process.extract(
                norm2,
                self._company_keys,
                scorer=fuzz.token_set_ratio,
                limit=top_candidates,
            )
            candidates = [
                {
                    "normalizedName": r[0],
                    "cin":            self._company_index.get(r[0], ""),
                    "score":          r[1],
                }
                for r in results
            ]

        return None, None, 0.0, candidates


# ---------------------------------------------------------------------------
# Legacy standalone helpers (thin wrappers — kept for callers not yet updated)
# ---------------------------------------------------------------------------

def build_company_index(bank_docs: list[dict]) -> dict[str, str]:
    """
    Legacy: build {normalized_name: companyCode/cin} from advances.companies.
    Prefer using GlobalEntityRegistry.company_index for new code.
    """
    index: dict[str, str] = {}
    for doc in bank_docs:
        for company in doc.get("advances", {}).get("companies", []):
            code = company.get("companyCode") or company.get("cin")
            name = company.get("companyName", "")
            if code and name:
                index[_normalize(name)] = code
    return index


def resolve_to_bank(name: str) -> tuple[str | None, float]:
    """
    Legacy: resolve a name to a bankSymbol using BANK_NAME_TO_SYMBOL only.
    Prefer GlobalEntityRegistry.resolve() for new code.
    """
    if not name or not name.strip():
        return None, 0.0

    norm  = name.lower().strip()
    norm2 = _normalize(name)

    sym = BANK_NAME_TO_SYMBOL.get(norm) or BANK_NAME_TO_SYMBOL.get(norm2)
    if sym:
        return sym, 1.0

    all_variants = list(BANK_NAME_TO_SYMBOL.keys())
    result = process.extractOne(norm2, all_variants, scorer=fuzz.token_set_ratio)
    if result and result[1] >= FUZZY_THRESHOLD:
        return BANK_NAME_TO_SYMBOL[result[0]], result[1] / 100

    if _is_abbreviation(name.strip()):
        expanded = _STATIC_BANK_ABBREVIATIONS.get(name.strip().upper())
        if expanded:
            return expanded, 0.9

    return None, 0.0


def resolve_to_company(
    name: str,
    company_index: dict[str, str],
    *,
    top_candidates: int = 3,
) -> tuple[str | None, float, list[dict]]:
    """
    Legacy: resolve a name to a cin using the provided company_index.
    Prefer GlobalEntityRegistry.resolve_with_candidates() for new code.
    """
    if not name or not name.strip():
        return None, 0.0, []

    norm2 = _normalize(name)
    candidates: list[dict] = []

    if norm2 in company_index:
        return company_index[norm2], 1.0, []

    if company_index:
        results = process.extract(
            norm2,
            list(company_index.keys()),
            scorer=fuzz.token_set_ratio,
            limit=top_candidates,
        )
        candidates = [
            {"normalizedName": r[0], "cin": company_index[r[0]], "score": r[1]}
            for r in results
        ]
        if results and results[0][1] >= FUZZY_THRESHOLD:
            best_norm, best_score, _ = results[0][0], results[0][1], None
            if not _generic_overlap_veto(norm2, best_norm):
                return company_index[best_norm], best_score / 100, candidates

    if _is_abbreviation(name.strip()):
        expanded = _STATIC_BANK_ABBREVIATIONS.get(name.strip().upper())
        if expanded:
            norm_exp = _normalize(expanded)
            if norm_exp in company_index:
                return company_index[norm_exp], 0.9, candidates

    return None, 0.0, candidates
