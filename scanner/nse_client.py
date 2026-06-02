"""
scanner/nse_client.py
---------------------
Handles fetching market-cap, free-float, and traded-value data.
Uses yfinance fast_info (primary) with info as fallback to bypass
401/403 Akamai blocks and avoid N/A market-cap / traded-value issues.
"""

from __future__ import annotations

import time
import logging

import numpy as np
import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

_EMPTY = {
    "total_market_cap_cr":  np.nan,
    "traded_value_cr":      np.nan,
    "traded_volume":        np.nan,
    "traded_val_pct_mc":    np.nan,
}


def fetch_market_cap(symbol_ns: str) -> dict:
    """
    Fetch market-cap and traded-value for a single NSE symbol.

    Strategy (most-reliable → least):
      1. yf.Ticker.fast_info  — lightweight, rarely blocked
      2. yf.Ticker.info       — full dict, occasionally rate-limited
      3. Last-resort: derive price × shares from history

    All monetary values are converted to ₹ Crores (1 Cr = 10,000,000).
    """
    try:
        ticker = yf.Ticker(symbol_ns)

        # ── 1. fast_info (preferred) ──────────────────────────────────────────
        fi = ticker.fast_info          # always available, no network call per se
        market_cap_raw = getattr(fi, "market_cap", None)
        current_price  = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
        volume         = getattr(fi, "three_month_average_volume", None)  # fallback
        # prefer today's volume
        day_volume     = getattr(fi, "regular_market_volume", None) or getattr(fi, "volume", None)
        if day_volume:
            volume = day_volume
        shares_outstanding = getattr(fi, "shares", None)

        # ── 2. Fall back to info dict if fast_info is sparse ─────────────────
        if not market_cap_raw or not current_price:
            try:
                info = ticker.info
                market_cap_raw = market_cap_raw or info.get("marketCap")
                current_price  = current_price  or info.get("currentPrice") or info.get("regularMarketPrice")
                volume         = volume         or info.get("volume") or info.get("regularMarketVolume")
                shares_outstanding = shares_outstanding or info.get("sharesOutstanding")
            except Exception as info_exc:
                logger.debug("info fallback failed for %s: %s", symbol_ns, info_exc)

        # ── 3. Last resort: derive from recent history ────────────────────────
        if not market_cap_raw or not current_price:
            try:
                hist = ticker.history(period="5d", auto_adjust=True)
                if not hist.empty:
                    current_price = current_price or float(hist["Close"].iloc[-1])
                    volume        = volume        or int(hist["Volume"].iloc[-1])
            except Exception:
                pass

        # ── Compute ₹ Crore figures ───────────────────────────────────────────
        _CR = 10_000_000.0   # 1 Crore = 10,000,000

        total_mc_cr = (float(market_cap_raw) / _CR) if market_cap_raw else np.nan

        # Traded value = volume × last price
        traded_value_cr = np.nan
        if volume and current_price:
            traded_value_cr = (float(volume) * float(current_price)) / _CR

        # TV as % of total market cap (useful liquidity metric)
        traded_val_pct_mc = np.nan
        if not np.isnan(traded_value_cr) and not np.isnan(total_mc_cr) and total_mc_cr > 0:
            traded_val_pct_mc = (traded_value_cr / total_mc_cr) * 100.0

        def _rnd(v, n=2):
            try:
                return round(float(v), n) if not np.isnan(float(v)) else np.nan
            except Exception:
                return np.nan

        return {
            "total_market_cap_cr": _rnd(total_mc_cr),
            "traded_value_cr":     _rnd(traded_value_cr),
            "traded_volume":       int(volume) if volume else np.nan,
            "traded_val_pct_mc":   _rnd(traded_val_pct_mc, 4),
        }

    except Exception as exc:
        logger.error("yfinance fetch error for %s: %s", symbol_ns, exc)
        return _EMPTY.copy()


def enrich_with_market_caps(passing_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market-cap / liquidity columns to *passing_df*.
    Iterates symbols using yfinance; returns an enriched copy.
    """
    if passing_df.empty:
        return passing_df

    logger.info("Fetching Market Cap data via yfinance for %d stocks…", len(passing_df))

    cols: dict[str, list] = {
        "total_market_cap_cr": [],
        "traded_value_cr":     [],
        "traded_volume":       [],
        "traded_val_pct_mc":   [],
    }

    for i, sym in enumerate(passing_df["symbol"], start=1):
        logger.info("  [%d/%d] %s", i, len(passing_df), sym)
        caps = fetch_market_cap(sym)
        for key in cols:
            cols[key].append(caps.get(key, np.nan))
        time.sleep(0.3)   # polite delay to avoid rate-limiting

    out = passing_df.copy()
    for key, values in cols.items():
        out[key] = values

    return out
