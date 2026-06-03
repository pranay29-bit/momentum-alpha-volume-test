"""
scanner/main.py
---------------
Orchestrates the full scan pipeline:
  1. Load symbols from CSV
  2. Download & compute indicators in batches (yfinance)
  3. Apply Minervini trend-template + RS-percentile filters
  4. Enrich passing stocks with NSE market-cap data
  5. Write CSV outputs and HTML dashboards to docs/
"""

from __future__ import annotations

import logging
import sys
import os
import json
from datetime import datetime
from pathlib import Path

import pandas as pd

from .config     import DOCS_DIR
from .data_loader import download_all, load_symbols
from .nse_client  import enrich_with_market_caps
from .dashboard   import build_passing_dashboard, build_passing_ema10_dashboard, build_volume_action_dashboard, build_rocket_dashboard
from .result_calendar import get_result_date
from .indicators  import get_market_sentiment

# ── Logging ───────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

COND_COLS = [
    "cond1_price_above_150_200",
    "cond2_ma150_above_ma200",
    "cond3_ma200_trending_up_1m",
    "cond4_ma50_above_150_200",
    "cond5_price_above_ma50",
    "cond6_30pct_above_52w_low",
    "cond7_within_25pct_52w_high",
    "cond8_rs_at_least_70",
]

