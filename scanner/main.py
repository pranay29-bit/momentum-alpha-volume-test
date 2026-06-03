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
    today        = datetime.today()
    today_str    = today.strftime("%Y%m%d")
    date_display = today.strftime("%Y-%m-%d")

    # ── Weekend guard ─────────────────────────────────────────────────────────
    # NSE markets are closed on Saturday (5) and Sunday (6).
    # Skip the scan entirely if today is a weekend day.
    weekday = today.weekday()  # Monday=0 … Sunday=6
    if weekday >= 5:
        day_name = today.strftime("%A")
        logger.warning(
            "Today is %s (%s) — NSE markets are closed on weekends. "
            "Scan skipped. No data will be generated.",
            day_name, date_display,
        )
        sys.exit(0)

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

    # Group dated_dirs by month for the index page
    from collections import OrderedDict
    months_map: dict[str, list] = OrderedDict()
    for d in dated_dirs:
        try:
            dt = datetime.strptime(d.name, "%Y-%m-%d")
            month_key = dt.strftime("%B %Y")
        except ValueError:
            month_key = "Other"
        months_map.setdefault(month_key, []).append(d)

    month_groups_html = ""
    for month_key, month_dirs in months_map.items():
        table_rows = ""
        for d in month_dirs:
            date_label = d.name
            try:
                date_label = datetime.strptime(d.name, "%Y-%m-%d").strftime("%d %b %Y")
            except ValueError:
                pass

            slug         = d.name.replace("-", "")
            passing_link = f"{d.name}/dashboard_{slug}.html"
            elite_link   = f"{base}/{d.name}/elite_dashboard_{slug}.html"

            table_rows += f"""
        <tr>
          <td class="date-cell">{date_label}</td>
          <td><a href="{passing_link}" class="btn-link">📊 Momentum</a></td>
          <td><a href="{elite_link}"   class="btn-link green">⚡ Elite</a></td>
          <td><a href="{d.name}/volume_dashboard_{slug}.html" class="btn-link blue">🔵 Volume</a></td>
          <td><a href="{d.name}/rocket_dashboard_{slug}.html" class="btn-link amber">🚀 Rocket</a></td>
        </tr>"""

        month_groups_html += f"""
  <div class="month-group">
    <div class="month-label">{month_key}</div>
    <table class="history-table">
      <thead>
        <tr>
          <th>Date</th>
          <th>Minervini Trend Template</th>
          <th>Above EMA10 (Elite)</th>
          <th>Volume Action</th>
          <th>Rocket Stocks</th>
        </tr>
      </thead>
      <tbody>{table_rows}</tbody>
    </table>
  </div>"""

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
    --bg:#ffffff;--surface:#ffffff;--surface2:#f8f9fb;--border:#e8eaef;
    --text:#111827;--muted:#6b7280;--subtle:#9ca3af;
    --indigo:#4f46e5;--indigo-lt:#eef2ff;--indigo-mid:#c7d2fe;
    --emerald:#059669;--emerald-lt:#ecfdf5;--emerald-mid:#a7f3d0;
    --blue:#2563eb;--blue-lt:#eff6ff;--blue-mid:#bfdbfe;
    --amber:#d97706;--amber-lt:#fffbeb;--amber-mid:#fde68a;
    --red:#dc2626;--red-lt:#fef2f2;
    --sans:'Inter',system-ui,sans-serif;--serif:'Playfair Display',Georgia,serif;
  }}
  *,*::before,*::after{{box-sizing:border-box;margin:0;padding:0;}}
  html{{font-size:15px;}}
  body{{background:var(--bg);color:var(--text);font-family:var(--sans);line-height:1.65;}}
  .topbar{{height:3px;background:linear-gradient(90deg,#4f46e5,#059669);}}
  header{{background:#fff;border-bottom:1px solid var(--border);padding:2.8rem 3rem 2.2rem;text-align:center;}}
  .logo-eyebrow{{display:inline-flex;align-items:center;gap:.4rem;
                 font-size:.72rem;font-weight:600;letter-spacing:.14em;text-transform:uppercase;
                 color:var(--emerald);margin-bottom:.55rem;}}
  .logo-dot{{width:7px;height:7px;border-radius:50%;background:var(--emerald);}}
  header h1{{font-family:var(--serif);font-size:clamp(1.9rem,3.5vw,2.6rem);font-weight:600;
             letter-spacing:-.02em;color:var(--text);margin:.1rem 0 .5rem;}}
  header p{{color:var(--muted);font-size:.88rem;font-family:var(--sans);}}
  .container{{max-width:1160px;margin:2.5rem auto;padding:0 1.75rem;}}
  h2.section-title{{font-family:var(--serif);font-size:1.35rem;font-weight:600;
                    letter-spacing:-.01em;margin-bottom:1.25rem;color:var(--text);}}
  /* Month groups */
  .month-group{{margin-bottom:2.5rem;}}
  .month-label{{font-size:.7rem;font-weight:600;letter-spacing:.12em;text-transform:uppercase;
                color:var(--subtle);padding-bottom:.5rem;margin-bottom:.65rem;
                border-bottom:2px solid var(--border);}}
  /* History table */
  table.history-table{{width:100%;border-collapse:collapse;background:#fff;
         border:1px solid var(--border);border-radius:12px;overflow:hidden;
         box-shadow:0 1px 4px rgba(0,0,0,.04);}}
  .history-table th{{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.09em;
      color:var(--muted);padding:.85rem 1.3rem;text-align:left;
      background:var(--surface2);border-bottom:1px solid var(--border);}}
  .history-table td{{padding:.95rem 1.3rem;border-bottom:1px solid var(--border);
                     font-size:.88rem;color:var(--text);}}
  .history-table tbody tr:last-child td{{border-bottom:none;}}
  .history-table tbody tr:hover td{{background:#fafbfc;}}
  .date-cell{{font-weight:600;font-size:.87rem;color:var(--text);letter-spacing:.01em;}}
  /* Dashboard link buttons */
  .btn-link{{display:inline-flex;align-items:center;gap:.3rem;padding:.3rem .9rem;
             border-radius:6px;font-size:.78rem;font-weight:500;
             background:var(--indigo-lt);border:1px solid var(--indigo-mid);color:var(--indigo);
             text-decoration:none;transition:background .13s,box-shadow .13s;white-space:nowrap;}}
  .btn-link:hover{{background:#e0e7ff;box-shadow:0 1px 4px rgba(79,70,229,.12);}}
  .btn-link.green{{background:var(--emerald-lt);border-color:var(--emerald-mid);color:var(--emerald);}}
  .btn-link.green:hover{{background:#d1fae5;box-shadow:0 1px 4px rgba(5,150,105,.12);}}
  .btn-link.amber{{background:var(--amber-lt);border-color:var(--amber-mid);color:var(--amber);}}
  .btn-link.amber:hover{{background:#fef3c7;box-shadow:0 1px 4px rgba(217,119,6,.12);}}
  .btn-link.blue{{background:var(--blue-lt);border-color:var(--blue-mid);color:var(--blue);}}
  .btn-link.blue:hover{{background:#dbeafe;box-shadow:0 1px 4px rgba(37,99,235,.12);}}
  footer{{text-align:center;padding:1.75rem;font-size:.75rem;color:var(--subtle);
          border-top:1px solid var(--border);background:#fff;margin-top:3rem;
          font-family:var(--sans);letter-spacing:.02em;}}

  /* ── Market Sentiment ── */
  .sentiment-section{{max-width:1160px;margin:0 auto 2rem;padding:0 1.75rem;}}
  .sentiment-grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(300px,1fr));
                   gap:1.1rem;margin-top:1rem;}}
  .sentiment-card{{background:#fff;border:1px solid var(--border);border-radius:12px;
                   padding:1.35rem 1.5rem;box-shadow:0 1px 4px rgba(0,0,0,.04);}}
  .sentiment-card-header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:.9rem;}}
  .sentiment-index-name{{font-weight:600;font-size:.95rem;color:var(--text);letter-spacing:-.01em;}}
  .overall-badge{{display:inline-block;padding:.22rem .85rem;border-radius:6px;
                  font-size:.72rem;font-weight:600;letter-spacing:.05em;text-transform:uppercase;}}
  .overall-badge.bullish{{background:var(--emerald-lt);border:1px solid var(--emerald-mid);color:var(--emerald);}}
  .overall-badge.bearish{{background:var(--red-lt);border:1px solid #fca5a5;color:var(--red);}}
  .overall-badge.mixed{{background:var(--amber-lt);border:1px solid var(--amber-mid);color:var(--amber);}}
  .overall-badge.unavailable{{background:#f9fafb;border:1px solid #e5e7eb;color:var(--subtle);}}
  .ema-row{{display:flex;gap:.6rem;flex-wrap:wrap;}}
  .ema-pill{{display:flex;align-items:center;gap:.35rem;padding:.3rem .8rem;
             border-radius:6px;font-size:.78rem;font-weight:500;border:1px solid;}}
  .ema-pill.green{{background:var(--emerald-lt);border-color:var(--emerald-mid);color:var(--emerald);}}
  .ema-pill.red{{background:var(--red-lt);border-color:#fca5a5;color:var(--red);}}
  .ema-pill.na{{background:#f9fafb;border-color:#e5e7eb;color:var(--subtle);}}
  .ema-dot{{width:6px;height:6px;border-radius:50%;flex-shrink:0;}}
  .ema-dot.green{{background:var(--emerald);}}
  .ema-dot.red{{background:var(--red);}}
  .ema-dot.na{{background:var(--subtle);}}
  .close-val{{font-size:.82rem;color:var(--muted);margin-bottom:.7rem;}}
  .close-val strong{{color:var(--text);font-weight:600;}}
  .sentiment-legend{{font-size:.73rem;color:var(--subtle);margin-top:.55rem;}}
  </style>
</head>
<body>
<div class="topbar"></div>
<header>
  <div class="logo-eyebrow"><span class="logo-dot"></span>Momentum Alpha</div>
  <h1>NSE Trend Scanner</h1>
  <p>Daily Minervini trend-template scans &nbsp;·&nbsp; Free-float &amp; liquidity data &nbsp;·&nbsp; NSE India</p>
</header>

{sentiment_html}

<div class="container">
  <h2 class="section-title">Scan History</h2>
  {month_groups_html}
</div>
<footer>
  Data sourced from NSE India &amp; Yahoo Finance &nbsp;·&nbsp;
  Updated daily at 18:00 IST &nbsp;·&nbsp;
  For informational purposes only — not financial advice
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
