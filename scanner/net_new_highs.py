"""
scanner/net_new_highs.py
-------------------------
Net New Highs (NNH) — NSE market-breadth indicator.

Methodology follows Nitin R's "Net New Highs" script
(https://finallynitin.substack.com/p/net-new-highs-script):

  NNH = (# stocks making a new 52-week high today) - (# stocks making a
        new 52-week low today)

  • Bias is BULLISH when NNH stays positive for 3 consecutive sessions,
    BEARISH when it stays negative for 3 consecutive sessions.
  • A 10-day SMA of NNH is also tracked to reduce whipsaws — the smoothed
    bias is bullish/bearish based on the sign of that average.

This module computes today's counts from the scanner's full results
DataFrame (one row per symbol, with `is_52w_high` / `is_52w_low` flags
already computed in data_loader.py), appends them to a small persistent
history CSV so the rolling/SMA bias can be tracked day over day, and
renders an HTML card for the landing page (docs/index.html).
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd

from .config import DATA_DIR

logger = logging.getLogger(__name__)

HISTORY_PATH = DATA_DIR / "net_new_highs_history.csv"
SMA_WINDOW   = 10
BIAS_STREAK  = 3


# ── 1. Today's counts ─────────────────────────────────────────────────────────

def compute_today_counts(df: pd.DataFrame) -> dict:
    """
    Count new 52-week highs / lows from the full scan results DataFrame.
    Expects boolean columns `is_52w_high` and `is_52w_low` (added in
    data_loader.py). Returns a dict with new_highs, new_lows, net, total.
    """
    if df is None or df.empty or "is_52w_high" not in df.columns or "is_52w_low" not in df.columns:
        return {"new_highs": 0, "new_lows": 0, "net": 0, "total": 0}

    valid      = df.dropna(subset=["is_52w_high", "is_52w_low"])
    new_highs  = int(valid["is_52w_high"].sum())
    new_lows   = int(valid["is_52w_low"].sum())
    total      = int(len(valid))

    return {
        "new_highs": new_highs,
        "new_lows":  new_lows,
        "net":       new_highs - new_lows,
        "total":     total,
    }


# ── 2. Persistent history (for streak + SMA bias) ────────────────────────────

def _load_history() -> pd.DataFrame:
    if HISTORY_PATH.exists():
        try:
            return pd.read_csv(HISTORY_PATH, parse_dates=["date"])
        except Exception as exc:
            logger.warning("Could not read NNH history (%s) — starting fresh.", exc)
    return pd.DataFrame(columns=["date", "new_highs", "new_lows", "net", "total"])


def _save_history(hist: pd.DataFrame) -> None:
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    hist.to_csv(HISTORY_PATH, index=False)


def update_history(date_str: str, counts: dict) -> pd.DataFrame:
    """
    Append/overwrite today's row (keyed by date_str, format YYYY-MM-DD) into
    the NNH history CSV and return the updated, date-sorted history.
    """
    hist = _load_history()
    date_ts = pd.Timestamp(date_str)

    hist = hist[hist["date"] != date_ts]  # replace if re-run same day
    new_row = pd.DataFrame([{
        "date":      date_ts,
        "new_highs": counts["new_highs"],
        "new_lows":  counts["new_lows"],
        "net":       counts["net"],
        "total":     counts["total"],
    }])
    hist = pd.concat([hist, new_row], ignore_index=True).sort_values("date").reset_index(drop=True)
    _save_history(hist)
    return hist


# ── 3. Bias / stats derived from history ──────────────────────────────────────

def _consecutive_bias(net_series: pd.Series, streak: int = BIAS_STREAK) -> str:
    """'bullish' if the last `streak` values are all > 0, 'bearish' if all < 0, else 'neutral'."""
    tail = net_series.tail(streak)
    if len(tail) < streak:
        return "neutral"
    if (tail > 0).all():
        return "bullish"
    if (tail < 0).all():
        return "bearish"
    return "neutral"


def compute_stats(history: pd.DataFrame) -> dict:
    """
    Build the full NNH stats dict used to render the dashboard card:
      today's high/low/net/total, raw 3-day bias, smoothed 10-day SMA + bias,
      and a short recent series for a sparkline.
    """
    if history.empty:
        return {
            "available": False,
            "new_highs": 0, "new_lows": 0, "net": 0, "total": 0,
            "pct_highs": 0.0, "pct_lows": 0.0,
            "bias": "neutral", "sma": 0.0, "sma_bias": "neutral",
            "history": [],
        }

    history = history.sort_values("date").reset_index(drop=True)
    history["sma"] = history["net"].rolling(window=SMA_WINDOW, min_periods=1).mean()

    today = history.iloc[-1]
    bias     = _consecutive_bias(history["net"])
    sma_val  = float(today["sma"])
    sma_bias = "bullish" if sma_val > 0 else ("bearish" if sma_val < 0 else "neutral")

    total = float(today["total"]) or 1.0
    pct_highs = round(100.0 * today["new_highs"] / total, 1)
    pct_lows  = round(100.0 * today["new_lows"]  / total, 1)

    recent = history.tail(20)[["date", "net", "sma"]].copy()
    recent["date"] = recent["date"].dt.strftime("%Y-%m-%d")

    return {
        "available":  True,
        "new_highs":  int(today["new_highs"]),
        "new_lows":   int(today["new_lows"]),
        "net":        int(today["net"]),
        "total":      int(today["total"]),
        "pct_highs":  pct_highs,
        "pct_lows":   pct_lows,
        "bias":       bias,        # 3-day consecutive raw bias
        "sma":        round(sma_val, 1),
        "sma_bias":   sma_bias,    # 10-day SMA bias
        "history":    recent.to_dict("records"),
    }


def run(df: pd.DataFrame, date_str: str) -> dict:
    """Convenience entry-point: compute → persist → return rendered stats."""
    counts  = compute_today_counts(df)
    history = update_history(date_str, counts)
    stats   = compute_stats(history)
    logger.info(
        "Net New Highs — highs:%d lows:%d net:%d (3d bias:%s, 10-SMA:%.1f/%s)",
        stats["new_highs"], stats["new_lows"], stats["net"],
        stats["bias"], stats["sma"], stats["sma_bias"],
    )
    return stats


# ── 4. HTML card for the landing page ─────────────────────────────────────────

def build_html(stats: dict) -> str:
    """Render the Net New Highs card as a self-contained HTML block."""
    if not stats.get("available"):
        return """