def run() -> None:
    today_str    = datetime.today().strftime("%Y%m%d")
    date_display = datetime.today().strftime("%Y-%m-%d")

    # ── Output directory (GitHub Pages root + dated sub-folder) ──────────────
    out_dir = Path(DOCS_DIR) / date_display
    out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Output directory: %s", out_dir)

    # ── 1. Symbols ────────────────────────────────────────────────────────────
    symbols = load_symbols()
    logger.info("Loaded %d symbols.", len(symbols))

    # ── 2. Download + indicators ──────────────────────────────────────────────
    df = download_all(symbols)
    if df.empty:
        logger.error("No valid data collected. Aborting.")
        sys.exit(1)
    logger.info("Collected rows for %d symbols.", len(df))

    # ── 3. RS percentile + condition flags ────────────────────────────────────
    df["rs_percentile"]        = df["12m_return_pct"].rank(pct=True) * 100.0
    df["cond8_rs_at_least_70"] = df["rs_percentile"] >= 70.0
    df["all_conditions_met"]   = df[COND_COLS].all(axis=1)

    # ── 4. Save full results ──────────────────────────────────────────────────
    full_path = out_dir / f"full_results_{today_str}.csv"
    df.to_csv(full_path, index=False)
    logger.info("Full results → %s", full_path)

    # ── 5. Passing stocks ─────────────────────────────────────────────────────
    
    # 1. Catch our exact indices so they don't get deleted by the momentum filter
    is_index = df["symbol"].isin(["^CNXSC", "NIFTYSMLCAP250.NS"])
    
    # 2. Keep the stock if it meets all conditions OR if it is one of our indices
    passing = df[df["all_conditions_met"] | is_index].copy()

    if not passing.empty:
        passing = enrich_with_market_caps(passing)

    passing_path = out_dir / f"passing_stocks_{today_str}.csv"
    passing.to_csv(passing_path, index=False)
    logger.info("Passing stocks (%d) → %s", len(passing), passing_path)

    # ── 6. Passing + above EMA10 ──────────────────────────────────────────────
    if not passing.empty and "cond9_price_above_ema10" in passing.columns:
        passing_ema10 = (
            passing[passing["cond9_price_above_ema10"]]
            .sort_values("rs_percentile", ascending=False)
            .copy()
        )
    else:
        passing_ema10 = pd.DataFrame()

    ema10_path = out_dir / f"passing_ema10_{today_str}.csv"
    passing_ema10.to_csv(ema10_path, index=False)
    logger.info("Passing+EMA10 stocks (%d) → %s", len(passing_ema10), ema10_path)

    # ── 7. Fresh crossovers ───────────────────────────────────────────────────
    fresh      = df[df["fresh_ma12_cross_today"]].copy()
    fresh_path = out_dir / f"fresh_crossovers_{today_str}.csv"
    fresh.to_csv(fresh_path, index=False)
    logger.info("Fresh crossovers (%d) → %s", len(fresh), fresh_path)

    # ── 8. Volume Action ──────────────────────────────────────────────────────
    volume_action = df[df["volume_signal"] == "ppv"].copy()
    volume_action_path = out_dir / f"volume_action_{today_str}.csv"
    volume_action.to_csv(volume_action_path, index=False)

    # ── 8b. Rocket Stocks (passing + inside bar) ──────────────────────────────
    if "inside_bar" in passing.columns:
        rocket = passing[passing["inside_bar"] == True].copy()
    else:
        rocket = pd.DataFrame()
    rocket_path = out_dir / f"rocket_stocks_{today_str}.csv"
    rocket.to_csv(rocket_path, index=False)
    logger.info("Rocket stocks (%d) → %s", len(rocket), rocket_path)

  

    # ── 9. HTML Dashboards ────────────────────────────────────────────────────

    # ── Compute known_symbols: all symbols seen in the past 10 calendar days ──
    # Used by each dashboard to highlight stocks appearing for the first time.
    known_symbols: set[str] = set()
    history:       list[dict] = []
    docs_root = Path(DOCS_DIR)
    dated_dirs_sorted = sorted(
        [d for d in docs_root.iterdir()
         if d.is_dir() and d.name.replace("-", "").isdigit()
         and len(d.name.replace("-", "")) == 8],
        key=lambda d: d.name,
    )
    for dated_dir in dated_dirs_sorted:
        dir_slug = dated_dir.name.replace("-", "")
        if dir_slug == today_str:
            continue
        # ── history for elite chart ──────────────────────────────────────────
        elite_csv = dated_dir / f"passing_ema10_{dir_slug}.csv"
        if elite_csv.exists():
            try:
                hist_df = pd.read_csv(elite_csv)
                mc = float(hist_df["total_market_cap_cr"].dropna().sum()) \
                     if "total_market_cap_cr" in hist_df.columns else 0.0
                tv = float(hist_df["traded_value_cr"].dropna().sum()) \
                     if "traded_value_cr" in hist_df.columns else 0.0
                history.append({
                    "date":            dir_slug,
                    "count":           len(hist_df),
                    "market_cap_cr":   mc,
                    "traded_value_cr": tv,
                })
            except Exception as exc:
                logger.warning("Could not read elite history from %s: %s", elite_csv, exc)
        # ── known_symbols: scan passing_stocks CSVs from last 10 days ────────
        try:
            from datetime import datetime as _dt, timedelta as _td
            dir_date   = _dt.strptime(dir_slug, "%Y%m%d").date()
            today_date = _dt.strptime(today_str, "%Y%m%d").date()
            if (today_date - dir_date).days <= 10:
                for csv_name in [f"passing_stocks_{dir_slug}.csv",
                                 f"passing_ema10_{dir_slug}.csv",
                                 f"volume_action_{dir_slug}.csv"]:
                    csv_p = dated_dir / csv_name
                    if csv_p.exists():
                        hist_df2 = pd.read_csv(csv_p)
                        if "symbol" in hist_df2.columns:
                            known_symbols.update(
                                str(s).replace(".NS", "")
                                for s in hist_df2["symbol"].dropna()
                            )
        except Exception as exc:
            logger.warning("Could not load known_symbols from %s: %s", dated_dir, exc)

    logger.info("Known symbols (last 10 days): %d", len(known_symbols))

    if not passing.empty:
        build_passing_dashboard(
            passing,
            out_dir / f"dashboard_{today_str}.html",
            today_str,
            known_symbols=known_symbols,
        )
        build_rocket_dashboard(
            passing,
            out_dir / f"rocket_dashboard_{today_str}.html",
            today_str,
            known_symbols=known_symbols,
        )

    if not passing_ema10.empty:
        build_passing_ema10_dashboard(
            passing_ema10,
            out_dir / f"elite_dashboard_{today_str}.html",
            today_str,
            history=history,
            known_symbols=known_symbols,
        )

    if not volume_action.empty:
        build_volume_action_dashboard(
            volume_action,
            out_dir / f"volume_dashboard_{today_str}.html",
            today_str,
            known_symbols=known_symbols,
        )

    # ── 9b. Market Sentiment (small-cap indices) ──────────────────────────────
    logger.info("Fetching market sentiment (small-cap indices)…")
    sentiment = get_market_sentiment()
    logger.info("Market sentiment:\n%s", json.dumps(sentiment, indent=2, default=str))

    # ── 10. Update docs/index.html  (GitHub Pages landing page) ───────────────
    _update_index(today_str, out_dir, len(passing), len(passing_ema10), sentiment=sentiment)

    # ── 10. Console summary ───────────────────────────────────────────────────
    logger.info("── SUMMARY ──────────────────────────────")
    logger.info("  Total scanned   : %d", len(df))
    logger.info("  Passing (8 cond): %d", len(passing))
    logger.info("  Passing + EMA10 : %d", len(passing_ema10))
    logger.info("  Fresh crossovers: %d", len(fresh))
    logger.info("  Volume action   : %d", len(volume_action))

