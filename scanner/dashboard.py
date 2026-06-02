"""
scanner/dashboard.py
--------------------
Generates self-contained HTML dashboards from scan results.

Three public entry-points:
  • build_passing_dashboard        – all 8-condition passing stocks
  • build_passing_ema10_dashboard  – passing AND above EMA10 (elite view)
  • build_index_page               – landing page with date navigation
"""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

from .utils import fmt_cr

logger = logging.getLogger(__name__)


# ── Small helpers ─────────────────────────────────────────────────────────────

def _safe(v) -> bool:
    try:
        return not np.isnan(float(v))
    except Exception:
        return False


def _r(v, n=2):
    try:
        f = float(v)
        return str(round(f, n)) if not np.isnan(f) else "null"
    except Exception:
        return "null"


def _tv_link(symbol_ns: str) -> str:
    sym = symbol_ns.replace(".NS", "").strip()
    return f"https://www.tradingview.com/chart/?symbol=NSE%3A{sym}"


def build_main_index(
    passing_path="passing_dashboard.html",
    elite_path="elite_dashboard.html",
    volume_path="volume_action_dashboard.html",
    rocket_path="rocket_dashboard.html",
    out_path="index.html"
):
    html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>Momentum Alpha Dashboard</title>
        <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
        <style>
            body {{
                font-family: 'Inter', sans-serif;
                background: #F8FAFC;
                color: #0F172A;
                padding: 40px;
                margin: 0;
            }}

            h1 {{
                margin-bottom: 30px;
                font-weight: 700;
                letter-spacing: -0.02em;
            }}

            .grid {{
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
                gap: 24px;
            }}

            .card {{
                background: #FFFFFF;
                padding: 30px;
                border-radius: 16px;
                border: 1px solid #E2E8F0;
                box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
                transition: transform 0.2s, box-shadow 0.2s;
            }}
            
            .card:hover {{
                transform: translateY(-2px);
                box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1), 0 4px 6px -4px rgba(0, 0, 0, 0.1);
            }}

            .card h2 {{
                margin-top: 0;
                color: #1E293B;
                font-size: 1.25rem;
                font-weight: 600;
            }}
            
            .card p {{
                color: #64748B;
                font-size: 0.9rem;
                margin-bottom: 24px;
            }}

            .card a {{
                display: inline-block;
                padding: 10px 18px;
                background: #2563EB;
                color: white;
                border-radius: 8px;
                text-decoration: none;
                font-weight: 500;
                font-size: 0.9rem;
                transition: background 0.2s;
            }}
            
            .card a:hover {{
                background: #1D4ED8;
            }}
        </style>
    </head>

    <body>
        <h1>Momentum Alpha Scanners</h1>
        <div class="grid">
            <div class="card">
                <h2>Passing Stocks</h2>
                <p>Base Minervini 8-condition scan.</p>
                <a href="{passing_path}">Open Dashboard</a>
            </div>
            <div class="card">
                <h2>Elite EMA10</h2>
                <p>High momentum + Above 10-period EMA.</p>
                <a href="{elite_path}">Open Dashboard</a>
            </div>
            <div class="card">
                <h2>Volume Action</h2>
                <p>Pocket pivots and abnormal volume signatures.</p>
                <a href="{volume_path}">Open Dashboard</a>
            </div>
            <div class="card">
                <h2>Rocket Stocks</h2>
                <p>Passing conditions + Inside bar coil.</p>
                <a href="{rocket_path}">Open Dashboard</a>
            </div>
        </div>
    </body>
    </html>
    """
    Path(out_path).write_text(html, encoding="utf-8")
    logger.info("Main index page → %s", out_path)


# ── Shared CSS / Chart.js CDN ─────────────────────────────────────────────────

_CDN_CHARTJS = "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/4.4.1/chart.umd.min.js"
_GOOGLE_FONTS = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@500;600&display=swap"

_BASE_CSS = """
:root {
  --bg: #F8FAFC;
  --surface: #FFFFFF;
  --border: #E2E8F0;
  --border2: #CBD5E1;
  --text: #0F172A;
  --muted: #64748B;
  --subtle: #94A3B8;
  
  --blue: #2563EB; --blue-bg: #EFF6FF; --blue-mid: #BFDBFE;
  --teal: #0D9488; --teal-bg: #F0FDFA; --teal-mid: #99F6E4;
  --amber: #D97706; --amber-bg: #FFFBEB; --amber-mid: #FDE68A;
  --emerald: #059669; --green-bg: #ECFDF5; --green-mid: #A7F3D0;
  --red: #DC2626; --red-bg: #FEF2F2; --red-mid: #FECACA;
  --purple: #7C3AED; --purple-bg: #F5F3FF;
  
  --sans: 'Inter', sans-serif;
  --mono: 'JetBrains Mono', monospace;
  --r: 8px; --rl: 12px;
  --shadow-sm: 0 1px 2px 0 rgba(0, 0, 0, 0.05);
  --shadow-md: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
}

*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
html { font-size: 14px; }
body { background: var(--bg); color: var(--text); font-family: var(--sans); line-height: 1.6; min-height: 100vh; }
a { color: inherit; text-decoration: none; }

/* ── Header ── */
header { background: var(--surface); border-bottom: 1px solid var(--border); padding: 2rem 3rem; display: flex; align-items: flex-end; justify-content: space-between; gap: 1rem; flex-wrap: wrap; }
.logo-line { display: flex; align-items: center; gap: 0.6rem; margin-bottom: 0.5rem; }
.logo-dot  { width: 10px; height: 10px; border-radius: 50%; }
.logo-tag  { font-size: 0.75rem; letter-spacing: 0.1em; text-transform: uppercase; font-weight: 700; }
header h1  { font-size: clamp(1.5rem, 3vw, 2.25rem); font-weight: 700; letter-spacing: -0.03em; line-height: 1.1; color: var(--text); }
header .sub { font-size: 0.9rem; color: var(--muted); margin-top: 0.4rem; font-weight: 500; }
.date-chip  { border-radius: 999px; padding: 0.4rem 1.2rem; font-size: 0.85rem; font-weight: 600; white-space: nowrap; border: 1px solid; }