<div class="sentiment-section">
  <h2 class="section-title">Net New Highs</h2>
  <div class="sentiment-card" style="max-width:480px">
    <div class="close-val">No data yet — runs after the first scan.</div>
  </div>
</div>"""

    badge_map = {
        "bullish": ("bullish", "🟢 Bullish"),
        "bearish": ("bearish", "🔴 Bearish"),
        "neutral": ("mixed",   "🟡 Neutral"),
    }
    bias_css, bias_label       = badge_map.get(stats["bias"],     ("mixed", "🟡 Neutral"))
    sma_css,  sma_label        = badge_map.get(stats["sma_bias"], ("mixed", "🟡 Neutral"))

    net      = stats["net"]
    net_css  = "green" if net > 0 else ("red" if net < 0 else "na")
    net_str  = f"{net:+d}"

    # Tiny inline sparkline of recent NNH net values (no JS dependency)
    hist = stats.get("history", [])
    if hist:
        vals = [h["net"] for h in hist]
        vmax = max(1, max(abs(v) for v in vals))
        bars = ""
        for h in hist:
            v = h["net"]
            height = max(4, round(abs(v) / vmax * 26))
            color  = "var(--emerald)" if v >= 0 else "var(--red)"
            align  = "flex-end" if v >= 0 else "flex-start"
            bars += (
                f'<div title="{h["date"]}: {v:+d}" '
                f'style="width:7px;height:28px;display:flex;align-items:{align}">'
                f'<div style="width:100%;height:{height}px;background:{color};border-radius:2px"></div>'
                f"</div>"
            )
        sparkline = f'<div style="display:flex;gap:2px;align-items:center;margin-top:.6rem">{bars}</div>'
    else:
        sparkline = ""

    return f"""
<div class="sentiment-section">
  <div style="display:flex;align-items:center;gap:1rem;margin-bottom:.25rem;">
    <h2 class="section-title" style="margin-bottom:0">Net New Highs</h2>
    <span class="overall-badge {bias_css}">{bias_label}</span>
  </div>
  <p style="font-size:.8rem;color:var(--muted);margin-bottom:.75rem;">
    NSE stocks making new 52-week highs minus new 52-week lows &middot;
    bias confirmed after {BIAS_STREAK} consecutive days &middot; smoothed with a {SMA_WINDOW}-day SMA.
  </p>
  <div class="sentiment-grid">
    <div class="sentiment-card">
      <div class="sentiment-card-header">
        <span class="sentiment-index-name">Today's Breadth</span>
      </div>
      <div class="close-val">Net New Highs: <strong>{net_str}</strong>
        &nbsp;(<span style="color:var(--emerald)">{stats['new_highs']} highs</span> /
        <span style="color:var(--red)">{stats['new_lows']} lows</span>
        of {stats['total']} stocks)</div>
      <div class="ema-row">
        <span class="ema-pill {net_css}"><span class="ema-dot {net_css}"></span>{stats['pct_highs']}% at new highs</span>
        <span class="ema-pill {'red' if stats['pct_lows'] else 'na'}"><span class="ema-dot {'red' if stats['pct_lows'] else 'na'}"></span>{stats['pct_lows']}% at new lows</span>
      </div>
      {sparkline}
      <div class="sentiment-legend">3-day confirmed bias &middot; bars = last 20 sessions' net reading</div>
    </div>
    <div class="sentiment-card">
      <div class="sentiment-card-header">
        <span class="sentiment-index-name">10-Day Smoothed Bias</span>
        <span class="overall-badge {sma_css}">{sma_label}</span>
      </div>
      <div class="close-val">10-SMA of Net New Highs: <strong>{stats['sma']:+.1f}</strong></div>
      <div class="sentiment-legend">Smoothing reduces day-to-day whipsaws in the raw NNH reading.</div>
    </div>
  </div>
</div>"""
