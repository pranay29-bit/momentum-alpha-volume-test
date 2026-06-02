"""
scanner/data_loader.py
----------------------
Loads symbol list from CSV and downloads OHLCV data from Yahoo Finance
in configurable batches. Also loads Industry & Industry Group metadata
from the same CSV and merges it into the result DataFrame.
"""

from __future__ import annotations

import logging
import time
from math import ceil
from pathlib import Path

import pandas as pd
import yfinance as yf

from .config import (
    CSV_PATH, SYMBOL_COLUMN, EXCHANGE_SUFFIX,
    PERIOD, INTERVAL, BATCH_SIZE,
)
from .indicators import add_indicators, evaluate_trend_template, compute_12m_return, compute_volume_action, is_inside_candle

logger = logging.getLogger(__name__)

# Seconds to pause between batches — prevents Yahoo Finance rate limiting
_BATCH_DELAY        = 1.0
# Extra back-off when a 429 / rate-limit error is detected
_RATE_LIMIT_BACKOFF = 30.0


# ── Symbol list & metadata ─────────────────────────────────────────────────────
"""
scanner/indicators.py
---------------------
All technical-indicator computation and Minervini trend-template evaluation.
Each function is pure (takes a DataFrame, returns a value / dict / bool).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .config import (
    MA12_WINDOW, MA36_WINDOW, MA50_WINDOW,
    MA150_WINDOW, MA200_WINDOW, EMA10_WINDOW, EMA20_WINDOW,
    RS_LOOKBACK,
)


# ── Indicator computation ─────────────────────────────────────────────────────

def add_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """Add MA/EMA and 52-week high/low columns to *df*. Returns a copy."""
    df = df.copy()
    df["MA12"]   = df["Close"].rolling(window=MA12_WINDOW).mean()
    df["MA36"]   = df["Close"].rolling(window=MA36_WINDOW).mean()
    df["MA50"]   = df["Close"].rolling(window=MA50_WINDOW).mean()
    df["MA150"]  = df["Close"].rolling(window=MA150_WINDOW).mean()
    df["MA200"]  = df["Close"].rolling(window=MA200_WINDOW).mean()
    df["EMA10"]  = df["Close"].ewm(span=EMA10_WINDOW, adjust=False).mean()
    df["EMA20"]  = df["Close"].ewm(span=EMA20_WINDOW, adjust=False).mean()
    df["52w_low"]  = df["Low"].rolling(window=RS_LOOKBACK).min()
    df["52w_high"] = df["High"].rolling(window=RS_LOOKBACK).max()
    df["inside_bar"] = (df["High"] < df["High"].shift(1)) & (df["Low"] > df["Low"].shift(1))  # ← ADD THIS
    return df


def get_market_sentiment() -> dict:
    """
    Fetch NIFTY SMALLCAP 100 and NIFTY SMALLCAP 250 index data directly from NSE 
    using jugaad_data, compute EMA10 / EMA20, and return a sentiment dict.
    """
    from datetime import date, timedelta
    import pandas as pd
    from jugaad_data.nse import index_raw

    # Exact official index names as required by the NSE website
    INDICES = {
        "cnxsmallcap": {
            "name": "NIFTY SMALLCAP 100",
            "display_name": "Smallcap 100"
        },
        "niftysmlcap250": {
            "name": "NIFTY SMALLCAP 250",
            "display_name": "Smallcap 250"
        },
    }

    result: dict = {
        "cnxsmallcap":    {"close": None, "ema10": None, "ema20": None,
                           "above_ema10": None, "above_ema20": None, "name": "Smallcap 100"},
        "niftysmlcap250": {"close": None, "ema10": None, "ema20": None,
                           "above_ema10": None, "above_ema20": None, "name": "Smallcap 250"},
        "overall": "unavailable",
    }

    ok_count   = 0
    bull_count = 0

    # Fetch the last 90 days of data to safely calculate the 20-day EMA
    to_date = date.today()
    from_date = to_date - timedelta(days=90)

    for key, meta in INDICES.items():
        try:
            # 1. Fetch historical index data from the NSE servers
            raw_data = index_raw(symbol=meta["name"], from_date=from_date, to_date=to_date)
            
            if not raw_data:
                print(f"[Market Sentiment] No data found for {meta['name']} on NSE")
                continue

            df = pd.DataFrame(raw_data)

            # 2. Extract and format dates and closing prices
            # (jugaad_data typically returns 'HistoricalDate' and 'CLOSE')
            date_col = "HistoricalDate" if "HistoricalDate" in df.columns else "Index Date"
            close_col = "CLOSE" if "CLOSE" in df.columns else "Closing Index Value"

            df[date_col] = pd.to_datetime(df[date_col])
            
            # 3. Sort chronologically (oldest to newest) for accurate EMA calculation
            df = df.sort_values(by=date_col).reset_index(drop=True)
            close_series = df[close_col].astype(float)

            if len(close_series) < 21:
                print(f"[Market Sentiment] Not enough data rows for {meta['name']}")
                continue

            print(f"[Market Sentiment] {meta['name']} OK — {len(close_series)} rows fetched from NSE")

            # 4. Calculate EMAs
            last  = float(close_series.iloc[-1])
            ema10 = float(close_series.ewm(span=10, adjust=False).mean().iloc[-1])
            ema20 = float(close_series.ewm(span=20, adjust=False).mean().iloc[-1])

            above10 = last > ema10
            above20 = last > ema20

            result[key].update({
                "close":       round(last,  2),
                "ema10":       round(ema10, 2),
                "ema20":       round(ema20, 2),
                "above_ema10": above10,
                "above_ema20": above20,
            })

            ok_count += 1
            if above10 and above20:
                bull_count += 1
            elif above10 or above20:
                bull_count += 0.5

        except Exception as e:
            print(f"[Market Sentiment] {meta['name']} failed: {e}")

    # 5. Evaluate overall sentiment based on the index data
    if ok_count == 0:
        result["overall"] = "unavailable"
    elif bull_count >= ok_count * 0.75:
        result["overall"] = "bullish"
    elif bull_count <= ok_count * 0.25:
        result["overall"] = "bearish"
    else:
        result["overall"] = "mixed"

    return result

# ── Helper predicates ─────────────────────────────────────────────────────────

def _strictly_increasing(series: pd.Series, days: int = 21) -> bool:
    s = series.dropna()
    if len(s) < days:
        return False
    return (s.tail(days).diff().dropna() > 0).all()


def _bullish_crossover_today(fast: pd.Series, slow: pd.Series) -> bool:
    """True iff fast crossed above slow on the most-recent bar."""
    idx = fast.dropna().index.intersection(slow.dropna().index)
    if len(idx) < 2:
        return False
    f, s = fast.loc[idx], slow.loc[idx]
    return bool((f.iloc[-1] > s.iloc[-1]) and (f.iloc[-2] <= s.iloc[-2]))


# ── 12-month relative-strength return ────────────────────────────────────────

def compute_12m_return(df: pd.DataFrame) -> float:
    if len(df) < RS_LOOKBACK + 1:
        return np.nan
    latest = df["Close"].iloc[-1]
    past   = df["Close"].iloc[-RS_LOOKBACK]
    if past == 0 or pd.isna(past):
        return np.nan
    return (latest / past - 1.0) * 100.0

def is_inside_candle(df: pd.DataFrame) -> bool:
    """
    Returns True if the latest bar is an inside candle
    (its high/low range is fully contained within the prior bar's range).
    """
    if len(df) < 2:
        return False
    curr = df.iloc[-1]
    prev = df.iloc[-2]
    return bool((curr["High"] < prev["High"]) and (curr["Low"] > prev["Low"]))


# ── Minervini Trend Template ──────────────────────────────────────────────────

_TEMPLATE_DEFAULTS = {
    "close": np.nan,
    "MA12":  np.nan, "MA36":  np.nan, "MA50":  np.nan,
    "MA150": np.nan, "MA200": np.nan, "EMA10": np.nan,
    "52w_low": np.nan, "52w_high": np.nan,
    "cond1_price_above_150_200":   False,
    "cond2_ma150_above_ma200":     False,
    "cond3_ma200_trending_up_1m":  False,
    "cond4_ma50_above_150_200":    False,
    "cond5_price_above_ma50":      False,
    "cond6_30pct_above_52w_low":   False,
    "cond7_within_25pct_52w_high": False,
    "cond9_price_above_ema10":     False,
    "fresh_ma12_cross_today":      False,
}


def evaluate_trend_template(df: pd.DataFrame) -> dict:
    """
    Evaluate all Minervini trend-template conditions for the latest bar.
    Returns a flat dict; all booleans default to False on insufficient data.
    """
    result = dict(_TEMPLATE_DEFAULTS)
    if df.empty or len(df) < RS_LOOKBACK:
        return result

    row   = df.iloc[-1]
    close = row["Close"]

    vals = {k: row.get(k, np.nan) for k in
            ["MA12", "MA36", "MA50", "MA150", "MA200", "EMA10", "52w_low", "52w_high"]}

    result.update({"close": close, **vals})

    if any(pd.isna(v) for v in vals.values()):
        return result

    ma12, ma36   = vals["MA12"],  vals["MA36"]
    ma50         = vals["MA50"]
    ma150, ma200 = vals["MA150"], vals["MA200"]
    ema10        = vals["EMA10"]
    low_52w      = vals["52w_low"]
    high_52w     = vals["52w_high"]

    result.update({
        "cond1_price_above_150_200":   close > ma150 and close > ma200,
        "cond2_ma150_above_ma200":     ma150 > ma200,
        "cond3_ma200_trending_up_1m":  _strictly_increasing(df["MA200"], 21),
        "cond4_ma50_above_150_200":    ma50 > ma150 and ma50 > ma200,
        "cond5_price_above_ma50":      close > ma50,
        "cond6_30pct_above_52w_low":   close >= 1.30 * low_52w,
        "cond7_within_25pct_52w_high": close >= 0.75 * high_52w,
        "cond9_price_above_ema10":     close > ema10,
        "fresh_ma12_cross_today":      _bullish_crossover_today(df["MA12"], df["MA36"]),
    })
    return result


# ── Smart Volume / Pocket Pivot ──────────────────────────────────────────────

def compute_volume_action(df: pd.DataFrame) -> dict:
    """Compute latest-day volume action labels."""
    result = {
        "volume_signal": "noise",
        "relative_volume": np.nan,
        "bull_snort": False,
    }
    if df.empty or len(df) < 21:
        return result

    vol_ma = df["Volume"].rolling(50).mean()
    latest = df.iloc[-1]
    latest_close = latest["Close"]
    prev_close = df["Close"].iloc[-2]
    latest_vol = latest["Volume"]
    latest_vol_ma = vol_ma.iloc[-1]

    highest_down_volume = 0
    for i in range(max(0, len(df)-21), len(df)-1):
        if i <= 0:
            continue
        if df["Close"].iloc[i] < df["Close"].iloc[i-1]:
            highest_down_volume = max(highest_down_volume, df["Volume"].iloc[i])

    is_up_day = latest_close > prev_close
    is_down_day = latest_close < prev_close
    is_ppv = is_up_day and latest_vol > highest_down_volume

    volume_signal = 'noise'
    if is_ppv:
        volume_signal = 'ppv'
    elif is_up_day and latest_vol > latest_vol_ma:
        volume_signal = 'green'
    elif is_down_day and latest_vol > latest_vol_ma:
        volume_signal = 'red'
    elif latest_vol <= latest_vol_ma * 0.20:
        volume_signal = 'dry'

    candle_range = latest['High'] - latest['Low']
    close_position = ((latest_close - latest['Low']) / candle_range) if candle_range > 0 else 0

    result.update({
        'volume_signal': volume_signal,
        'relative_volume': (latest_vol / latest_vol_ma) * 100 if latest_vol_ma else np.nan,
        'bull_snort': bool((latest_vol >= 3 * latest_vol_ma) and (close_position >= 0.65) and is_up_day)
    })
    return result
# ── Batch downloader ──────────────────────────────────────────────────────────

def _chunk(lst: list, n: int):
    for i in range(0, len(lst), n):
        yield lst[i : i + n]


def _process_symbol(sym: str, data: pd.DataFrame, is_multi: bool) -> dict | None:
    try:
        df_sym = data[sym].copy() if is_multi else data.copy()
        if "Close" not in df_sym.columns:
            if "Adj Close" in df_sym.columns:
                df_sym = df_sym.rename(columns={"Adj Close": "Close"})
            else:
                return None
        df_sym = df_sym.dropna(subset=["Close"])
        if df_sym.empty:
            return None

        df_sym   = add_indicators(df_sym)
        tpl      = evaluate_trend_template(df_sym)
        rs_ret   = compute_12m_return(df_sym)
        vol_data = compute_volume_action(df_sym)
        inside_bar = is_inside_candle(df_sym)  

        return {
            "symbol":  sym,
            "close":   tpl["close"],
            "MA12":    tpl["MA12"],  "MA36":  tpl["MA36"],
            "MA50":    tpl["MA50"],  "MA150": tpl["MA150"],
            "MA200":   tpl["MA200"], "EMA10": tpl["EMA10"],
            "52w_low":  tpl["52w_low"],
            "52w_high": tpl["52w_high"],
            "cond1_price_above_150_200":   tpl["cond1_price_above_150_200"],
            "cond2_ma150_above_ma200":     tpl["cond2_ma150_above_ma200"],
            "cond3_ma200_trending_up_1m":  tpl["cond3_ma200_trending_up_1m"],
            "cond4_ma50_above_150_200":    tpl["cond4_ma50_above_150_200"],
            "cond5_price_above_ma50":      tpl["cond5_price_above_ma50"],
            "cond6_30pct_above_52w_low":   tpl["cond6_30pct_above_52w_low"],
            "cond7_within_25pct_52w_high": tpl["cond7_within_25pct_52w_high"],
            "cond9_price_above_ema10":     tpl["cond9_price_above_ema10"],
            "fresh_ma12_cross_today":      tpl["fresh_ma12_cross_today"],
            "12m_return_pct": rs_ret,
            "volume_signal":  vol_data["volume_signal"],
            "relative_volume": vol_data["relative_volume"],
            "bull_snort":     vol_data["bull_snort"],
            "inside_bar":     inside_bar,
        }
    except Exception as exc:
        logger.error("Error processing %s: %r", sym, exc)
        return None


def download_all(symbols: list[str]) -> pd.DataFrame:
    """
    Download price history for all *symbols* in batches and return a
    consolidated DataFrame with indicators + trend-template flags,
    enriched with Industry Group and Industry from NSE_Stocks.csv.
    """
    # Load industry metadata once
    try:
        meta = load_symbol_metadata()
    except Exception as exc:
        logger.warning("Could not load symbol metadata: %s", exc)
        meta = pd.DataFrame()

    all_rows: list[dict] = []
    total = ceil(len(symbols) / BATCH_SIZE)

    for i, batch in enumerate(_chunk(symbols, BATCH_SIZE), start=1):
        # Polite pause between batches to avoid Yahoo Finance rate limiting
        if i > 1:
            time.sleep(_BATCH_DELAY)

        logger.info("=== Batch %d/%d (%d symbols) ===", i, total, len(batch))
        try:
            data = yf.download(
                tickers=batch,
                period=PERIOD,
                interval=INTERVAL,
                group_by="ticker",
                auto_adjust=True,
                threads=False,   # sequential within batch — avoids burst 429s
                progress=False,
            )
        except Exception as exc:
            err_str = str(exc).lower()
            if "too many requests" in err_str or "rate limit" in err_str or "429" in err_str:
                logger.warning(
                    "Rate limited on batch %d — backing off %ds then retrying once…",
                    i, _RATE_LIMIT_BACKOFF,
                )
                time.sleep(_RATE_LIMIT_BACKOFF)
                try:
                    data = yf.download(
                        tickers=batch,
                        period=PERIOD,
                        interval=INTERVAL,
                        group_by="ticker",
                        auto_adjust=True,
                        threads=False,
                        progress=False,
                    )
                except Exception as exc2:
                    logger.error("Batch %d retry also failed: %s", i, exc2)
                    continue
            else:
                logger.error("Batch %d download failed: %s", i, exc)
                continue

        if data is None or data.empty:
            continue

        is_multi = isinstance(data.columns, pd.MultiIndex)
        for sym in batch:
            row = _process_symbol(sym, data, is_multi)
            if row:
                all_rows.append(row)

    df = pd.DataFrame(all_rows)

    # Merge industry metadata
    if not df.empty and not meta.empty:
        df = df.join(meta, on="symbol", how="left")

    return df