/* ── KPI row ── */
.kpi-row { display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1.5rem; padding: 2rem 3rem; }
.kpi { background: var(--surface); border: 1px solid var(--border); border-radius: var(--rl); padding: 1.5rem; position: relative; overflow: hidden; box-shadow: var(--shadow-sm); }
.kpi-accent { position: absolute; top: 0; left: 0; height: 4px; width: 100%; }
.kpi-label  { font-size: 0.75rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--muted); font-weight: 600; margin-bottom: 0.5rem; }
.kpi-val    { font-family: var(--sans); font-size: clamp(1.5rem, 2vw, 2rem); font-weight: 700; letter-spacing: -0.02em; line-height: 1; word-break: break-word; color: var(--text); }
.kpi.blue   .kpi-accent { background: var(--blue); }
.kpi.teal   .kpi-accent { background: var(--teal); }
.kpi.amber  .kpi-accent { background: var(--amber); }
.kpi.green  .kpi-accent { background: var(--emerald); }
.kpi.purple .kpi-accent { background: var(--purple); }

/* ── Charts ── */
.charts-grid { padding: 0 3rem 2rem; display: grid; gap: 1.5rem; grid-template-columns: 3fr 2fr; }
@media(max-width:860px) { .charts-grid { grid-template-columns: 1fr; } }
.chart-card  { background: var(--surface); border: 1px solid var(--border); border-radius: var(--rl); padding: 1.5rem; box-shadow: var(--shadow-sm); }
.chart-title { font-size: 0.8rem; text-transform: uppercase; letter-spacing: 0.08em; color: var(--text); font-weight: 700; margin-bottom: 1.25rem; }
.chart-wrap  { position: relative; height: 280px; }

/* ── Table section ── */
.table-section { padding: 0 3rem 3rem; }
.sec-head  { display: flex; align-items: center; justify-content: space-between; margin-bottom: 1rem; flex-wrap: wrap; gap: 1rem; }
.sec-title { font-size: 1rem; color: var(--text); font-weight: 700; }
.controls  { display: flex; align-items: center; gap: 1.5rem; flex-wrap: wrap; }
.search-input { background: var(--bg); border: 1px solid var(--border); border-radius: var(--r); color: var(--text); font-family: var(--sans); font-size: 0.9rem; padding: 0.5rem 1rem; outline: none; width: 220px; transition: all 0.2s; }
.search-input:focus { border-color: var(--blue); background: var(--surface); box-shadow: 0 0 0 3px var(--blue-bg); }
.search-input::placeholder { color: var(--subtle); }
.legend { display: flex; gap: 1.2rem; font-size: 0.8rem; color: var(--muted); flex-wrap: wrap; align-items: center; font-weight: 500; }
.leg-item { display: flex; align-items: center; gap: 0.4rem; }
.leg-dot  { width: 8px; height: 8px; border-radius: 50%; flex-shrink: 0; }