# ── Landing-page updater ──────────────────────────────────────────────────────

def _update_index(today_str: str, out_dir: Path, n_passing: int, n_elite: int, sentiment: dict | None = None) -> None:
    """Regenerate docs/index.html with a link to today's dashboards."""
    docs_root  = Path(DOCS_DIR)
    index_path = docs_root / "index.html"

    # Detect repo sub-path from environment (set by GitHub Actions)
    repo        = os.environ.get("GITHUB_REPOSITORY", "")
    repo_name   = repo.split("/")[-1] if "/" in repo else ""
    base        = f"/{repo_name}" if repo_name else ""

    dated_dirs = sorted(
        [d for d in docs_root.iterdir() if d.is_dir() and d.name[:4].isdigit()],
        reverse=True,
    )

    rows = ""
    for d in dated_dirs:
        date_label = d.name
        try:
            date_label = datetime.strptime(d.name, "%Y-%m-%d").strftime("%d %b %Y")
        except ValueError:
            pass

        slug         = d.name.replace("-", "")
        passing_link = f"{d.name}/dashboard_{slug}.html"
        elite_link   = f"{base}/{d.name}/elite_dashboard_{slug}.html"

        rows += f"""
        <tr>
          <td class="date-cell">{date_label}</td>
          <td><a href="{passing_link}" class="btn-link">📊 Momentum Stocks</a></td>
          <td><a href="{elite_link}"   class="btn-link green">⚡ Elite Stocks</a></td>
          <td><a href="{d.name}/volume_dashboard_{slug}.html" class="btn-link">🔵 Volume Action</a></td>
          <td><a href="{d.name}/rocket_dashboard_{slug}.html" class="btn-link" style="background:#fff7ed;border-color:#fdba74;color:#c2410c">🚀 Rocket Stocks</a></td>
        </tr>"""

    # ── Build Market Sentiment HTML block ─────────────────────────────────────
    sentiment_html = _build_sentiment_html(sentiment or {})

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Momentum Alpha \u2014 NSE Trend Scanner</title>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&family=Playfair+Display:wght@500;600&display=swap" rel="stylesheet"/>
<style>
  :root{{
    --bg:#f5f3ef;--surface:#fff;--border:#e4e0d8;--text:#1c1917;--muted:#78716c;
    --blue:#2563eb;--blue-bg:#eff6ff;--blue-mid:#bfdbfe;
    --emerald:#059669;--green-bg:#f0fdf4;--green-mid:#86efac;
    --amber:#b45309;--red:#dc2626;--green:#15803d;
    --sans:'Inter',sans-serif;--serif:'Playfair Display',Georgia,serif;
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  body{{background:var(--bg);color:var(--text);font-family:var(--sans);}}
  header{{background:var(--surface);border-bottom:1px solid var(--border);
          padding:2.5rem 3rem;text-align:center;}}
  .logo-dot{{display:inline-block;width:10px;height:10px;border-radius:50%;
             background:var(--emerald);margin-right:.4rem;vertical-align:middle;}}
  header h1{{font-family:var(--serif);font-size:2.4rem;font-weight:600;
             letter-spacing:-.02em;margin:.4rem 0;}}
  header p{{color:var(--muted);font-size:.9rem;}}
  .container{{max-width:1120px;margin:2.5rem auto;padding:0 1.5rem;}}
  h2.section-title{{font-family:var(--serif);font-size:1.3rem;margin-bottom:1rem;}}
  /* Scan history table */
  table.history-table{{width:100%;border-collapse:collapse;background:var(--surface);
         border:1px solid var(--border);border-radius:14px;overflow:hidden;}}
  .history-table th{{font-size:.65rem;font-weight:700;text-transform:uppercase;letter-spacing:.09em;
      color:var(--muted);padding:.8rem 1.2rem;text-align:left;
      background:#faf9f7;border-bottom:1px solid var(--border);}}
  .history-table td{{padding:.9rem 1.2rem;border-bottom:1px solid var(--border);font-size:.88rem;}}
  .history-table tr:last-child td{{border-bottom:none;}}
  .date-cell{{font-weight:600;}}
  .btn-link{{display:inline-block;padding:.3rem .9rem;border-radius:999px;
             font-size:.78rem;font-weight:600;background:var(--blue-bg);
             border:1px solid var(--blue-mid);color:var(--blue);
             text-decoration:none;transition:background .15s;}}
  .btn-link:hover{{background:#dbeafe;}}
  .btn-link.green{{background:var(--green-bg);border-color:var(--green-mid);color:var(--emerald);}}
  .btn-link.green:hover{{background:#dcfce7;}}
  footer{{text-align:center;padding:2rem;font-size:.72rem;color:var(--muted);
          border-top:1px solid var(--border);margin-top:3rem;}}

  /* ── Market Sentiment ── */
  .sentiment-section{{max-width:1120px;margin:0 auto 2.5rem;padding:0 1.5rem;}}
  .sentiment-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));gap:1.25rem;margin-top:1rem;}}
  .sentiment-card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;
                   padding:1.4rem 1.6rem;}}
  .sentiment-card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:1rem;}}
  .sentiment-index-name{{font-weight:700;font-size:.95rem;}}
  .overall-badge{{display:inline-block;padding:.25rem .85rem;border-radius:999px;
                  font-size:.72rem;font-weight:700;letter-spacing:.06em;text-transform:uppercase;}}
  .overall-badge.bullish{{background:#f0fdf4;border:1px solid #86efac;color:#15803d;}}
  .overall-badge.bearish{{background:#fef2f2;border:1px solid #fca5a5;color:#dc2626;}}
  .overall-badge.mixed{{background:#fffbeb;border:1px solid #fde68a;color:#b45309;}}
  .overall-badge.unavailable{{background:#f8fafc;border:1px solid #e2e8f0;color:#94a3b8;}}
  .ema-row{{display:flex;gap:.75rem;flex-wrap:wrap;}}
  .ema-pill{{display:flex;align-items:center;gap:.4rem;padding:.35rem .85rem;
             border-radius:999px;font-size:.78rem;font-weight:600;border:1px solid;}}
  .ema-pill.green{{background:#f0fdf4;border-color:#86efac;color:#15803d;}}
  .ema-pill.red{{background:#fef2f2;border-color:#fca5a5;color:#dc2626;}}
  .ema-pill.na{{background:#f8fafc;border-color:#e2e8f0;color:#94a3b8;}}
  .ema-dot{{width:7px;height:7px;border-radius:50%;flex-shrink:0;}}
  .ema-dot.green{{background:#15803d;}}
  .ema-dot.red{{background:#dc2626;}}
  .ema-dot.na{{background:#94a3b8;}}
  .close-val{{font-size:.8rem;color:var(--muted);margin-bottom:.75rem;}}
  .close-val strong{{color:var(--text);}}
  .sentiment-legend{{font-size:.72rem;color:var(--muted);margin-top:.6rem;}}
  </style>
</head>
<body>
<header>
  <span class="logo-dot"></span>
  <span style="font-size:.72rem;letter-spacing:.14em;text-transform:uppercase;font-weight:700;color:var(--emerald)">Momentum Alpha</span>
  <h1>NSE Trend Scanner</h1>
  <p>Daily Minervini trend-template scans \u00b7 Free-float &amp; liquidity data \u00b7 NSE India</p>
</header>

{sentiment_html}

<div class="container">
  <h2 class="section-title">Scan History</h2>
  <table class="history-table">
    <thead>
      <tr>
        <th>Date</th>
        <th>Minervini Trend Template Stocks</th>
        <th>Minervini Trend Template Stocks (Above EMA10)</th>
        <th>Volume Action Stocks</th>
        <th>Rocket Stocks</th>
      </tr>
    </thead>
    <tbody>{rows}</tbody>
  </table>
</div>
<footer>
  Data sourced from NSE India &amp; Yahoo Finance &nbsp;\u00b7&nbsp;
  Updated daily at 18:00 IST &nbsp;\u00b7&nbsp;
  For informational purposes only \u2014 not financial advice
</footer>
</body>
</html>"""

    index_path.write_text(html, encoding="utf-8")
    logger.info("Index page updated → %s", index_path)


def _build_sentiment_html(sentiment: dict) -> str:
    """Build the Market Sentiment HTML section from the sentiment dict."""

    def _pill(label: str, above: bool | None, ema_val: float | None) -> str:
        if above is None:
            css = "na"
            text = f"{label} N/A"
        else:
            css = "green" if above else "red"
            direction = "above" if above else "below"
            val_str = f" ({ema_val:,.0f})" if ema_val is not None else ""
            text = f"Price {direction} {label}{val_str}"
        return f'<span class="ema-pill {css}"><span class="ema-dot {css}"></span>{text}</span>'

    overall = sentiment.get("overall", "unavailable")
    overall_label = {"bullish": "🟢 Bullish", "bearish": "🔴 Bearish",
                     "mixed":   "🟡 Mixed",   "unavailable": "⬜ N/A"}.get(overall, "⬜ N/A")

    cards_html = ""
    for key in ("cnxsmallcap", "niftysmlcap250"):
        info = sentiment.get(key, {})
        name    = info.get("name", key)
        close   = info.get("close")
        ema10   = info.get("ema10")
        ema20   = info.get("ema20")
        above10 = info.get("above_ema10")
        above20 = info.get("above_ema20")

        close_str = f"₹{close:,.2f}" if close is not None else "N/A"
        pill10    = _pill("EMA10", above10, ema10)
        pill20    = _pill("EMA20", above20, ema20)

        cards_html += f"""
    <div class="sentiment-card">
      <div class="sentiment-card-header">
        <span class="sentiment-index-name">{name}</span>
      </div>
      <div class="close-val">Last Close: <strong>{close_str}</strong></div>
      <div class="ema-row">
        {pill10}
        {pill20}
      </div>
      <div class="sentiment-legend">Green = price above EMA &nbsp;·&nbsp; Red = price below EMA</div>
    </div>"""

    return f"""
<div class="sentiment-section">
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:.25rem;">
    <h2 class="section-title" style="margin-bottom:0">Market Sentiment</h2>
    <span class="overall-badge {overall}">{overall_label}</span>
  </div>
  <p style="font-size:.8rem;color:var(--muted);margin-bottom:.75rem;">
    Small-cap index health based on 10-EMA &amp; 20-EMA — updated each scan run.
  </p>
  <div class="sentiment-grid">
    {cards_html}
  </div>
</div>"""

if __name__ == "__main__":
    run()
