"""
Task 10: Merton Distance-to-Default (DTD) — Soft Label Generator
=================================================================
Computes Merton's Distance-to-Default for all 41 NSE-listed Indian banks.
These DTD values are used exclusively as ORDINAL soft labels to orient
the KPCA stress manifold in task11_stress_score.py.

Model parameters (deliberate design choices):
  T  = 0.25  (3-month horizon — short-term rollover risk dominates for banks)
  r  = 0.065 (RBI 91-day T-bill rate, annualised)
  σ_E window = 63 trading days (~1 quarter, consistent with T=0.25)
  Market cap  = 7-calendar-day trailing average (reduces intraday/sentiment noise)
  D  = KMV proxy: Total Deposits + 0.5 * Total Borrowings (ex-deposits)
       Fallback: 0.9 * Total Book Liabilities if breakdown unavailable

Merton Two-Equation System (solved iteratively via KMV):
  E  = V_A * N(d1) - D * exp(-r*T) * N(d2)          ... (BSM call)
  σ_E * E = N(d1) * σ_A * V_A                         ... (Ito's lemma link)
  d1 = [ln(V_A/D) + (r + σ_A^2/2)*T] / (σ_A * sqrt(T))
  d2 = d1 - σ_A * sqrt(T)
  DTD = d2  (Distance to Default)

CRITICAL NOTE ON USAGE:
  We use dtdRank (ordinal ordering) — NOT the absolute implied PD = N(-d2).
  The absolute value is unreliable for banks due to violated normality, but
  the ORDERING is robust and captures relative fundamental + market health.

Output saved to: data_consolidation/data/outputs/merton_soft_labels.json
"""

import os
import sys
import json
import math
import warnings
from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

import numpy as np
import pandas as pd
from scipy.stats import norm
from scipy.optimize import fsolve

# ── Path setup ────────────────────────────────────────────────────────────────
_BANK_SCRIPTS_DIR = os.path.dirname(__file__)
if _BANK_SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, _BANK_SCRIPTS_DIR)

from config import DATA_PATHS, SCB_NSE_TICKER_MAP, _normalize_bank_name

# ── Model Constants ───────────────────────────────────────────────────────────
MERTON_T = 0.25          # 3-month horizon (consistent with 91-day T-bill)
MERTON_r = 0.065         # RBI 91-day T-bill, annualised (as of early 2026)
SIGMA_E_WINDOW = 63      # trading days (≈1 quarter) for annualised volatility
MARKET_CAP_DAYS = 7      # calendar days for rolling average market cap
TRADING_DAYS_PER_YEAR = 252

# ── NSE Ticker Mapping ───────────────────────────────────────────────────────
# Sourced from config.SCB_NSE_TICKER_MAP (canonical allowlist from tier1_cap.csv).
# Keys are CSV bank names (Title Case); lookup against Excel names uses
# _normalize_bank_name() for case-insensitive, suffix-agnostic matching.
NSE_TICKER_MAP: Dict[str, str] = SCB_NSE_TICKER_MAP

# ── Output Path ───────────────────────────────────────────────────────────────
_DATA_CONSOLIDATION_DIR = os.path.dirname(os.path.dirname(_BANK_SCRIPTS_DIR))
OUTPUT_DIR = os.path.join(_DATA_CONSOLIDATION_DIR, "data", "outputs")
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "merton_soft_labels.json")


# ─────────────────────────────────────────────────────────────────────────────
# Market Data Fetching
# ─────────────────────────────────────────────────────────────────────────────

def _import_yfinance():
    """Lazy import yfinance — raises clear error if not installed."""
    try:
        import yfinance as yf
        return yf
    except ImportError:
        raise ImportError(
            "yfinance is required. Install with: pip install yfinance\n"
            "or: pip install -r requirements.txt"
        )


