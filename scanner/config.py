"""
scanner/config.py
-----------------
All tuneable parameters for the Momentum Alpha scanner.
Override any value via environment variables before running.
"""

import os
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────────
ROOT_DIR     = Path(__file__).resolve().parent.parent
DATA_DIR     = ROOT_DIR / "data"
WEB_DIR      = ROOT_DIR / "web"
DOCS_DIR     = ROOT_DIR / "docs"          # GitHub Pages root

CSV_PATH     = os.getenv("NSE_CSV_PATH", str(DATA_DIR / "NSE_Stocks.csv"))
SYMBOL_COLUMN = "Symbol"
EXCHANGE_SUFFIX = ".NS"

# ── Download ──────────────────────────────────────────────────────────────────
PERIOD    = "400d"
INTERVAL  = "1d"
BATCH_SIZE = 50

# ── Indicator windows ─────────────────────────────────────────────────────────
RS_LOOKBACK  = 252
MA12_WINDOW  = 12
MA36_WINDOW  = 36
MA50_WINDOW  = 50
MA150_WINDOW = 150
MA200_WINDOW = 200
EMA10_WINDOW = 10
EMA20_WINDOW = 20
CROSS_LOOKBACK = 10

# ── NSE API ───────────────────────────────────────────────────────────────────
NSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": "https://www.nseindia.com/",
}
NSE_REQUEST_DELAY = 1.0   # seconds between per-stock NSE calls
