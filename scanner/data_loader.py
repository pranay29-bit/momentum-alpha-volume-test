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

def load_symbols(csv_path: str = CSV_PATH, symbol_col: str = SYMBOL_COLUMN) -> list[str]:
    df  = pd.read_csv(csv_path)
    raw = df[symbol_col].dropna().astype(str).str.strip().unique().tolist()
    return [s if "." in s else s + EXCHANGE_SUFFIX for s in raw]


def load_symbol_metadata(csv_path: str = CSV_PATH, symbol_col: str = SYMBOL_COLUMN) -> pd.DataFrame:
    """
    Return a DataFrame indexed by the Yahoo-suffixed symbol with
    'industry_group' and 'industry' columns (sourced from NSE_Stocks.csv).
    """
    df = pd.read_csv(csv_path)
    df[symbol_col] = df[symbol_col].dropna().astype(str).str.strip()
    df = df[df[symbol_col].str.len() > 0].copy()
    df["symbol_ns"] = df[symbol_col].apply(
        lambda s: s if "." in s else s + EXCHANGE_SUFFIX
    )

    meta_cols = {"symbol_ns": "symbol_ns"}
    if "Industry Group" in df.columns:
        meta_cols["Industry Group"] = "industry_group"
    if "Industry" in df.columns:
        meta_cols["Industry"] = "industry"

    meta = df[[c for c in meta_cols]].rename(columns=meta_cols)
    return meta.drop_duplicates(subset=["symbol_ns"]).set_index("symbol_ns")


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
