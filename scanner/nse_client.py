"""
scanner/nse_client.py
---------------------
Handles fetching market-cap, free-float, and traded-value data.

Primary source: yfinance fast_info (with .info as a secondary fallback).
Yahoo Finance is frequently rate-limited or blocked from shared/CI IPs
(GitHub Actions runners in particular), which previously showed up as
every stock's market-cap / traded-value coming back "N/A" with no
retry and no alternate source. This version adds:

  1. A short retry-with-backoff around the yfinance fetch, since most
     Yahoo blocks are transient (a 429/999 that succeeds a few seconds
     later), rather than permanent.
  2. A same-day fallback to NSE India's own quote API (via `jugaad_data`,
     already a project dependency) when yfinance still comes back empty.
     This uses NSE's official `NSE_HEADERS`/`NSE_REQUEST_DELAY` config
     (previously defined but unused) and is inherently more reliable for
     NSE-listed symbols since it's the exchange's own data, not a
     third-party scrape.

Both paths are independent and defensive — if one fails/errors for any
reason, the other still has a chance to fill in the numbers, and if both
fail the columns are NaN (rendered as "N/A") exactly as before, so this
is purely additive resilience with no new hard dependency on either
source being up.
"""

from __future__ import annotations

import logging
import random
import time

import numpy as np
import pandas as pd
import yfinance as yf

from .config import NSE_REQUEST_DELAY

logger = logging.getLogger(__name__)

_EMPTY = {
    "total_market_cap_cr":  np.nan,
    "traded_value_cr":      np.nan,
    "traded_volume":        np.nan,
    "traded_val_pct_mc":    np.nan,
}

_CR = 10_000_000.0   # 1 Crore = 10,000,000

# ── NSE fallback client (lazy singleton — only created if actually needed) ────
_nse_live = None


def _get_nse_live():
    """Lazily create (and cache) a single jugaad_data NSELive client."""
    global _nse_live
    if _nse_live is None:
        try:
            from jugaad_data.nse import NSELive
            _nse_live = NSELive()
        except Exception as exc:
            logger.warning("Could not initialize NSE fallback client: %s", exc)
            _nse_live = False   # sentinel: don't keep retrying construction
    return _nse_live or None


def _rnd(v, n=2):
    try:
        f = float(v)
        return round(f, n) if not np.isnan(f) else np.nan
    except Exception:
        return np.nan


def _is_complete(caps: dict) -> bool:
    """True if we already have both market cap and traded value."""
    mc = caps.get("total_market_cap_cr")
    tv = caps.get("traded_value_cr")
    return (mc is not None and not (isinstance(mc, float) and np.isnan(mc))) and \
           (tv is not None and not (isinstance(tv, float) and np.isnan(tv)))


# ── 1. yfinance (primary) ──────────────────────────────────────────────────────

def _fetch_from_yfinance(symbol_ns: str, attempts: int = 2) -> dict:
    """
    Fetch market-cap and traded-value for a single NSE symbol via yfinance.

    Strategy (most-reliable → least):
      1. yf.Ticker.fast_info  — lightweight, rarely blocked
      2. yf.Ticker.info       — full dict, occasionally rate-limited
      3. Last-resort: derive price × shares from history

    Retries up to `attempts` times with a short randomized backoff, since
    Yahoo rate-limit/blocks (HTTP 429/999) are usually transient.
    """
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            ticker = yf.Ticker(symbol_ns)

            # ── fast_info (preferred) ──────────────────────────────────────
            fi = ticker.fast_info
            market_cap_raw = getattr(fi, "market_cap", None)
            current_price  = getattr(fi, "last_price", None) or getattr(fi, "regular_market_price", None)
            volume         = getattr(fi, "three_month_average_volume", None)  # fallback
            day_volume     = getattr(fi, "regular_market_volume", None) or getattr(fi, "volume", None)
            if day_volume:
                volume = day_volume
            shares_outstanding = getattr(fi, "shares", None)

            # ── fall back to info dict if fast_info is sparse ──────────────
            if not market_cap_raw or not current_price:
                try:
                    info = ticker.info
                    market_cap_raw = market_cap_raw or info.get("marketCap")
                    current_price  = current_price  or info.get("currentPrice") or info.get("regularMarketPrice")
                    volume         = volume         or info.get("volume") or info.get("regularMarketVolume")
                    shares_outstanding = shares_outstanding or info.get("sharesOutstanding")
                except Exception as info_exc:
                    logger.debug("info fallback failed for %s: %s", symbol_ns, info_exc)

            # ── last resort: derive from recent history ────────────────────
            if not market_cap_raw or not current_price:
                try:
                    hist = ticker.history(period="5d", auto_adjust=True)
                    if not hist.empty:
                        current_price = current_price or float(hist["Close"].iloc[-1])
                        volume        = volume        or int(hist["Volume"].iloc[-1])
                except Exception:
                    pass

            total_mc_cr = (float(market_cap_raw) / _CR) if market_cap_raw else np.nan

            traded_value_cr = np.nan
            if volume and current_price:
                traded_value_cr = (float(volume) * float(current_price)) / _CR

            traded_val_pct_mc = np.nan
            if not np.isnan(traded_value_cr) and not np.isnan(total_mc_cr) and total_mc_cr > 0:
                traded_val_pct_mc = (traded_value_cr / total_mc_cr) * 100.0

            result = {
                "total_market_cap_cr": _rnd(total_mc_cr),
                "traded_value_cr":     _rnd(traded_value_cr),
                "traded_volume":       int(volume) if volume else np.nan,
                "traded_val_pct_mc":   _rnd(traded_val_pct_mc, 4),
            }

            if _is_complete(result) or attempt == attempts:
                return result

            # Incomplete but attempts remain — likely a transient block; retry.
            logger.debug("yfinance incomplete for %s (attempt %d/%d) — retrying",
                         symbol_ns, attempt, attempts)

        except Exception as exc:
            last_exc = exc
            logger.debug("yfinance fetch error for %s (attempt %d/%d): %s",
                         symbol_ns, attempt, attempts, exc)

        if attempt < attempts:
            time.sleep(0.6 * attempt + random.uniform(0, 0.4))   # short randomized backoff

    if last_exc:
        logger.warning("yfinance fetch failed for %s after %d attempts: %s", symbol_ns, attempts, last_exc)
    return _EMPTY.copy()