def fetch_market_data(nse_ticker: str) -> Optional[Dict]:
    """
    Fetch equity price history and balance sheet from NSE via yfinance.

    Returns dict with:
      - prices:         pd.Series of adjusted close prices (1-year history)
      - shares_out:     shares outstanding (units)
      - total_deposits: book value of deposits (INR Cr) — may be None
      - total_borrowings: book value of non-deposit borrowings (INR Cr) — may be None
      - total_liabilities: fallback — total book liabilities (INR Cr)

    Returns None if data cannot be fetched (unlisted / delisted / no data).
    """
    yf = _import_yfinance()
    ticker_str = f"{nse_ticker}.NS"

    try:
        ticker = yf.Ticker(ticker_str)

        # --- Price history: 14 months to ensure 63 trading-day window + buffer ---
        end_date = datetime.today()
        start_date = end_date - timedelta(days=430)
        hist = ticker.history(start=start_date.strftime("%Y-%m-%d"),
                               end=end_date.strftime("%Y-%m-%d"),
                               auto_adjust=True)

        if hist.empty or len(hist) < 10:
            return None

        prices = hist["Close"].dropna()
        if len(prices) < 10:
            return None

        # --- Shares outstanding (from ticker.info) ---
        info = ticker.info or {}
        shares_out = info.get("sharesOutstanding") or info.get("impliedSharesOutstanding")

        if not shares_out:
            # Fallback: derive from market cap / price if available
            mkt_cap_raw = info.get("marketCap")
            if mkt_cap_raw and len(prices) > 0:
                shares_out = mkt_cap_raw / float(prices.iloc[-1])
            else:
                return None

        # --- Balance sheet for D (KMV debt proxy) ---
        # yfinance returns values in base currency units (INR for Indian stocks).
        # We convert to INR Crore (1 Cr = 1e7).
        total_deposits = None
        total_borrowings = None
        total_liabilities = None

        try:
            bs = ticker.quarterly_balance_sheet
            if bs is None or bs.empty:
                bs = ticker.balance_sheet

            if bs is not None and not bs.empty:
                # yfinance uses various column names depending on sector
                # For Indian banks it typically reports:
                #   "Total Liabilities Net Minority Interest" or "Total Liabilities"

                def _get_bs_field(df, *keys):
                    for k in keys:
                        matches = [c for c in df.index if k.lower() in c.lower()]
                        if matches:
                            val = df.loc[matches[0]].iloc[0]
                            if pd.notna(val):
                                return float(val) / 1e7  # convert to INR Crore
                    return None

                total_liabilities = _get_bs_field(
                    bs,
                    "Total Liabilities Net Minority Interest",
                    "Total Liabilities",
                    "Total Liab",
                )
                # Attempt to find deposit / borrowing breakdown
                total_deposits = _get_bs_field(
                    bs, "Deposits", "Total Deposits", "Customer Deposits"
                )
                total_borrowings = _get_bs_field(
                    bs, "Borrowings", "Total Borrowings", "Long Term Debt",
                    "Long-term Debt"
                )

        except Exception:
            pass  # Balance sheet fetch failed — will use fallback D

        return {
            "ticker": ticker_str,
            "prices": prices,
            "shares_out": float(shares_out),
            "total_deposits": total_deposits,
            "total_borrowings": total_borrowings,
            "total_liabilities": total_liabilities,
        }

    except Exception as e:
        warnings.warn(f"Failed to fetch market data for {nse_ticker}: {e}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Market Cap & Volatility Computation
# ─────────────────────────────────────────────────────────────────────────────

def compute_market_cap_7d_avg(prices: pd.Series, shares_out: float) -> float:
    """
    7-calendar-day trailing average market cap (INR Crore).
    Uses the last 5 trading days (≈7 calendar days Mon–Fri).
    """
    last_5_prices = prices.iloc[-5:].mean()
    market_cap = last_5_prices * shares_out / 1e7  # INR Crore
    return float(market_cap)


def compute_equity_volatility(prices: pd.Series) -> Optional[float]:
    """
    Annualised equity volatility from 63-day (1-quarter) trailing log returns.
    Consistent with T=0.25: we look at the same horizon as the Merton model.
    Returns None if insufficient data.
    """
    if len(prices) < 65:
        return None
    last_64_prices = prices.iloc[-64:]  # 63 returns from 64 prices
    log_returns = np.log(last_64_prices / last_64_prices.shift(1)).dropna()
    if len(log_returns) < 20:
        return None
    sigma_E = float(log_returns.std() * math.sqrt(TRADING_DAYS_PER_YEAR))
    return sigma_E


# ─────────────────────────────────────────────────────────────────────────────
# KMV Debt Proxy
# ─────────────────────────────────────────────────────────────────────────────

def compute_debt_proxy(total_deposits: Optional[float],
                        total_borrowings: Optional[float],
                        total_liabilities: Optional[float]) -> Optional[float]:
    """
    KMV-style debt proxy for banks (INR Crore):
      D = Total_Deposits + 0.5 * Total_Borrowings_ex_deposits

    Rationale:
      - Deposits are treated as fully "current" (callable on demand in a run).
      - Non-deposit borrowings (bonds, tier-2, interbank) are treated as
        half-weight long-term (KMV practitioners' standard).

    Fallback (if breakdown unavailable):
      D = 0.9 * Total_Book_Liabilities
      (0.9 factor excludes deferred tax / provisions which are not debt-like)
    """
    if total_deposits is not None:
        borrowings = total_borrowings if total_borrowings is not None else 0.0
        return total_deposits + 0.5 * borrowings

    if total_liabilities is not None:
        return 0.9 * total_liabilities

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Merton / KMV Iterative Solver
# ─────────────────────────────────────────────────────────────────────────────

def _merton_equations(params: np.ndarray,
                       E: float, sigma_E: float,
                       D: float, r: float, T: float) -> np.ndarray:
    """
    System of two equations to solve for [V_A, sigma_A]:
      f1: E - (V_A * N(d1) - D * exp(-r*T) * N(d2)) = 0
      f2: sigma_E * E - N(d1) * sigma_A * V_A = 0
    """
    V_A, sigma_A = params[0], params[1]

    if V_A <= 0 or sigma_A <= 0:
        return np.array([1e10, 1e10])

    sqrt_T = math.sqrt(T)
    d1 = (math.log(V_A / D) + (r + 0.5 * sigma_A ** 2) * T) / (sigma_A * sqrt_T)
    d2 = d1 - sigma_A * sqrt_T

    N_d1 = norm.cdf(d1)
    N_d2 = norm.cdf(d2)

    f1 = E - (V_A * N_d1 - D * math.exp(-r * T) * N_d2)
    f2 = sigma_E * E - N_d1 * sigma_A * V_A

    return np.array([f1, f2])


def solve_merton(E: float, sigma_E: float, D: float,
                  r: float = MERTON_r, T: float = MERTON_T) -> Optional[Dict]:
    """
    Solve the Merton model for asset value (V_A) and asset volatility (sigma_A).
    Uses scipy.optimize.fsolve with multiple starting points for robustness.

    Args:
        E:        Market value of equity (INR Crore) — 7-day average
        sigma_E:  Annualised equity volatility (fraction, e.g., 0.35 = 35%)
        D:        Debt proxy — KMV formula (INR Crore)
        r:        Risk-free rate (annualised)
        T:        Time horizon (years) — use 0.25 for 3-month

    Returns dict with: V_A, sigma_A, d1, d2 (DTD), implied_PD
    Returns None if convergence fails.
    """
    if E <= 0 or sigma_E <= 0 or D <= 0:
        return None

    # Initial guess: standard KMV starting point
    V_A_init = E + D
    sigma_A_init = sigma_E * E / V_A_init  # rough lower bound

    best_result = None
    best_residual = np.inf

    # Try multiple starting points to avoid local minima
    for va_mult in [1.0, 1.05, 0.95, 1.1, 0.9]:
        for sa_mult in [1.0, 0.8, 1.2]:
            x0 = np.array([V_A_init * va_mult, sigma_A_init * sa_mult])
            try:
                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")
                    sol, info, ier, _ = fsolve(
                        _merton_equations, x0,
                        args=(E, sigma_E, D, r, T),
                        full_output=True
                    )
                if ier == 1:  # converged
                    residual = np.sum(np.abs(info["fvec"]))
                    if residual < best_residual and sol[0] > 0 and sol[1] > 0:
                        best_residual = residual
                        best_result = sol
            except Exception:
                continue

    if best_result is None or best_residual > 1e-2 * E:
        # Convergence failed — use simplified closed-form approximation
        # V_A ≈ E + D * exp(-r*T), sigma_A ≈ sigma_E * E / (E + D)
        V_A = E + D * math.exp(-r * T)
        sigma_A = sigma_E * E / V_A
        warnings.warn(f"Merton solver did not converge (residual={best_residual:.4f}). "
                       f"Using closed-form approximation.")
    else:
        V_A, sigma_A = best_result[0], best_result[1]

    sqrt_T = math.sqrt(T)
    d1 = (math.log(V_A / D) + (r + 0.5 * sigma_A ** 2) * T) / (sigma_A * sqrt_T)
    d2 = d1 - sigma_A * sqrt_T

    return {
        "assetValue":       round(V_A, 4),
        "assetVolatility":  round(sigma_A, 6),
        "d1":               round(d1, 6),
        "d2":               round(d2, 6),         # This IS the DTD
        "distanceToDefault": round(d2, 6),
        "impliedPD":        round(float(norm.cdf(-d2)), 6),  # N(-d2) — for reference only
        "converged":        bool(best_residual < 1e-2 * E),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Validation: Cross-check Merton Ranks vs NPA Ranks
# ─────────────────────────────────────────────────────────────────────────────

def _validate_merton_vs_npa(results: Dict) -> Dict:
    """
    Spearman rank correlation between DTD rank and Net NPA rank.
    If rho > 0.5, Merton is picking up real fundamental signal.
    If rho < 0.3, it's mostly market noise — downweight in orientation step.

    Loads NPA data from ratios_all_banks.xlsx.
    """
    try:
        from scipy.stats import spearmanr

        df = pd.read_excel(DATA_PATHS["ratios"], sheet_name="Report 1")
        clean = df.iloc[5:].copy()
        clean.columns = clean.iloc[0]
        clean = clean.iloc[1:].reset_index(drop=True)
        clean["Year"] = clean["Year"].ffill()

        # Build NPA lookup for 2025
        npa_lookup = {}
        for _, row in clean[clean["Year"].astype(str).str.strip() == "2025"].iterrows():
            bank_name = str(row.get("Bank", "")).strip()
            npa_val = row.get("35.  Ratio of net NPA To net advances")
            try:
                npa_lookup[bank_name] = float(npa_val)
            except (TypeError, ValueError):
                pass

        # Build a normalised NPA lookup so CSV-keyed results match Excel-named NPA data
        npa_lookup_norm = {_normalize_bank_name(k): v for k, v in npa_lookup.items()}

        # Align banks that have both Merton DTD and NPA
        common = []
        for bank_name, res in results.items():
            bank_norm = _normalize_bank_name(bank_name)
            if res.get("merton") and bank_norm in npa_lookup_norm:
                dtd = res["merton"]["distanceToDefault"]
                npa = npa_lookup_norm[bank_norm]
                if dtd is not None and npa is not None:
                    common.append((bank_name, dtd, npa))

        if len(common) < 5:
            return {"spearmanRho": None, "nCommon": len(common), "interpretation": "insufficient data"}

        dtds = [x[1] for x in common]
        npas = [x[2] for x in common]

        rho, pval = spearmanr(dtds, npas)
        # DTD is inverse of stress, NPA is direct stress
        # so we expect negative rho (higher DTD → lower NPA → less stressed)

        if abs(rho) >= 0.5:
            interp = "STRONG signal: Merton ranks capture fundamental health"
        elif abs(rho) >= 0.3:
            interp = "MODERATE signal: Merton partially captures fundamentals"
        else:
            interp = "WEAK signal: Merton mostly reflects market sentiment — use with caution"

        return {
            "spearmanRho":    round(float(rho), 4),
            "pValue":         round(float(pval), 4),
            "nCommon":        len(common),
            "interpretation": interp,
            # Note: expected negative rho (DTD ↑ ↔ NPA ↓ ↔ less stressed)
            "expectedSign":   "negative (more DTD = less stressed = lower NPA)",
        }

    except Exception as e:
        return {"error": str(e)}


# ─────────────────────────────────────────────────────────────────────────────
# Main: Compute DTD for All Banks
# ─────────────────────────────────────────────────────────────────────────────

def compute_merton_soft_labels(verbose: bool = True) -> Dict:
    """
    Compute Merton DTD for all NSE-listed Indian banks.

    Steps:
      1. Fetch market data for each bank via yfinance
      2. Compute 7-day average market cap and 63-day equity volatility
      3. Compute KMV debt proxy D
      4. Solve Merton two-equation system
      5. Assign ordinal DTD ranks (1 = most stressed, N = least stressed)
      6. Validate ranks via Spearman correlation with Net NPA

    Returns:
        {
          bank_excel_name: {
            "nseTickerUsed": str,
            "marketCap7dAvgCr": float,          # INR Crore
            "equityVolatility63d": float,         # annualised, fraction
            "debtProxy_D_Cr": float,              # INR Crore
            "merton": {
              "assetValue": float,                # V_A (INR Crore)
              "assetVolatility": float,           # sigma_A
              "d1": float,
              "d2": float,                        # DTD
              "distanceToDefault": float,
              "impliedPD": float,                 # N(-d2) — reference only
              "converged": bool,
            },
            "dtdRank": int,                       # 1=most stressed, N=least
            "computedAt": str,
          },
          "_meta": { validation stats, model params, ... }
        }
    """
    results = {}
    failed = []
    compute_time = datetime.now().isoformat()

    total = len(NSE_TICKER_MAP)
    if verbose:
        print(f"\nMerton DTD Computation — {total} banks, T={MERTON_T}, r={MERTON_r}")
        print("=" * 65)

    for i, (bank_name, nse_ticker) in enumerate(NSE_TICKER_MAP.items(), 1):
        if verbose:
            print(f"[{i:02d}/{total}] {nse_ticker:<15} | {bank_name[:45]:<45}", end=" ... ")

        # 1. Fetch market data
        mkt = fetch_market_data(nse_ticker)
        if mkt is None:
            failed.append({"bank": bank_name, "ticker": nse_ticker, "reason": "no market data"})
            if verbose:
                print("SKIP (no data)")
            continue

        # 2. Market cap (7-day avg) and equity volatility (63-day)
        try:
            E = compute_market_cap_7d_avg(mkt["prices"], mkt["shares_out"])
            sigma_E = compute_equity_volatility(mkt["prices"])
        except Exception as e:
            failed.append({"bank": bank_name, "ticker": nse_ticker, "reason": f"computation error: {e}"})
            if verbose:
                print(f"SKIP ({e})")
            continue

        if sigma_E is None or E <= 0:
            failed.append({"bank": bank_name, "ticker": nse_ticker,
                            "reason": "insufficient price history for sigma_E"})
            if verbose:
                print("SKIP (insufficient history)")
            continue

        # 3. KMV Debt proxy
        D = compute_debt_proxy(mkt["total_deposits"], mkt["total_borrowings"], mkt["total_liabilities"])
        if D is None or D <= 0:
            # Last resort: use a leverage estimate (banks typically 10x equity)
            D = E * 10.0
            d_source = "estimated (10x equity — fallback)"
            if verbose:
                print(f"WARN D-fallback", end=" ")
        else:
            d_source = "balance sheet (KMV formula)"

        # 4. Solve Merton
        merton = solve_merton(E, sigma_E, D, r=MERTON_r, T=MERTON_T)
        if merton is None:
            failed.append({"bank": bank_name, "ticker": nse_ticker, "reason": "solver returned None"})
            if verbose:
                print("SKIP (solver failed)")
            continue

        results[bank_name] = {
            "nseTickerUsed":         f"{nse_ticker}.NS",
            "marketCap7dAvgCr":      round(E, 2),
            "equityVolatility63d":   round(sigma_E, 6),
            "debtProxy_D_Cr":        round(D, 2),
            "debtSource":            d_source,
            "merton":                merton,
            "dtdRank":               None,  # assigned after all banks computed
            "computedAt":            compute_time,
        }

        if verbose:
            dtd = merton["distanceToDefault"]
            pd_val = merton["impliedPD"]
            print(f"DTD={dtd:+.3f}  PD={pd_val:.4f}  E={E:.0f}Cr  sigmaE={sigma_E:.3f}")

    # 5. Assign ordinal DTD ranks (1 = lowest DTD = most stressed)
    ranked = sorted(
        [(k, v["merton"]["distanceToDefault"]) for k, v in results.items()],
        key=lambda x: x[1]  # ascending: lower DTD → higher stress → lower rank number
    )
    for rank, (bank_name, _) in enumerate(ranked, 1):
        results[bank_name]["dtdRank"] = rank

    # Build dtdRankMap for downstream use
    dtd_rank_map = {k: v["dtdRank"] for k, v in results.items()}

    # 6. Validate vs NPA
    if verbose:
        print("\nValidating Merton ranks against Net NPA ratios...")
    validation = _validate_merton_vs_npa(results)

    # Meta
    results["_meta"] = {
        "modelParams": {
            "T":                  MERTON_T,
            "r":                  MERTON_r,
            "sigmaE_window_days": SIGMA_E_WINDOW,
            "marketCap_avg_days": MARKET_CAP_DAYS,
            "debtFormula":        "Deposits + 0.5*Borrowings (KMV); fallback: 0.9*TotalLiabilities",
        },
        "totalBanks":      total,
        "computed":        len(results) - 1,  # subtract _meta
        "failed":          failed,
        "dtdRankMap":      dtd_rank_map,
        "validation":      validation,
        "computedAt":      compute_time,
    }

    if verbose:
        n_ok = len(results) - 1
        print(f"\nCompleted: {n_ok} banks computed, {len(failed)} skipped")
        print(f"Most stressed (lowest DTD):  "
              f"{ranked[0][0]} (DTD={ranked[0][1]:+.3f})")
        print(f"Least stressed (highest DTD): "
              f"{ranked[-1][0]} (DTD={ranked[-1][1]:+.3f})")
        print(f"\nValidation: Merton vs NPA Spearman rho = "
              f"{validation.get('spearmanRho', 'N/A')}  "
              f"({validation.get('interpretation', 'N/A')})")

    # Save output
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    _save_results(results)

    return results


def _save_results(results: Dict):
    """Serialise results to JSON (converts non-serialisable types)."""
    def _serialise(obj):
        if isinstance(obj, (np.integer,)):
            return int(obj)
        if isinstance(obj, (np.floating,)):
            return float(obj)
        if isinstance(obj, (np.bool_,)):
            return bool(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, pd.Series):
            return obj.tolist()
        raise TypeError(f"Object of type {type(obj)} is not JSON serialisable")

    # Strip pandas Series from the saved output
    clean = {}
    for k, v in results.items():
        if isinstance(v, dict):
            clean[k] = {kk: vv for kk, vv in v.items() if kk != "prices"}
        else:
            clean[k] = v

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(clean, f, indent=2, default=_serialise)

    print(f"\nSaved: {OUTPUT_FILE}")


def load_merton_soft_labels() -> Optional[Dict]:
    """Load previously computed Merton soft labels from disk."""
    if not os.path.exists(OUTPUT_FILE):
        return None
    with open(OUTPUT_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


# ─────────────────────────────────────────────────────────────────────────────
# Entry Point
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    results = compute_merton_soft_labels(verbose=True)

    # Print rank table
    print("\n" + "=" * 65)
    print(f"{'RANK':<6} {'BANK':<45} {'DTD':>8}  {'Impl.PD':>8}")
    print("-" * 65)
    meta = results.get("_meta", {})
    ranked_banks = sorted(
        [(k, v) for k, v in results.items() if k != "_meta"],
        key=lambda x: x[1].get("dtdRank", 999)
    )
    for bank_name, data in ranked_banks:
        dtd = data["merton"]["distanceToDefault"]
        pd_val = data["merton"]["impliedPD"]
        rank = data["dtdRank"]
        print(f"{rank:<6} {bank_name[:44]:<45} {dtd:>+8.3f}  {pd_val:>8.4f}")