.tbl-wrap { background: var(--surface); border: 1px solid var(--border); border-radius: var(--rl); overflow: auto; box-shadow: var(--shadow-sm); }
table { width: 100%; border-collapse: collapse; font-size: 0.85rem; white-space: nowrap; }
thead tr { background: #F1F5F9; position: sticky; top: 0; z-index: 2; }
th { font-size: 0.75rem; font-weight: 600; text-transform: uppercase; letter-spacing: 0.05em; color: var(--text); padding: 1rem 1.25rem; text-align: left; cursor: pointer; user-select: none; transition: background 0.15s; border-bottom: 1px solid var(--border); }
th:hover { background: #E2E8F0; }
th.r { text-align: right; } th.c { text-align: center; }
th .si { margin-left: 0.4rem; opacity: 0.4; font-style: normal; font-size: 0.75rem; }
th.sort-asc  .si::after { content: '▲'; opacity: 1; color: var(--blue); }
th.sort-desc .si::after { content: '▼'; opacity: 1; color: var(--blue); }
th:not(.sort-asc):not(.sort-desc) .si::after { content: '⇅'; }
.srow { border-bottom: 1px solid var(--border); transition: background 0.15s; }
.srow:last-child { border-bottom: none; }
.srow:hover { background: var(--bg); }
td { padding: 1rem 1.25rem; vertical-align: middle; color: var(--text); }
td.r { text-align: right; font-family: var(--mono); } td.c { text-align: center; }

a.sym-tag { display: inline-block; font-weight: 600; font-size: 0.8rem; padding: 0.25rem 0.6rem; border-radius: 6px; text-decoration: none; border: 1px solid; transition: all 0.15s; }
a.sym-tag:hover { filter: brightness(0.95); }
.rs-tag  { display: inline-block; background: var(--amber-bg); border: 1px solid var(--amber-mid); color: var(--amber); font-size: 0.8rem; font-weight: 600; padding: 0.2rem 0.6rem; border-radius: 999px; }
.ema-tag { display: inline-block; font-size: 0.8rem; font-weight: 600; padding: 0.2rem 0.6rem; border-radius: 999px; border: 1px solid transparent; }
.badge    { font-size: 0.7rem; font-weight: 600; letter-spacing: 0.05em; text-transform: uppercase; border-radius: 999px; padding: 0.3rem 0.8rem; border: 1px solid; }
.badge-row { display: flex; gap: 0.6rem; margin-top: 0.8rem; flex-wrap: wrap; }
footer { text-align: center; padding: 1.5rem; font-size: 0.8rem; color: var(--muted); border-top: 1px solid var(--border); background: var(--bg); }

/* ── CSV download button ── */
.csv-bar { display: flex; align-items: center; gap: 16px; padding: 0.75rem 3rem; background: var(--surface); border-bottom: 1px solid var(--border); }
.csv-btn  { display: inline-flex; align-items: center; gap: 6px; padding: 0.5rem 1rem; background: var(--surface); color: var(--text); font-size: 0.85rem; font-weight: 600; border: 1px solid var(--border2); border-radius: 6px; text-decoration: none; transition: all 0.15s; box-shadow: var(--shadow-sm); }
.csv-btn:hover { border-color: var(--blue); color: var(--blue); background: var(--bg); }
.csv-btn-full { background: var(--blue); color: #fff; border-color: var(--blue); }
.csv-btn-full:hover { background: #1D4ED8; color: #fff; border-color: #1D4ED8; }
.csv-bar-label { font-size: 0.8rem; color: var(--muted); font-weight: 500; }
"""

def _csv_bar(date_str: str, elite: bool = False) -> str:
    scan_date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%Y-%m-%d")
    if elite:
        primary = f"passing_ema10_{date_str}.csv"
        label   = "⬇ Download Elite CSV"
        note    = f"Elite Stocks · Scan date: {scan_date_display}"
    else:
        primary = f"passing_stocks_{date_str}.csv"
        label   = "⬇ Download CSV"
        note    = f"Passing Stocks · Scan date: {scan_date_display}"
    full = f"full_results_{date_str}.csv"
    return f"""
<div class="csv-bar">
  <a class="csv-btn csv-btn-full" href="{primary}" download="{primary}">{label}</a>
  <a class="csv-btn" href="{full}" download="{full}">⬇ Full Results CSV</a>
  <span class="csv-bar-label">{note}</span>
</div>"""

_TABLE_SORT_JS = """
let sortCol = null, sortAsc = true;
document.querySelectorAll('#mainTable thead th').forEach(th => {
  th.addEventListener('click', () => {
    const col  = th.dataset.col;
    const type = th.dataset.type;
    if (!col) return;
    sortAsc = (sortCol === col) ? !sortAsc : true;
    sortCol = col;
    document.querySelectorAll('#mainTable thead th')
      .forEach(h => h.classList.remove('sort-asc','sort-desc'));
    th.classList.add(sortAsc ? 'sort-asc' : 'sort-desc');
    const tbody = document.getElementById('tableBody');
    Array.from(tbody.querySelectorAll('.srow'))
      .sort((a, b) => {
        let av = a.dataset[col], bv = b.dataset[col];
        if (type === 'num') {
          av = parseFloat(av); bv = parseFloat(bv);
          if (isNaN(av)) av = -Infinity;
          if (isNaN(bv)) bv = -Infinity;
          return sortAsc ? av - bv : bv - av;
        }
        return sortAsc ? av.localeCompare(bv) : bv.localeCompare(av);
      })
      .forEach(r => tbody.appendChild(r));
  });
});
"""

_FILTER_JS = """
function filterRows() {
  const q = document.getElementById('searchInput').value.toLowerCase();
  document.querySelectorAll('#tableBody .srow').forEach(r => {
    const sym    = (r.dataset.sym    || '').toLowerCase();
    const indgrp = (r.dataset.indgrp || '').toLowerCase();
    const ind    = (r.dataset.ind    || '').toLowerCase();
    r.style.display = (sym.includes(q) || indgrp.includes(q) || ind.includes(q)) ? '' : 'none';
  });
}
"""

_CHARTJS_DEFAULTS = """
Chart.defaults.font.family = "'Inter', sans-serif";
Chart.defaults.font.size   = 12;
Chart.defaults.color       = "#64748B";
Chart.defaults.scale.grid.color = "#E2E8F0";
"""


def _html_head(title: str, accent: str = "var(--blue)") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>{title}</title>
<script src="{_CDN_CHARTJS}"></script>
<link href="{_GOOGLE_FONTS}" rel="stylesheet"/>
<style>{_BASE_CSS}</style>
</head>
<body>
"""


# ─────────────────────────────────────────────────────────────────────────────
#  PASSING STOCKS DASHBOARD  (all 8 Minervini conditions)
# ─────────────────────────────────────────────────────────────────────────────

def build_passing_dashboard(passing: pd.DataFrame, out_path: Path, date_str: str) -> None:
    date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%d %b %Y")

    n_stocks    = len(passing)
    n_above_ema = int(passing.get("cond9_price_above_ema10", pd.Series(dtype=bool)).sum()) \
                  if "cond9_price_above_ema10" in passing.columns else "N/A"
    total_tmc_s = fmt_cr(passing["total_market_cap_cr"].dropna().sum()) \
                  if "total_market_cap_cr" in passing.columns else "N/A"
    total_tv_s  = fmt_cr(passing["traded_value_cr"].dropna().sum()) \
                  if "traded_value_cr" in passing.columns else "N/A"

    rows_html = ""
    chart_labels, chart_total = [], []

    for _, row in passing.sort_values("rs_percentile", ascending=False).iterrows():
        sym        = str(row.get("symbol", "")).replace(".NS", "")
        link       = _tv_link(row.get("symbol", sym))
        close      = row.get("close", np.nan)
        ema10      = row.get("EMA10",  np.nan)
        rs         = row.get("rs_percentile", np.nan)
        tmc        = row.get("total_market_cap_cr", np.nan)
        tv         = row.get("traded_value_cr", np.nan)
        tvpct      = row.get("traded_val_pct_mc", np.nan)
        ind_grp    = str(row.get("industry_group", "")) or "—"
        industry   = str(row.get("industry", ""))       or "—"
        result_date = row.get("result_date", "—")
        price_band = str(row.get("price_band", "—"))

        close_s = f"{float(close):,.2f}" if _safe(close) else "N/A"
        ema10_s = f"{float(ema10):,.2f}" if _safe(ema10) else "N/A"
        rs_s    = f"{float(rs):.1f}"       if _safe(rs)    else "N/A"
        tmc_s   = fmt_cr(tmc)
        tv_s    = fmt_cr(tv)
        tvpct_s = f"{float(tvpct):.4f}%"  if _safe(tvpct) else "N/A"

        try:
            above_ema = float(close) > float(ema10)
            ema_col = "var(--emerald)" if above_ema else "var(--red)"
            ema_bg  = "var(--green-bg)" if above_ema else "var(--red-bg)"
            ema_bdr = "var(--green-mid)" if above_ema else "var(--red-mid)"
        except Exception:
            ema_col = "var(--muted)"; ema_bg = "var(--bg)"; ema_bdr = "var(--border2)"

        rows_html += f"""
        <tr class="srow"
          data-sym="{sym}" data-close="{_r(close)}" data-rs="{_r(rs)}"
          data-ema10="{_r(ema10)}" data-tmc="{_r(tmc)}"
          data-tv="{_r(tv)}" data-tvpct="{_r(tvpct, 6)}"
          data-indgrp="{ind_grp}" data-ind="{industry}">
          <td><a class="sym-tag"
                 style="background:var(--blue-bg);border-color:var(--blue-mid);color:var(--blue)"
                 href="{link}" target="_blank" rel="noopener">{sym}</a></td>
          <td class="r">{close_s}</td>
          <td class="r"><span class="ema-tag"
               style="background:{ema_bg};border-color:{ema_bdr};color:{ema_col}">{ema10_s}</span></td>
          <td class="r"><span class="rs-tag">{rs_s}</span></td>
          <td class="r">{tmc_s}</td>
          <td class="r">{tv_s}</td>
          <td class="r">{tvpct_s}</td>
          <td>{ind_grp}</td>
          <td>{industry}</td>
          <td class="r">{result_date}</td>
          <td class="c">{price_band}</td>
        </tr>"""

        chart_labels.append(f'"{sym}"')
        chart_total.append(_r(tmc))

    html = _html_head(f"Market Cap Dashboard — {date_display}")
    html += _csv_bar(date_str, elite=False)
    html += f"""
<header>
  <div>
    <div class="logo-line">
      <div class="logo-dot" style="background:var(--blue)"></div>
      <span class="logo-tag" style="color:var(--blue)">Momentum Alpha · Minervini Scanner</span>
    </div>
    <h1>Market Cap Dashboard</h1>
    <p class="sub">Passing stocks · EMA10 filter · Market cap &amp; traded value · NSE data</p>
  </div>
  <div class="date-chip" style="background:var(--blue-bg);border-color:var(--blue-mid);color:var(--blue)">{date_display}</div>
</header>

<div class="kpi-row">
  <div class="kpi blue"><div class="kpi-accent"></div>
    <div class="kpi-label">Passing Stocks</div><div class="kpi-val">{n_stocks}</div></div>
  <div class="kpi purple"><div class="kpi-accent"></div>
    <div class="kpi-label">Above EMA10</div><div class="kpi-val">{n_above_ema}</div></div>
  <div class="kpi teal"><div class="kpi-accent"></div>
    <div class="kpi-label">Total Market Cap</div><div class="kpi-val">₹{total_tmc_s}</div></div>
  <div class="kpi green"><div class="kpi-accent"></div>
    <div class="kpi-label">Total Traded Value</div><div class="kpi-val">₹{total_tv_s}</div></div>
</div>

<div class="charts-grid" style="grid-template-columns:1fr">
  <div class="chart-card">
    <div class="chart-title">Total Market Cap (₹ Cr)</div>
    <div class="chart-wrap"><canvas id="barChart"></canvas></div>
  </div>
</div>
<div class="table-section">
  <div class="sec-head">
    <span class="sec-title">Passing Stocks Detail</span>
    <div class="controls">
      <div class="legend">
        <div class="leg-item"><div class="leg-dot" style="background:var(--emerald)"></div>Close &gt; EMA10</div>
        <div class="leg-item"><div class="leg-dot" style="background:var(--red)"></div>Close ≤ EMA10</div>
      </div>
      <input class="search-input" id="searchInput" type="text"
             placeholder="Search symbol / industry…" oninput="filterRows()"/>
    </div>
  </div>
  <div class="tbl-wrap">
    <table id="mainTable">
      <thead><tr>
        <th data-col="sym"    data-type="str">Symbol<i class="si"></i></th>
        <th class="r" data-col="close"  data-type="num">Close ₹<i class="si"></i></th>
        <th class="r" data-col="ema10"  data-type="num">EMA10 ₹<i class="si"></i></th>
        <th class="r" data-col="rs"     data-type="num">RS %ile<i class="si"></i></th>
        <th class="r" data-col="tmc"    data-type="num">Total Mkt Cap<i class="si"></i></th>
        <th class="r" data-col="tv"     data-type="num">Traded Value<i class="si"></i></th>
        <th class="r" data-col="tvpct"  data-type="num">TV % of Mkt Cap<i class="si"></i></th>
        <th          data-col="indgrp" data-type="str">Industry Group<i class="si"></i></th>
        <th          data-col="ind"    data-type="str">Industry<i class="si"></i></th>
        <th class="r" data-col="result" data-type="str">Result Date<t class="si"></i></th>
        <th class="c" data-col="priceband" data-type="str">Price Band<i class="si"></i></th>
      </tr></thead>
      <tbody id="tableBody">{rows_html}</tbody>
    </table>
  </div>
</div>

<footer>Data from NSE India &nbsp;·&nbsp; Generated {date_display} &nbsp;·&nbsp; For informational purposes only &nbsp;·&nbsp; Not financial advice</footer>

<script>
const labels    = [{",".join(chart_labels)}];
const totalData = [{",".join(chart_total)}];
{_CHARTJS_DEFAULTS}
new Chart(document.getElementById('barChart'), {{
  type:'bar',
  data:{{ labels, datasets:[
    {{ label:'Total Mkt Cap', data:totalData, backgroundColor:'#3B82F6',
       borderColor:'#2563EB', borderWidth:1, borderRadius:4, hoverBackgroundColor: '#2563EB' }},
  ]}},
  options:{{
    responsive:true, maintainAspectRatio:false,
    plugins:{{
      legend:{{ display: false }},
      tooltip:{{ backgroundColor:'#1E293B', titleColor:'#F8FAFC', bodyColor:'#F1F5F9', padding:12,
        callbacks:{{ label: c => ` ${{c.dataset.label}}: ₹${{(c.parsed.y||0).toLocaleString('en-IN')}} Cr` }} }},
    }},
    scales:{{
      y:{{ ticks:{{ callback: v=>'₹'+Number(v).toLocaleString('en-IN')}} }}
    }},
  }},
}});
{_FILTER_JS}
{_TABLE_SORT_JS}
</script>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    logger.info("Passing dashboard → %s", out_path)


# ─────────────────────────────────────────────────────────────────────────────
#  ELITE DASHBOARD  (all 8 conditions + above EMA10)
# ─────────────────────────────────────────────────────────────────────────────

def build_passing_ema10_dashboard(
    df: pd.DataFrame,
    out_path: Path,
    date_str: str,
    history: list[dict] | None = None,
) -> None:
    date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%d %b %Y")

    n_total     = len(df)
    total_tmc_s = fmt_cr(df["total_market_cap_cr"].dropna().sum()) \
                  if "total_market_cap_cr" in df.columns else "N/A"
    total_tv_s  = fmt_cr(df["traded_value_cr"].dropna().sum()) \
                  if "traded_value_cr" in df.columns else "N/A"

    rows_html = ""
    chart_labels, chart_total_mc = [], []

    for _, row in df.iterrows():
        sym      = str(row.get("symbol", "")).replace(".NS", "")
        link     = _tv_link(row.get("symbol", sym))
        close    = row.get("close",  np.nan)
        ema10    = row.get("EMA10",  np.nan)
        rs       = row.get("rs_percentile", np.nan)
        tmc      = row.get("total_market_cap_cr", np.nan)
        tv       = row.get("traded_value_cr", np.nan)
        tvpct    = row.get("traded_val_pct_mc", np.nan)
        ind_grp  = str(row.get("industry_group", "")) or "—"
        industry = str(row.get("industry", ""))       or "—"
        result_date = row.get("result_date", "—")
        price_band = str(row.get("price_band", "—"))

        close_s = f"{float(close):,.2f}" if _safe(close) else "N/A"
        ema10_s = f"{float(ema10):,.2f}" if _safe(ema10) else "N/A"
        rs_s    = f"{float(rs):.1f}"       if _safe(rs)    else "N/A"
        tmc_s   = fmt_cr(tmc)
        tv_s    = fmt_cr(tv)
        tvpct_s = f"{float(tvpct):.4f}%"  if _safe(tvpct) else "N/A"

        try:
            gap_pct = (float(close) - float(ema10)) / float(ema10) * 100
            gap_s   = f"+{gap_pct:.2f}%"
            gap_col = "var(--emerald)"
        except Exception:
            gap_pct = -1.0; gap_s = "N/A"; gap_col = "var(--muted)"

        rows_html += f"""
        <tr class="srow"
          data-sym="{sym}" data-close="{_r(close)}" data-ema10="{_r(ema10)}"
          data-gap="{_r(gap_pct, 4)}" data-rs="{_r(rs)}" data-tmc="{_r(tmc)}"
          data-tv="{_r(tv)}" data-tvpct="{_r(tvpct, 6)}"
          data-indgrp="{ind_grp}" data-ind="{industry}">
          <td><a class="sym-tag"
                 style="background:var(--green-bg);border-color:var(--green-mid);color:var(--emerald)"
                 href="{link}" target="_blank" rel="noopener">{sym}</a></td>
          <td class="r">{close_s}</td>
          <td class="r"><span class="ema-tag"
               style="background:var(--bg);border-color:var(--border2);color:var(--text)">{ema10_s}</span></td>
          <td class="r" style="color:{gap_col};font-weight:600">{gap_s}</td>
          <td class="r"><span class="rs-tag">{rs_s}</span></td>
          <td class="r">{tmc_s}</td>
          <td class="r">{tv_s}</td>
          <td class="r">{tvpct_s}</td>
          <td>{ind_grp}</td>
          <td>{industry}</td>
          <td class="r">{result_date}</td>
          <td class="c">{price_band}</td>
        </tr>"""

    hist = list(history) if history else []
    today_entry = {
        "date": date_str,
        "count": n_total,
        "market_cap_cr": float(df["total_market_cap_cr"].dropna().sum()) if "total_market_cap_cr" in df.columns else 0.0,
        "traded_value_cr": float(df["traded_value_cr"].dropna().sum()) if "traded_value_cr" in df.columns else 0.0,
    }
    hist = [h for h in hist if h.get("date") != date_str]
    hist.append(today_entry)
    hist.sort(key=lambda h: h["date"])

    def _fmt_date_label(d: str) -> str:
        try:
            return datetime.strptime(d, "%Y%m%d").strftime("%d %b")
        except Exception:
            return d

    hist_labels_js  = ",".join(f'"{_fmt_date_label(h["date"])}"' for h in hist)
    hist_count_js   = ",".join(str(int(h.get("count", 0)))         for h in hist)
    hist_mc_js      = ",".join(str(round(float(h.get("market_cap_cr", 0)), 2))     for h in hist)
    hist_tv_js      = ",".join(str(round(float(h.get("traded_value_cr", 0)), 2))   for h in hist)

    html = _html_head(f"Momentum Alpha — {date_display}")
    html += _csv_bar(date_str, elite=True)
    html += f"""
<header>
  <div>
    <div class="logo-line">
      <div class="logo-dot" style="background:var(--emerald)"></div>
      <span class="logo-tag" style="color:var(--emerald)">Momentum Alpha · Elite Filter</span>
    </div>
    <h1>Passing Stocks Above EMA10</h1>
    <p class="sub">All 8 Minervini conditions met &plus; Close &gt; 10-period EMA · NSE data</p>
    <div class="badge-row">
      <span class="badge" style="background:var(--green-bg);border-color:var(--green-mid);color:var(--emerald)">✓ 8 Conditions</span>
      <span class="badge" style="background:var(--blue-bg);border-color:var(--blue-mid);color:var(--blue)">✓ Close &gt; EMA10</span>
    </div>
  </div>
  <div class="date-chip" style="background:var(--green-bg);border-color:var(--green-mid);color:var(--emerald)">{date_display}</div>
</header>

<div class="kpi-row">
  <div class="kpi green"><div class="kpi-accent"></div>
    <div class="kpi-label">Elite Stocks</div><div class="kpi-val">{n_total}</div></div>
  <div class="kpi teal"><div class="kpi-accent"></div>
    <div class="kpi-label">Total Market Cap</div><div class="kpi-val">₹{total_tmc_s}</div></div>
  <div class="kpi blue"><div class="kpi-accent"></div>
    <div class="kpi-label">Total Traded Value</div><div class="kpi-val">₹{total_tv_s}</div></div>
</div>

<div class="charts-grid" style="grid-template-columns:1fr 1fr 1fr">
  <div class="chart-card">
    <div class="chart-title">Elite Stock Count</div>
    <div class="chart-wrap"><canvas id="countChart"></canvas></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">Combined Market Cap (₹ Cr)</div>
    <div class="chart-wrap"><canvas id="mcChart"></canvas></div>
  </div>
  <div class="chart-card">
    <div class="chart-title">Total Traded Value (₹ Cr)</div>
    <div class="chart-wrap"><canvas id="tvChart"></canvas></div>
  </div>
</div>

<div class="table-section">
  <div class="sec-head">
    <span class="sec-title">Elite Stocks Detail</span>
    <div class="controls">
      <input class="search-input" id="searchInput" type="text"
             placeholder="Search symbol / industry…" oninput="filterRows()"/>
    </div>
  </div>
  <div class="tbl-wrap">
    <table id="mainTable">
      <thead><tr>
        <th data-col="sym"    data-type="str">Symbol<i class="si"></i></th>
        <th class="r" data-col="close"  data-type="num">Close ₹<i class="si"></i></th>
        <th class="r" data-col="ema10"  data-type="num">EMA10 ₹<i class="si"></i></th>
        <th class="r" data-col="gap"    data-type="num">Gap % Above EMA10<i class="si"></i></th>
        <th class="r" data-col="rs"     data-type="num">RS %ile<i class="si"></i></th>
        <th class="r" data-col="tmc"    data-type="num">Total Mkt Cap<i class="si"></i></th>
        <th class="r" data-col="tv"     data-type="num">Traded Value<i class="si"></i></th>
        <th class="r" data-col="tvpct"  data-type="num">TV % of Mkt Cap<i class="si"></i></th>
        <th          data-col="indgrp" data-type="str">Industry Group<i class="si"></i></th>
        <th          data-col="ind"    data-type="str">Industry<i class="si"></i></th>
        <th class="r" data-col="result" data-type="str">Result Date<t class="si"></i></th>
        <th class="c" data-col="priceband" data-type="str">Price Band<i class="si"></i></th>
      </tr></thead>
      <tbody id="tableBody">{rows_html}</tbody>
    </table>
  </div>
</div>

<footer>Data from NSE India &nbsp;·&nbsp; Generated {date_display} &nbsp;·&nbsp; For informational purposes only &nbsp;·&nbsp; Not financial advice</footer>

<script>
const histLabels = [{hist_labels_js}];
const histCount  = [{hist_count_js}];
const histMC     = [{hist_mc_js}];
const histTV     = [{hist_tv_js}];
{_CHARTJS_DEFAULTS}

const _lineOpts = (yFmt, tooltipFmt) => ({{
  responsive: true, maintainAspectRatio: false,
  tension: 0.35,
  plugins: {{
    legend: {{ display: false }},
    tooltip: {{
      backgroundColor: '#1E293B', titleColor: '#F8FAFC', bodyColor: '#F1F5F9', padding: 12,
      callbacks: {{ label: tooltipFmt }},
    }},
  }},
  scales: {{
    x: {{ ticks: {{ maxTicksLimit: 7 }} }},
    y: {{ ticks: {{ callback: yFmt }} }},
  }},
}});

new Chart(document.getElementById('countChart'), {{
  type: 'line',
  data: {{ labels: histLabels, datasets: [{{
    label: 'Elite Stocks', data: histCount,
    borderColor: '#059669', backgroundColor: 'rgba(5,150,105,0.1)',
    borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#059669', fill: true,
  }}]}},
  options: _lineOpts( v => v, c => ` Elite Stocks: ${{c.parsed.y}}` ),
}});

new Chart(document.getElementById('mcChart'), {{
  type: 'line',
  data: {{ labels: histLabels, datasets: [{{
    label: 'Combined Mkt Cap', data: histMC,
    borderColor: '#0D9488', backgroundColor: 'rgba(13,148,136,0.1)',
    borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#0D9488', fill: true,
  }}]}},
  options: _lineOpts( v => '₹' + Number(v).toLocaleString('en-IN'), c => ` Mkt Cap: ₹${{(c.parsed.y||0).toLocaleString('en-IN')}} Cr` ),
}});

new Chart(document.getElementById('tvChart'), {{
  type: 'line',
  data: {{ labels: histLabels, datasets: [{{
    label: 'Traded Value', data: histTV,
    borderColor: '#2563EB', backgroundColor: 'rgba(37,99,235,0.1)',
    borderWidth: 2, pointRadius: 3, pointBackgroundColor: '#2563EB', fill: true,
  }}]}},
  options: _lineOpts( v => '₹' + Number(v).toLocaleString('en-IN'), c => ` Traded Value: ₹${{(c.parsed.y||0).toLocaleString('en-IN')}} Cr` ),
}});
{_FILTER_JS}
{_TABLE_SORT_JS}
</script>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    logger.info("Elite dashboard → %s", out_path)


# ─────────────────────────────────────────────────────────────────────────────
#  VOLUME ACTION DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────

def build_volume_action_dashboard(
    volume_df: pd.DataFrame,
    out_path: Path,
    date_str: str
) -> None:

    date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%d %b %Y")
    rows = ""

    for _, row in volume_df.sort_values("relative_volume", ascending=False).iterrows():
        sym        = str(row.get("symbol", "")).replace(".NS", "")
        close      = row.get("close", np.nan)
        rel_vol    = row.get("relative_volume", np.nan)
        rs         = row.get("rs_percentile", np.nan)
        ind_grp    = str(row.get("industry_group", "")) or "—"
        industry   = str(row.get("industry", "")) or "—"
        result_date = row.get("result_date", "—")
        price_band = str(row.get("price_band", "—"))

        rows += f"""
        <tr class='srow'
            data-sym="{sym}" data-indgrp="{ind_grp}" data-ind="{industry}"
            data-close="{_r(close)}" data-relvol="{_r(rel_vol)}" data-rs="{_r(rs)}">
            <td>
                <a class='sym-tag' style="background:var(--blue-bg);border-color:var(--blue-mid);color:var(--blue)"
                   href='{_tv_link(sym)}' target='_blank' rel='noopener'>{sym}</a>
            </td>
            <td class='r'>{"{:,.2f}".format(float(close)) if _safe(close) else "N/A"}</td>
            <td class='r' style="font-weight:600;color:var(--blue)">{"{:.1f}%".format(float(rel_vol)) if _safe(rel_vol) else "N/A"}</td>
            <td class='c'>
                <span class='badge' style='background:var(--blue-bg);color:var(--blue);border-color:var(--blue-mid);'>BLUE PPV</span>
            </td>
            <td class='c'>{'🔥' if row.get('bull_snort', False) else '-'}</td>
            <td class='r'><span class='rs-tag'>{round(float(rs),1) if _safe(rs) else "N/A"}</span></td>
            <td>{ind_grp}</td>
            <td>{industry}</td>
            <td class='r'>{result_date}</td>
            <td class="c">{price_band}</td>
        </tr>"""

    html = _html_head("Volume Action Dashboard") + f"""
<header>
  <div>
    <div class='logo-line'>
      <span class='logo-dot' style='background:var(--blue)'></span>
      <span class='logo-tag' style="color:var(--blue)">Momentum Alpha</span>
    </div>
    <h1>Volume Action</h1>
    <div class='sub'>Pocket Pivot / Blue Volume Stocks</div>
  </div>
  <div class='date-chip' style='border-color:var(--blue-mid);background:var(--blue-bg);color:var(--blue);'>{len(volume_df)} Stocks &nbsp;|&nbsp; {date_display}</div>
</header>

<div class="table-section" style="padding-top: 2rem;">
  <div class="sec-head">
    <span class="sec-title">Volume Action Stocks</span>
    <div class="controls">
      <input class="search-input" id="searchInput" type="text"
             placeholder="Search symbol / industry…" oninput="filterRows()"/>
    </div>
  </div>
  <div class='tbl-wrap'>
    <table id="mainTable">
      <thead>
        <tr>
          <th data-col="sym" data-type="str">Symbol<i class="si"></i></th>
          <th class='r' data-col="close" data-type="num">Close<i class="si"></i></th>
          <th class='r' data-col="relvol" data-type="num">Rel Volume<i class="si"></i></th>
          <th class='c'>Signal</th>
          <th class='c'>Bull Snort</th>
          <th class='r' data-col="rs" data-type="num">RS<i class="si"></i></th>
          <th data-col="indgrp" data-type="str">Industry Group<i class="si"></i></th>
          <th data-col="ind" data-type="str">Industry<i class="si"></i></th>
          <th class="r" data-col="result" data-type="str">Result Date<i class="si"></i></th>
          <th class="c" data-col="priceband" data-type="str">Price Band<i class="si"></i></th>
        </tr>
      </thead>
      <tbody id="tableBody">{rows}</tbody>
    </table>
  </div>
</div>
<footer>Data from NSE India &nbsp;·&nbsp; Generated {date_display}</footer>
<script>
{_FILTER_JS}
{_TABLE_SORT_JS}
</script>
</body>
</html>
"""
    out_path.write_text(html, encoding='utf-8')
    logger.info("Volume action dashboard → %s", out_path)

# ─────────────────────────────────────────────────────────────────────────────
#  ROCKET DASHBOARD  (all 8 conditions + Inside Bar on latest close)
# ─────────────────────────────────────────────────────────────────────────────

def build_rocket_dashboard(
    passing: pd.DataFrame,
    out_path: Path,
    date_str: str,
) -> None:

    date_display = datetime.strptime(date_str, "%Y%m%d").strftime("%d %b %Y")

    rocket = passing[passing["inside_bar"] == True].copy() \
             if "inside_bar" in passing.columns else pd.DataFrame()

    n_rocket  = len(rocket)
    n_passing = len(passing)

    rows_html = ""

    if n_rocket == 0:
        rows_html = """
        <tr><td colspan="9" style="text-align:center;padding:60px;color:var(--muted)">
          No Rocket Stocks today — no inside bars found among passing stocks.
        </td></tr>"""
    else:
        for _, row in rocket.sort_values("rs_percentile", ascending=False).iterrows():
            sym      = str(row.get("symbol", "")).replace(".NS", "")
            link     = _tv_link(row.get("symbol", sym))
            close    = row.get("close",  np.nan)
            ema10    = row.get("EMA10",  np.nan)
            rs       = row.get("rs_percentile", np.nan)
            tmc      = row.get("total_market_cap_cr", np.nan)
            tv       = row.get("traded_value_cr", np.nan)
            hi52_pct = row.get("pct_from_52w_high", np.nan)
            lo52_pct = row.get("pct_above_52w_low", np.nan)
            ind_grp  = str(row.get("industry_group", "")) or "—"
            industry = str(row.get("industry", ""))       or "—"

            close_s  = f"{float(close):,.2f}" if _safe(close) else "N/A"
            ema10_s  = f"{float(ema10):,.2f}" if _safe(ema10) else "N/A"
            rs_s     = f"{float(rs):.1f}"       if _safe(rs)    else "N/A"
            tmc_s    = fmt_cr(tmc)
            tv_s     = fmt_cr(tv)

            if not _safe(hi52_pct) and _safe(close) and _safe(row.get("52w_high")):
                hi52_pct = (float(close) / float(row["52w_high"]) - 1) * 100
            if not _safe(lo52_pct) and _safe(close) and _safe(row.get("52w_low")):
                lo52_pct = (float(close) / float(row["52w_low"]) - 1) * 100

            hi52_s = f"{float(hi52_pct):+.1f}%" if _safe(hi52_pct) else "N/A"
            lo52_s = f"{float(lo52_pct):+.1f}%" if _safe(lo52_pct) else "N/A"

            rows_html += f"""
            <tr class="srow"
              data-sym="{sym}" data-close="{_r(close)}" data-rs="{_r(rs)}"
              data-ema10="{_r(ema10)}" data-tmc="{_r(tmc)}" data-tv="{_r(tv)}"
              data-indgrp="{ind_grp}" data-ind="{industry}">
              <td>
                <a class="sym-tag"
                   style="background:var(--amber-bg);border-color:var(--amber-mid);color:var(--amber)"
                   href="{link}" target="_blank" rel="noopener">{sym}</a>
                <span style="font-size:0.65rem;background:var(--amber-bg);
                             border:1px solid var(--amber-mid);color:var(--amber);padding:2px 6px;
                             border-radius:4px;font-weight:700;margin-left:6px">IB</span>
              </td>
              <td class="r">{close_s}</td>
              <td class="r"><span class="ema-tag"
                   style="background:var(--bg);border-color:var(--border2);color:var(--text)">{ema10_s}</span></td>
              <td class="r"><span class="rs-tag">{rs_s}</span></td>
              <td class="r" style="color:var(--emerald);font-weight:600">{lo52_s}</td>
              <td class="r" style="color:var(--amber);font-weight:600">{hi52_s}</td>
              <td class="r">{tmc_s}</td>
              <td class="r">{tv_s}</td>
              <td>{ind_grp}</td>
            </tr>"""

    html = _html_head(f"Rocket Stocks — {date_display}")
    html += f"""
<header>
  <div>
    <div class="logo-line">
      <div class="logo-dot" style="background:var(--amber)"></div>
      <span class="logo-tag" style="color:var(--amber)">Momentum Alpha · Rocket Stocks</span>
    </div>
    <h1>🚀 Rocket Stocks</h1>
    <p class="sub">All 8 Minervini conditions met &plus; Inside Bar on latest close · NSE data</p>
    <div class="badge-row">
      <span class="badge" style="background:var(--amber-bg);border-color:var(--amber-mid);color:var(--amber)">✓ 8 Conditions</span>
      <span class="badge" style="background:var(--amber-bg);border-color:var(--amber-mid);color:var(--amber)">✓ Inside Bar</span>
    </div>
  </div>
  <div class="date-chip" style="background:var(--amber-bg);border-color:var(--amber-mid);color:var(--amber)">{date_display}</div>
</header>

<div class="kpi-row">
  <div class="kpi amber"><div class="kpi-accent"></div>
    <div class="kpi-label">Rocket Stocks</div>
    <div class="kpi-val">{n_rocket}</div>
  </div>
  <div class="kpi blue"><div class="kpi-accent"></div>
    <div class="kpi-label">Total Passing Stocks</div>
    <div class="kpi-val">{n_passing}</div>
  </div>
  <div class="kpi green"><div class="kpi-accent"></div>
    <div class="kpi-label">Inside Bar Hit Rate</div>
    <div class="kpi-val">{100*n_rocket/n_passing:.1f}%</div>
  </div>
</div>

<div style="padding:1rem 3rem 0;font-size:0.85rem;color:var(--muted)">
  <strong style="color:var(--text)">Inside Bar:</strong>
  Today's high &lt; yesterday's high <strong>AND</strong> today's low &gt; yesterday's low —
  price compression inside a strong uptrend. A potential coiling setup before breakout.
</div>

<div class="table-section" style="padding-top: 1.5rem;">
  <div class="sec-head">
    <span class="sec-title">Rocket Stocks</span>
    <div class="controls">
      <input class="search-input" id="searchInput" type="text"
             placeholder="Search symbol / industry…" oninput="filterRows()"/>
    </div>
  </div>
  <div class="tbl-wrap">
    <table id="mainTable">
      <thead><tr>
        <th data-col="sym"   data-type="str">Symbol<i class="si"></i></th>
        <th class="r" data-col="close" data-type="num">Close ₹<i class="si"></i></th>
        <th class="r" data-col="ema10" data-type="num">EMA10 ₹<i class="si"></i></th>
        <th class="r" data-col="rs"    data-type="num">RS %ile<i class="si"></i></th>
        <th class="r">% above 52W Low</th>
        <th class="r">% from 52W High</th>
        <th class="r" data-col="tmc"   data-type="num">Mkt Cap<i class="si"></i></th>
        <th class="r" data-col="tv"    data-type="num">Traded Value<i class="si"></i></th>
        <th data-col="indgrp" data-type="str">Industry Group<i class="si"></i></th>
      </tr></thead>
      <tbody id="tableBody">{rows_html}</tbody>
    </table>
  </div>
</div>

<footer>Data from NSE India &nbsp;·&nbsp; Generated {date_display} &nbsp;·&nbsp; For informational purposes only &nbsp;·&nbsp; Not financial advice</footer>

<script>
{_FILTER_JS}
{_TABLE_SORT_JS}
</script>
</body></html>"""

    out_path.write_text(html, encoding="utf-8")
    logger.info("Rocket dashboard → %s  (%d stocks)", out_path, n_rocket)