# ── 2. NSE India quote API (fallback) ──────────────────────────────────────────

def _fetch_from_nse(symbol_ns: str) -> dict:
    """
    Fetch market-cap and traded-value straight from NSE India's own
    quote-equity API (via jugaad_data's NSELive), which mirrors what
    https://www.nseindia.com/get-quotes/equity?symbol=... shows.

    Market cap  = last traded price × issued share capital.
    Traded value = NSE's own reported total traded value for the day
                   (no need to derive it — NSE publishes it directly).
    """
    nse = _get_nse_live()
    if nse is None:
        return _EMPTY.copy()

    sym = symbol_ns.replace(".NS", "").strip().upper()
    try:
        q = nse.stock_quote(sym)
        if not isinstance(q, dict):
            return _EMPTY.copy()

        price_info    = q.get("priceInfo", {}) or {}
        security_info = q.get("securityInfo", {}) or {}
        trade_info    = ((q.get("marketDeptOrderBook", {}) or {}).get("tradeInfo", {})) or {}

        last_price   = price_info.get("lastPrice")
        issued_size  = security_info.get("issuedSize")
        total_value  = trade_info.get("totalTradedValue")    # NSE reports this in ₹ Lakhs
        total_volume = trade_info.get("totalTradedVolume")

        total_mc_cr = np.nan
        if last_price and issued_size:
            total_mc_cr = (float(last_price) * float(issued_size)) / _CR

        traded_value_cr = np.nan
        if total_value:
            # NSE reports totalTradedValue in ₹ Lakhs — convert Lakhs → Crores.
            traded_value_cr = float(total_value) / 100.0

        traded_val_pct_mc = np.nan
        if not np.isnan(traded_value_cr) and not np.isnan(total_mc_cr) and total_mc_cr > 0:
            traded_val_pct_mc = (traded_value_cr / total_mc_cr) * 100.0

        return {
            "total_market_cap_cr": _rnd(total_mc_cr),
            "traded_value_cr":     _rnd(traded_value_cr),
            "traded_volume":       int(total_volume) if total_volume else np.nan,
            "traded_val_pct_mc":   _rnd(traded_val_pct_mc, 4),
        }

    except Exception as exc:
        logger.debug("NSE quote fallback failed for %s: %s", sym, exc)
        return _EMPTY.copy()


# ── Public API ──────────────────────────────────────────────────────────────────

def fetch_market_cap(symbol_ns: str) -> dict:
    """
    Fetch market-cap and traded-value for a single NSE symbol.
    Tries yfinance first (with retries); if that comes back incomplete,
    fills in any missing fields from NSE India's own quote API.
    """
    result = _fetch_from_yfinance(symbol_ns)

    if not _is_complete(result):
        nse_result = _fetch_from_nse(symbol_ns)
        # Fill in only what's still missing — prefer whichever source answered.
        for key, val in nse_result.items():
            existing = result.get(key)
            existing_missing = existing is None or (isinstance(existing, float) and np.isnan(existing))
            if existing_missing and val is not None and not (isinstance(val, float) and np.isnan(val)):
                result[key] = val
        time.sleep(NSE_REQUEST_DELAY)   # be polite to NSE's servers when we do hit them

    return result


def enrich_with_market_caps(passing_df: pd.DataFrame) -> pd.DataFrame:
    """
    Add market-cap / liquidity columns to *passing_df*.
    Iterates symbols using yfinance (falling back to NSE's own API per
    symbol when needed); returns an enriched copy.
    """
    if passing_df.empty:
        return passing_df

    logger.info("Fetching market-cap data for %d stocks…", len(passing_df))

    cols: dict[str, list] = {
        "total_market_cap_cr": [],
        "traded_value_cr":     [],
        "traded_volume":       [],
        "traded_val_pct_mc":   [],
    }

    for i, sym in enumerate(passing_df["symbol"], start=1):
        caps = fetch_market_cap(sym)
        if _is_complete(caps):
            logger.info("  [%d/%d] %s ✓", i, len(passing_df), sym)
        else:
            logger.debug("  [%d/%d] %s — still incomplete after all sources", i, len(passing_df), sym)
        for key in cols:
            cols[key].append(caps.get(key, np.nan))
        time.sleep(0.3)   # polite delay to avoid rate-limiting

    out = passing_df.copy()
    for key, values in cols.items():
        out[key] = values

    n_missing = out["total_market_cap_cr"].isna().sum()
    if n_missing:
        logger.warning(
            "%d/%d stocks still missing market-cap data after yfinance + NSE fallback "
            "(both sources may be temporarily unreachable from this network).",
            n_missing, len(out),
        )

    return out
