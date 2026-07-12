#!/usr/bin/env python3
"""
PSU strategy backtester.

Reads Evaluation/Indicators/*.csv, simulates the buy/sell logic on historical
data, and writes:
  Validation/results/summary.csv   — tabular results for every period × ticker
  Validation/results/report.html   — interactive HTML report with equity curves

Usage:
  python Validation/backtest.py

Edit TEST_PERIODS below to add or remove date ranges. Re-run any time to refresh
results against the latest indicator CSVs.
"""

import sys
import json
import logging
import math
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backtest")

BASE_DIR = Path(__file__).parent.parent
IND_DIR  = BASE_DIR / "Evaluation" / "Indicators"
OUT_DIR  = Path(__file__).parent / "results"

# ── Configuration ──────────────────────────────────────────────────────────────
INITIAL_BALANCE = 100.0
ADX_THRESHOLD   = 20
SMA_LOOKBACK    = 100   # rolling window for fibonacci swing (matches main.py)
EQUITY_MAX_PTS  = 600   # sub-sample equity curves for the HTML chart

# (label, start_date_str_or_None, end_date_str_or_None)
# None start → ticker's earliest available data
# None end   → latest row in the indicator CSV
TEST_PERIODS = [
    ("2025",     "2025-01-01", "2026-01-01"),
    ("2024",     "2024-01-01", "2025-01-01"),
    ("2yr",      "2024-01-01", None),
    ("5yr",      "2021-01-01", None),
    ("10yr",     "2016-01-01", None),
    ("all-time", None,         None),
]


# ── Signal computation ─────────────────────────────────────────────────────────

def compute_signals(df: pd.DataFrame) -> list:
    """
    Compute Buy/Sell/Hold for each row of an indicator DataFrame.
    Mirrors evaluate_signal() logic using the pre-computed indicator columns.

    Voting: SMA/LMA-fibonacci + RSI + Bollinger Band, majority rule.
    Gate: suppress directional signal when ADX < ADX_THRESHOLD (no trend).
    """
    close = df["Close"].to_numpy(dtype=float)
    sma20 = df["SMA20"].to_numpy(dtype=float)
    sma50 = df["SMA50"].to_numpy(dtype=float)
    rsi14 = df["RSI14"].to_numpy(dtype=float)
    bb_lo = df["BB_Lower"].to_numpy(dtype=float)
    bb_hi = df["BB_Upper"].to_numpy(dtype=float)
    adx14 = df["ADX14"].to_numpy(dtype=float)

    # Rolling max/min for the fibonacci support threshold (swing * 0.786)
    roll_max = pd.Series(close).rolling(SMA_LOOKBACK, min_periods=50).max().to_numpy()
    roll_min = pd.Series(close).rolling(SMA_LOOKBACK, min_periods=50).min().to_numpy()
    swing    = roll_max - roll_min
    support  = swing * 0.786

    signals = []
    for i in range(len(df)):
        if np.isnan(adx14[i]):
            signals.append("Hold")
            continue

        votes = []

        # SMA/LMA fibonacci crossover vote
        if not (np.isnan(sma20[i]) or np.isnan(sma50[i]) or np.isnan(swing[i])):
            diff = sma20[i] - sma50[i]
            if diff < -support[i]:
                votes.append("Buy")
            elif diff > support[i]:
                votes.append("Sell")

        # RSI vote
        if not np.isnan(rsi14[i]):
            if rsi14[i] < 30:
                votes.append("Buy")
            elif rsi14[i] > 70:
                votes.append("Sell")

        # Bollinger Band vote
        if not (np.isnan(bb_lo[i]) or np.isnan(bb_hi[i])):
            if close[i] < bb_lo[i]:
                votes.append("Buy")
            elif close[i] > bb_hi[i]:
                votes.append("Sell")

        if not votes:
            signals.append("Hold")
            continue

        # ADX gate: suppress signal when market is not trending
        if adx14[i] < ADX_THRESHOLD:
            signals.append("Hold")
            continue

        buy_v  = votes.count("Buy")
        sell_v = votes.count("Sell")
        if buy_v > sell_v:
            signals.append("Buy")
        elif sell_v > buy_v:
            signals.append("Sell")
        else:
            signals.append("Hold")

    return signals


def load_ticker(ticker: str) -> Optional[pd.DataFrame]:
    """
    Load indicator CSV and compute signals.
    Returns DataFrame with columns: Date (YYYY-MM-DD), Close, RSI14, Signal.
    """
    path = IND_DIR / f"{ticker}_indicators.csv"
    if not path.exists():
        return None
    df = pd.read_csv(str(path))
    df["Date"]   = pd.to_datetime(df["Datetime"], utc=True).dt.date.astype(str)
    df["Signal"] = compute_signals(df)
    df = df[["Date", "Close", "RSI14", "Signal"]].dropna(subset=["Close"])
    return df.reset_index(drop=True)


# ── Result dataclass ───────────────────────────────────────────────────────────

@dataclass
class Trade:
    date:   str
    action: str     # "Buy" | "Sell" | "Sell (EOD)"
    ticker: str
    price:  float
    shares: float
    value:  float   # portfolio value after trade

@dataclass
class Result:
    ticker:     str
    period:     str
    start_date: str
    end_date:   str
    start_bal:  float
    end_bal:    float
    bh_end_bal: float    # buy-and-hold terminal value
    equity:     list     # [(date_str, value), ...]
    trades:     list     # [Trade, ...]

    @property
    def return_pct(self) -> float:
        return (self.end_bal / self.start_bal - 1) * 100

    @property
    def bh_return_pct(self) -> float:
        return (self.bh_end_bal / self.start_bal - 1) * 100

    @property
    def alpha(self) -> float:
        return self.return_pct - self.bh_return_pct

    @property
    def n_trades(self) -> int:
        return sum(1 for t in self.trades if t.action == "Buy")

    @property
    def win_rate(self) -> Optional[float]:
        buys  = [t for t in self.trades if t.action == "Buy"]
        sells = [t for t in self.trades if t.action.startswith("Sell")]
        pairs = list(zip(buys, sells))
        if not pairs:
            return None
        wins = sum(1 for b, s in pairs if s.price > b.price)
        return 100.0 * wins / len(pairs)

    @property
    def max_drawdown(self) -> float:
        if not self.equity:
            return 0.0
        peak = self.start_bal
        worst = 0.0
        for _, v in self.equity:
            if v > peak:
                peak = v
            if peak > 0:
                worst = max(worst, (peak - v) / peak)
        return worst * 100.0

    @property
    def ann_return(self) -> Optional[float]:
        try:
            days = (
                datetime.strptime(self.end_date, "%Y-%m-%d") -
                datetime.strptime(self.start_date, "%Y-%m-%d")
            ).days
            if days <= 0:
                return None
            return ((self.end_bal / self.start_bal) ** (365.25 / days) - 1) * 100
        except Exception:
            return None


# ── Single-ticker backtest ─────────────────────────────────────────────────────

def run_single(
    ticker:     str,
    df:         pd.DataFrame,
    period:     str,
    start_date: Optional[str],
    end_date:   Optional[str],
    start_bal:  float = INITIAL_BALANCE,
) -> Optional[Result]:

    sub = df.copy()
    if start_date:
        sub = sub[sub["Date"] >= start_date]
    if end_date:
        sub = sub[sub["Date"] < end_date]
    sub = sub.reset_index(drop=True)

    if len(sub) < 2:
        return None

    balance   = start_bal
    shares    = 0.0
    in_market = False
    equity    = []
    trades    = []

    for _, row in sub.iterrows():
        price  = float(row["Close"])
        signal = row["Signal"]
        d      = row["Date"]

        if not in_market and signal == "Buy":
            shares    = balance / price
            balance   = 0.0
            in_market = True
            trades.append(Trade(d, "Buy", ticker,
                                round(price, 4), round(shares, 6), round(shares * price, 4)))

        elif in_market and signal == "Sell":
            balance = shares * price
            trades.append(Trade(d, "Sell", ticker,
                                round(price, 4), round(shares, 6), round(balance, 4)))
            shares    = 0.0
            in_market = False

        equity.append((d, round(balance + shares * price, 4)))

    # Liquidate any open position at the last close
    last = sub.iloc[-1]
    last_price = float(last["Close"])
    end_bal = balance + shares * last_price
    if in_market:
        trades.append(Trade(last["Date"], "Sell (EOD)", ticker,
                            round(last_price, 4), round(shares, 6), round(end_bal, 4)))

    first_close = float(sub.iloc[0]["Close"])
    bh_end_bal  = start_bal * (last_price / first_close) if first_close else start_bal

    return Result(
        ticker=ticker, period=period,
        start_date=sub.iloc[0]["Date"], end_date=last["Date"],
        start_bal=start_bal, end_bal=round(end_bal, 4), bh_end_bal=round(bh_end_bal, 4),
        equity=equity, trades=trades,
    )


# ── Multi-ticker backtest ──────────────────────────────────────────────────────

def run_multi(
    ticker_dfs: dict,
    period:     str,
    start_date: Optional[str],
    end_date:   Optional[str],
    start_bal:  float = INITIAL_BALANCE,
) -> Optional[Result]:
    """
    All-in sequential strategy across all tickers.

    Rules (per user spec):
    - In cash: buy the ticker with the lowest RSI that signals Buy today.
    - Holding ticker T: stay until T signals Sell. Ignore other tickers' buy signals.
    - Execute at same-day close price.
    - Tie-break multiple simultaneous Buy signals: pick the one with the lowest RSI.
    """
    # Slice each DataFrame to the requested period
    subs: dict = {}
    for t, df in ticker_dfs.items():
        sub = df.copy()
        if start_date:
            sub = sub[sub["Date"] >= start_date]
        if end_date:
            sub = sub[sub["Date"] < end_date]
        if not sub.empty:
            subs[t] = sub.set_index("Date")

    if not subs:
        return None

    all_dates = sorted(set().union(*(set(s.index) for s in subs.values())))
    if len(all_dates) < 2:
        return None

    balance     = start_bal
    held_ticker = None
    held_shares = 0.0
    equity      = []
    trades      = []

    # Pre-build lookup tables; track last known price for forward-fill
    last_known_price: dict = {}
    close_lut:  dict = {t: {} for t in subs}
    signal_lut: dict = {t: {} for t in subs}
    rsi_lut:    dict = {t: {} for t in subs}

    for t, sub in subs.items():
        for d, row in sub.iterrows():
            close_lut[t][d]  = float(row["Close"])
            signal_lut[t][d] = row["Signal"]
            rsi = row["RSI14"]
            rsi_lut[t][d]    = float(rsi) if not (isinstance(rsi, float) and math.isnan(rsi)) else 100.0

    for d in all_dates:
        # Update forward-fill prices
        for t in subs:
            if d in close_lut[t]:
                last_known_price[t] = close_lut[t][d]

        # --- Sell check ---
        if held_ticker is not None:
            signal = signal_lut[held_ticker].get(d, "Hold")
            price  = last_known_price.get(held_ticker)
            if price and signal == "Sell":
                balance = held_shares * price
                trades.append(Trade(d, "Sell", held_ticker,
                                    round(price, 4), round(held_shares, 6), round(balance, 4)))
                held_ticker = None
                held_shares = 0.0

        # --- Buy check ---
        if held_ticker is None:
            candidates = [
                (t, rsi_lut[t].get(d, 100.0), last_known_price[t])
                for t in subs
                if signal_lut[t].get(d) == "Buy" and t in last_known_price
            ]
            if candidates:
                best_t, _, best_price = min(candidates, key=lambda x: x[1])
                held_shares = balance / best_price
                balance     = 0.0
                held_ticker = best_t
                trades.append(Trade(d, "Buy", best_t,
                                    round(best_price, 4), round(held_shares, 6),
                                    round(held_shares * best_price, 4)))

        # --- Equity snapshot ---
        if held_ticker and held_ticker in last_known_price:
            val = balance + held_shares * last_known_price[held_ticker]
        else:
            val = balance
        equity.append((d, round(val, 4)))

    # Liquidate at end
    end_bal = balance
    if held_ticker and held_ticker in last_known_price:
        end_bal = held_shares * last_known_price[held_ticker]
        trades.append(Trade(all_dates[-1], "Sell (EOD)", held_ticker,
                            round(last_known_price[held_ticker], 4),
                            round(held_shares, 6), round(end_bal, 4)))

    # B&H reference: QQQ if available, else the first ticker alphabetically
    ref = "QQQ" if "QQQ" in subs else sorted(subs.keys())[0]
    ref_sub = subs[ref]
    ref_first = float(ref_sub.iloc[0]["Close"])
    ref_last  = float(ref_sub.iloc[-1]["Close"])
    bh_end_bal = start_bal * (ref_last / ref_first) if ref_first else start_bal

    return Result(
        ticker="MULTI", period=period,
        start_date=all_dates[0], end_date=all_dates[-1],
        start_bal=start_bal, end_bal=round(end_bal, 4), bh_end_bal=round(bh_end_bal, 4),
        equity=equity, trades=trades,
    )


# ── Output helpers ─────────────────────────────────────────────────────────────

def _subsample(equity: list) -> list:
    n = len(equity)
    if n <= EQUITY_MAX_PTS:
        return equity
    stride  = max(1, n // EQUITY_MAX_PTS)
    sampled = equity[::stride]
    if sampled[-1] != equity[-1]:
        sampled = sampled + [equity[-1]]
    return sampled


def _r2d(r: Result) -> dict:
    wr = r.win_rate
    ar = r.ann_return
    return {
        "start":    r.start_date,
        "end":      r.end_date,
        "end_bal":  round(r.end_bal, 2),
        "ret":      round(r.return_pct, 2),
        "bh_bal":   round(r.bh_end_bal, 2),
        "bh_ret":   round(r.bh_return_pct, 2),
        "alpha":    round(r.alpha, 2),
        "max_dd":   round(r.max_drawdown, 2),
        "n_trades": r.n_trades,
        "win_rate": round(wr, 1) if wr is not None else None,
        "ann_ret":  round(ar, 2) if ar is not None else None,
        "equity":   _subsample(r.equity),
        "trades":   [
            [t.date, t.action, t.ticker, round(t.price, 2), round(t.shares, 4), round(t.value, 2)]
            for t in r.trades if not t.action.startswith("Sell (EOD)")
        ],
    }


def write_csv(results: list, out_path: Path):
    rows = []
    for r in results:
        wr = r.win_rate
        ar = r.ann_return
        rows.append({
            "Period":        r.period,
            "Ticker":        r.ticker,
            "Start Date":    r.start_date,
            "End Date":      r.end_date,
            "Start Bal ($)": r.start_bal,
            "End Bal ($)":   round(r.end_bal, 2),
            "Return (%)":    round(r.return_pct, 2),
            "B&H End ($)":   round(r.bh_end_bal, 2),
            "B&H Return (%)":round(r.bh_return_pct, 2),
            "Alpha (%)":     round(r.alpha, 2),
            "Max DD (%)":    round(r.max_drawdown, 2),
            "N Trades":      r.n_trades,
            "Win Rate (%)":  round(wr, 1) if wr is not None else "",
            "Ann Return (%)":round(ar, 2) if ar is not None else "",
        })
    pd.DataFrame(rows).to_csv(str(out_path), index=False)
    logger.info(f"CSV written → {out_path}")


# ── HTML report ────────────────────────────────────────────────────────────────

REPORT_TMPL = """<title>PSU Backtest Report</title>
<style>
:root{
  --bg:#eef2f7;--sf:#fff;--sf2:#e4ecf5;--sf3:#f5f7fb;
  --ink:#0d1624;--ink2:#3a5068;--mu:#7590a8;
  --gr:#cdd8e6;--bd:rgba(20,60,100,.12);--acc:#1a56db;
  --c1:#1a56db;--c2:#0d9488;--c3:#c97b06;--c4:#059669;
  --pos:#059669;--neg:#dc2626;--tbg:#e9eff7;
}
@media(prefers-color-scheme:dark){:root{
  --bg:#070b12;--sf:#0e1520;--sf2:#162030;--sf3:#0b1219;
  --ink:#d4e4f4;--ink2:#7a98b8;--mu:#4a6278;
  --gr:#1a2840;--bd:rgba(100,180,255,.08);--acc:#4d8ef0;
  --c1:#4d8ef0;--c2:#14b8a6;--c3:#f59e0b;--c4:#10b981;
  --pos:#10b981;--neg:#f87171;--tbg:#111c2c;
}}
:root[data-theme=dark]{--bg:#070b12;--sf:#0e1520;--sf2:#162030;--sf3:#0b1219;--ink:#d4e4f4;--ink2:#7a98b8;--mu:#4a6278;--gr:#1a2840;--bd:rgba(100,180,255,.08);--acc:#4d8ef0;--c1:#4d8ef0;--c2:#14b8a6;--c3:#f59e0b;--c4:#10b981;--pos:#10b981;--neg:#f87171;--tbg:#111c2c}
:root[data-theme=light]{--bg:#eef2f7;--sf:#fff;--sf2:#e4ecf5;--sf3:#f5f7fb;--ink:#0d1624;--ink2:#3a5068;--mu:#7590a8;--gr:#cdd8e6;--bd:rgba(20,60,100,.12);--acc:#1a56db;--c1:#1a56db;--c2:#0d9488;--c3:#c97b06;--c4:#059669;--pos:#059669;--neg:#dc2626;--tbg:#e9eff7}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{background:var(--bg);color:var(--ink);font-family:system-ui,-apple-system,"Segoe UI",sans-serif;font-size:13px}
.app{max-width:1200px;margin:0 auto;padding:16px 16px 40px}
.hdr{display:flex;align-items:baseline;gap:12px;flex-wrap:wrap;padding:10px 0;border-bottom:1px solid var(--bd);margin-bottom:18px}
.htitle{font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:13px;font-weight:700;letter-spacing:.06em;color:var(--acc);text-transform:uppercase}
.hsub{font-size:11px;color:var(--mu);font-family:'SF Mono','Fira Code','Consolas',monospace}
/* Period tabs */
.period-tabs{display:flex;gap:3px;flex-wrap:wrap;margin-bottom:14px}
.ptab{font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:11px;font-weight:600;letter-spacing:.04em;padding:4px 10px;border-radius:3px;border:1px solid var(--bd);background:transparent;color:var(--mu);cursor:pointer;transition:color .1s,background .1s}
.ptab:hover{color:var(--ink2);background:var(--sf2)}
.ptab.on{background:var(--acc);color:#fff;border-color:var(--acc)}
/* Summary table */
.sec-title{font-size:10px;font-weight:700;letter-spacing:.10em;text-transform:uppercase;color:var(--mu);margin-bottom:8px}
.tbw{overflow-x:auto;border:1px solid var(--bd);border-radius:4px;margin-bottom:18px}
table{width:100%;border-collapse:collapse;font-size:11px;font-variant-numeric:tabular-nums;font-family:'SF Mono','Fira Code','Consolas',monospace;white-space:nowrap}
thead th{position:sticky;top:0;background:var(--sf2);border-bottom:1px solid var(--bd);padding:5px 10px;text-align:right;font-weight:600;letter-spacing:.04em;color:var(--mu);font-size:10px}
thead th:first-child{text-align:left}
tbody td{padding:3px 10px;text-align:right;border-bottom:1px solid var(--gr);color:var(--ink2)}
tbody td:first-child{text-align:left;color:var(--ink)}
tbody tr:last-child td{border-bottom:none}
tbody tr:hover td{background:var(--tbg)}
.pos{color:var(--pos)}
.neg{color:var(--neg)}
.bold{font-weight:700}
/* Chart area */
.chart-controls{display:flex;flex-wrap:wrap;gap:5px;margin-bottom:8px}
.tgl{font-family:'SF Mono','Fira Code','Consolas',monospace;font-size:10px;font-weight:600;padding:3px 8px;border-radius:3px;border:1px solid var(--bd);cursor:pointer;letter-spacing:.03em;background:transparent;color:var(--mu);transition:color .1s,background .1s,border-color .1s;opacity:.6}
.tgl:hover{opacity:1}
.tgl.on{opacity:1;color:#fff}
.cw{position:relative;border:1px solid var(--bd);border-radius:4px;overflow:hidden;background:var(--sf);height:260px;margin-bottom:18px}
canvas{display:block;width:100%;height:100%;cursor:crosshair}
/* Tooltip */
#tt{position:fixed;pointer-events:none;z-index:99;display:none;background:var(--sf);border:1px solid var(--bd);border-radius:5px;padding:8px 12px;box-shadow:0 4px 16px rgba(0,0,0,.18);min-width:160px;font-family:'SF Mono','Fira Code','Consolas',monospace}
.ttd{font-size:11px;font-weight:600;color:var(--ink);margin-bottom:5px}
.ttr{display:flex;justify-content:space-between;gap:14px;line-height:1.7;font-size:11px}
.ttl{color:var(--mu)}
.ttv{font-weight:500;color:var(--ink)}
.ttdiv{border:none;border-top:1px solid var(--bd);margin:4px 0 3px}
/* Trade log */
.tlog-hdr{display:flex;align-items:center;gap:8px;cursor:pointer;user-select:none;width:fit-content;margin-bottom:6px}
.tlog-arrow{font-size:10px;color:var(--mu);transition:transform .15s}
.tlog-arrow.open{transform:rotate(90deg)}
.tlog-lbl{font-size:10px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--mu)}
.tlog-hdr:hover .tlog-lbl,.tlog-hdr:hover .tlog-arrow{color:var(--ink2)}
.tlog-body[hidden]{display:none}
.period-section[hidden]{display:none}
</style>

<div class="app">
  <div class="hdr">
    <span class="htitle">PSU · Backtest Report</span>
    <span class="hsub" id="meta-line"></span>
  </div>

  <div class="period-tabs" id="period-tabs"></div>

  <div id="period-sections"></div>
</div>

<div id="tt"></div>

<script>
const R = @@REPORT_DATA@@;

// ── Palette (reads from CSS tokens) ─────────────────────────────────────────
const MONO = "'SF Mono','Fira Code','Cascadia Code','Consolas',monospace";
function tok(n){ return getComputedStyle(document.documentElement).getPropertyValue(n).trim() }
function isDark(){
  const t = document.documentElement.dataset.theme;
  return t==='dark'||(t!=='light'&&window.matchMedia('(prefers-color-scheme:dark)').matches);
}

// Fixed color for each series (MULTI gets special treatment)
const SERIES_COLORS_LIGHT = ['#1a56db','#0d9488','#c97b06','#059669','#7c3aed','#dc2626','#be185d','#ea580c'];
const SERIES_COLORS_DARK  = ['#4d8ef0','#14b8a6','#f59e0b','#10b981','#a78bfa','#f87171','#f472b6','#fb923c'];
const BH_COLOR_LIGHT = 'rgba(100,130,170,.50)';
const BH_COLOR_DARK  = 'rgba(100,160,220,.40)';

function seriesColor(idx){ const p=isDark()?SERIES_COLORS_DARK:SERIES_COLORS_LIGHT; return p[idx%p.length] }
function bhColor(){ return isDark()?BH_COLOR_DARK:BH_COLOR_LIGHT }

// ── Init ─────────────────────────────────────────────────────────────────────
document.getElementById('meta-line').textContent =
  `Generated ${R.meta.generated} · Initial $${R.meta.initial_balance} · ADX gate ${R.meta.adx_threshold}`;

const periods = R.periods;
const tickers_all = [...R.tickers, 'MULTI'];  // signal tickers + multi

let activePeriod = periods[0];
let activeToggles = {};  // period → Set of enabled tickers

// Build period tabs
const tabsEl = document.getElementById('period-tabs');
periods.forEach(p => {
  const b = document.createElement('button');
  b.className = 'ptab' + (p === activePeriod ? ' on' : '');
  b.dataset.p = p; b.textContent = p;
  b.onclick = () => {
    activePeriod = p;
    document.querySelectorAll('.ptab').forEach(x => x.classList.toggle('on', x.dataset.p === p));
    document.querySelectorAll('.period-section').forEach(s => {
      s.hidden = s.dataset.p !== p;
    });
    renderChart(p);
  };
  tabsEl.appendChild(b);
});

// Build period sections
const sectEl = document.getElementById('period-sections');
periods.forEach(p => {
  activeToggles[p] = new Set(['MULTI']);  // default: show MULTI only

  const sec = document.createElement('div');
  sec.className = 'period-section';
  sec.dataset.p = p;
  sec.hidden    = (p !== activePeriod);
  sec.innerHTML = buildPeriodHTML(p);
  sectEl.appendChild(sec);

  // Wire toggle buttons
  sec.querySelectorAll('.tgl').forEach(btn => {
    btn.onclick = () => {
      const t = btn.dataset.t, pn = btn.closest('.period-section').dataset.p;
      if (activeToggles[pn].has(t)) {
        activeToggles[pn].delete(t);
        btn.classList.remove('on');
        btn.style.background = '';
        btn.style.borderColor = '';
      } else {
        activeToggles[pn].add(t);
        btn.classList.add('on');
        const idx = tickers_all.indexOf(t);
        const col = t === 'MULTI' ? tok('--acc') : seriesColor(idx);
        btn.style.background   = col;
        btn.style.borderColor  = col;
      }
      renderChart(pn);
    };
  });

  // Wire trade log toggle
  sec.querySelectorAll('.tlog-hdr').forEach(hdr => {
    hdr.onclick = () => {
      const body  = hdr.nextElementSibling;
      const arrow = hdr.querySelector('.tlog-arrow');
      body.hidden = !body.hidden;
      arrow.classList.toggle('open', !body.hidden);
    };
    hdr.addEventListener('keydown', e => { if(e.key==='Enter'||e.key===' '){e.preventDefault();hdr.click();} });
  });

  // Set initial toggle state for MULTI button
  const multiBtn = sec.querySelector('.tgl[data-t="MULTI"]');
  if (multiBtn) {
    multiBtn.classList.add('on');
    multiBtn.style.background  = tok('--acc');
    multiBtn.style.borderColor = tok('--acc');
  }
});

renderChart(activePeriod);

// ── Period section HTML builder ───────────────────────────────────────────────
function buildPeriodHTML(p) {
  const pd = R.data[p];
  if (!pd) return `<p style="color:var(--mu);font-size:11px">No data for period ${p}</p>`;

  const rows = [...R.tickers, 'MULTI'].filter(t => pd[t]);

  // Summary table
  let tblRows = rows.map(t => {
    const d = pd[t];
    const retCls = d.ret >= 0 ? 'pos' : 'neg';
    const bh     = d.bh_ret >= 0 ? 'pos' : 'neg';
    const alCls  = d.alpha >= 0 ? 'pos' : 'neg';
    const wr     = d.win_rate != null ? d.win_rate.toFixed(1)+'%' : '—';
    const ar     = d.ann_ret != null ? d.ann_ret.toFixed(1)+'%' : '—';
    const isMult = t === 'MULTI';
    return `<tr${isMult?' class="bold"':''}>
      <td>${t}</td>
      <td>${d.start}</td><td>${d.end}</td>
      <td>$${d.end_bal.toFixed(2)}</td>
      <td class="${retCls}">${d.ret>=0?'+':''}${d.ret.toFixed(1)}%</td>
      <td class="${bh}">${d.bh_ret>=0?'+':''}${d.bh_ret.toFixed(1)}%</td>
      <td class="${alCls}">${d.alpha>=0?'+':''}${d.alpha.toFixed(1)}%</td>
      <td>${d.max_dd.toFixed(1)}%</td>
      <td>${d.n_trades}</td>
      <td>${wr}</td>
      <td>${ar}</td>
    </tr>`;
  }).join('');

  // Toggle buttons
  let toggles = rows.map((t, i) => {
    return `<button class="tgl" data-t="${t}" style="letter-spacing:.04em">${t}</button>`;
  }).join('');

  // Trade log (all tickers combined for this period)
  let tradeRows = '';
  rows.forEach(t => {
    const d = pd[t];
    if (!d || !d.trades.length) return;
    d.trades.forEach(tr => {
      const cls = tr[1] === 'Buy' ? 'pos' : 'neg';
      tradeRows += `<tr>
        <td>${tr[0]}</td><td class="${cls}">${tr[1]}</td><td>${tr[2]}</td>
        <td>$${tr[3].toFixed(2)}</td><td>${tr[4].toFixed(4)}</td><td>$${tr[5].toFixed(2)}</td>
      </tr>`;
    });
  });

  return `
    <div class="sec-title">${p} · Summary</div>
    <div class="tbw">
      <table>
        <thead><tr>
          <th style="text-align:left">Ticker</th><th>Start</th><th>End</th>
          <th>End $</th><th>Return</th><th>B&H Ret</th><th>Alpha</th>
          <th>Max DD</th><th>Trades</th><th>Win%</th><th>Ann. Ret</th>
        </tr></thead>
        <tbody>${tblRows}</tbody>
      </table>
    </div>

    <div class="sec-title">Equity Curves — click tickers to overlay</div>
    <div class="chart-controls">${toggles}</div>
    <div class="cw"><canvas id="chart-${p.replace(/[^a-z0-9]/gi,'_')}"></canvas></div>

    ${tradeRows ? `
    <div class="tlog-hdr" role="button" tabindex="0">
      <span class="tlog-arrow">&#9658;</span>
      <span class="tlog-lbl">Trade Log (${p})</span>
    </div>
    <div class="tlog-body" hidden>
      <div class="tbw">
        <table>
          <thead><tr><th style="text-align:left">Date</th><th>Action</th><th>Ticker</th>
            <th>Price</th><th>Shares</th><th>Value</th></tr></thead>
          <tbody>${tradeRows}</tbody>
        </table>
      </div>
    </div>` : ''}
  `;
}

// ── Canvas chart ──────────────────────────────────────────────────────────────
const ML=58,MT=8,MR=16,MB=26;
let hov = -1;
let currentChartId = null;
let currentSeries  = [];

function prep(id){
  const c=document.getElementById(id); if(!c) return null;
  const dpr=window.devicePixelRatio||1,W=c.offsetWidth,H=c.offsetHeight;
  c.width=W*dpr; c.height=H*dpr;
  const ctx=c.getContext('2d'); ctx.scale(dpr,dpr);
  return {ctx,W,H,p:{x:ML,y:MT,w:W-ML-MR,h:H-MT-MB}};
}
function px_(i,n,x0,w){ return x0+i/Math.max(n-1,1)*w }
function py_(v,lo,hi,y0,h){ return y0+h-(v-lo)/(hi-lo)*h }
function niceR(vals,pad=.04){
  const vs=vals.filter(v=>v!=null&&isFinite(v));
  if(!vs.length) return {lo:90,hi:110};
  let lo=Math.min(...vs),hi=Math.max(...vs);
  const r=(hi-lo)*pad||1; return {lo:lo-r,hi:hi+r};
}
function tks(lo,hi,n=5){
  const r=hi-lo,raw=r/n,mag=Math.pow(10,Math.floor(Math.log10(raw||1)));
  const nm=raw/mag,s=nm<1.5?1:nm<3?2:nm<7?5:10,step=s*mag;
  const t=[];
  for(let v=Math.ceil(lo/step)*step;v<=hi+step*.01;v=+(v+step).toFixed(12)) t.push(+v.toFixed(10));
  return t;
}
function hexA(hex,a){
  const h=hex.replace('#','');
  const [r,g,b]=[0,2,4].map(i=>parseInt(h.slice(i,i+2),16));
  return `rgba(${r},${g},${b},${a})`;
}
function fmtD(s){ return new Date(s+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric',year:'numeric'}) }

function renderChart(p) {
  const cid = 'chart-' + p.replace(/[^a-z0-9]/gi,'_');
  const cv  = document.getElementById(cid);
  if (!cv) return;
  currentChartId = cid;

  const pd = R.data[p];
  if (!pd) return;

  const enabled = activeToggles[p];
  const series  = [];

  // BH reference line (use QQQ BH if available)
  const bhTicker = pd['QQQ'] ? 'QQQ' : (R.tickers.find(t => pd[t]) || null);
  if (bhTicker && pd[bhTicker]) {
    const bh_eq = pd[bhTicker].equity;
    const startV = bh_eq[0][1];
    const bh_ratio = pd[bhTicker].bh_bal / pd[bhTicker].end_bal;
    // Reconstruct B&H curve: scale equity by (bh_end / strategy_end) ratio
    // Simpler: just use bh_end_bal and assume linear growth from start_bal
    // Even simpler: derive from the ticker's own equity scaled so final = bh_bal
    // Best: use actual QQQ close prices normalized to start_bal
    // We only have the equity arrays so do: bh_val[i] = start_bal * (bh_end / start_bal)^(i/(n-1))
    // That's an approximation. Let's store it separately.
    if (pd[bhTicker].bh_equity) {
      series.push({ label: 'B&H ('+bhTicker+')', eq: pd[bhTicker].bh_equity, color: bhColor(), dash: [4,4], w: 1.5 });
    }
  }

  // Enabled tickers
  [...R.tickers, 'MULTI'].forEach((t, idx) => {
    if (!enabled.has(t) || !pd[t]) return;
    const col = t === 'MULTI' ? tok('--acc') : seriesColor(idx);
    series.push({ label: t, eq: pd[t].equity, color: col, dash: [], w: t === 'MULTI' ? 2.5 : 1.5 });
  });

  currentSeries = series;

  const g = prep(cid);
  if (!g) return;
  const {ctx, p: pl} = g;
  const c = { sf: tok('--sf'), gr: tok('--gr'), mu: tok('--mu'), cr: isDark()?'rgba(180,215,255,.28)':'rgba(20,60,120,.20)' };

  // All values for range
  const all_vals = series.flatMap(s => s.eq.map(e => e[1]));
  const {lo, hi} = niceR(all_vals);

  // Grid
  ctx.save(); ctx.strokeStyle=c.gr; ctx.lineWidth=1;
  ctx.font=`10px ${MONO}`; ctx.textAlign='right'; ctx.fillStyle=c.mu;
  for (const t of tks(lo,hi,5)){
    const y=py_(t,lo,hi,pl.y,pl.h);
    ctx.beginPath(); ctx.moveTo(pl.x,y); ctx.lineTo(pl.x+pl.w,y); ctx.stroke();
    ctx.fillText('$'+t.toFixed(2), pl.x-5, y+3.5);
  }
  ctx.restore();

  // X axis (year markers from first series)
  if (series.length) {
    const eq = series[series.length-1].eq;
    const n  = eq.length;
    ctx.save(); ctx.strokeStyle=c.mu; ctx.lineWidth=1;
    ctx.font=`10px ${MONO}`; ctx.textAlign='center'; ctx.fillStyle=c.mu;
    const ay=pl.y+pl.h;
    ctx.beginPath(); ctx.moveTo(pl.x,ay); ctx.lineTo(pl.x+pl.w,ay); ctx.stroke();
    const seen=new Set();
    for(let i=0;i<n;i++){
      const dt=eq[i][0],yr=dt.slice(0,4),mm=dt.slice(5,7),dd=+dt.slice(8);
      if(mm==='01'&&dd<=10&&!seen.has(yr)){
        seen.add(yr); const x=px_(i,n,pl.x,pl.w);
        ctx.fillText(yr,x,ay+16); ctx.beginPath(); ctx.moveTo(x,ay); ctx.lineTo(x,ay+3); ctx.stroke();
      }
    }
    ctx.restore();
  }

  // Lines
  series.forEach(s => {
    const eq=s.eq, n=eq.length;
    ctx.save(); ctx.strokeStyle=s.color; ctx.lineWidth=s.w;
    ctx.lineJoin='round'; ctx.lineCap='round';
    if(s.dash.length) ctx.setLineDash(s.dash);
    ctx.beginPath(); let on=false;
    for(let i=0;i<n;i++){
      const v=eq[i][1]; if(!isFinite(v)){on=false;continue;}
      const x=px_(i,n,pl.x,pl.w),y=py_(v,lo,hi,pl.y,pl.h);
      if(!on){ctx.moveTo(x,y);on=true;}else ctx.lineTo(x,y);
    }
    ctx.stroke(); ctx.restore();
  });

  // Crosshair
  if (hov >= 0 && series.length) {
    const n = series[series.length-1].eq.length;
    const i = Math.min(hov, n-1);
    const x = px_(i, n, pl.x, pl.w);
    ctx.save(); ctx.strokeStyle=c.cr; ctx.lineWidth=1; ctx.globalAlpha=.55;
    ctx.setLineDash([4,3]);
    ctx.beginPath(); ctx.moveTo(x,pl.y); ctx.lineTo(x,pl.y+pl.h); ctx.stroke();
    ctx.restore();
  }

  // Legend (top-right inside chart)
  if (series.length) {
    ctx.save(); ctx.font=`10px ${MONO}`; ctx.textAlign='left';
    let ly = pl.y + 10;
    series.forEach(s => {
      ctx.strokeStyle=s.color; ctx.lineWidth=s.w;
      if(s.dash.length) ctx.setLineDash(s.dash); else ctx.setLineDash([]);
      ctx.beginPath(); ctx.moveTo(pl.x+pl.w-90,ly); ctx.lineTo(pl.x+pl.w-72,ly); ctx.stroke();
      ctx.setLineDash([]);
      ctx.fillStyle=c.mu; ctx.fillText(s.label, pl.x+pl.w-70, ly+3.5);
      ly += 16;
    });
    ctx.restore();
  }
}

// ── Hover / Tooltip ───────────────────────────────────────────────────────────
function getCanvas(){
  if(!currentChartId) return null;
  return document.getElementById(currentChartId);
}
function getPlot(){
  const c=getCanvas(); if(!c) return null;
  return {x:ML,y:MT,w:c.offsetWidth-ML-MR,h:c.offsetHeight-MT-MB};
}

function onMove(e){
  const c=getCanvas(); if(!c) return;
  const r=c.getBoundingClientRect(), pl=getPlot();
  const mx=e.clientX-r.left;
  if(mx<pl.x||mx>pl.x+pl.w){if(hov!==-1){hov=-1;renderChart(activePeriod);hideTT();}return;}
  const n=currentSeries.length?currentSeries[currentSeries.length-1].eq.length:0;
  if(!n) return;
  const ni=Math.round((mx-pl.x)/pl.w*(n-1));
  if(ni!==hov){hov=ni;renderChart(activePeriod);}
  showTT(e.clientX,e.clientY,ni);
}
function onLeave(){hov=-1;renderChart(activePeriod);hideTT();}
function hideTT(){document.getElementById('tt').style.display='none'}
function showTT(cx,cy,idx){
  const tt=document.getElementById('tt');
  if(!currentSeries.length||idx<0){tt.style.display='none';return;}
  const first=currentSeries[currentSeries.length-1];
  const eq=first.eq;
  if(idx>=eq.length){tt.style.display='none';return;}
  const d=eq[idx][0];
  let rows='<div class="ttd">'+fmtD(d)+'</div><hr class="ttdiv">';
  currentSeries.forEach(s=>{
    const i=Math.min(idx,s.eq.length-1), v=s.eq[i][1];
    const cls=v>=100?'pos':'neg';
    rows+=`<div class="ttr"><span class="ttl" style="color:${s.color}">${s.label}</span><span class="ttv ${cls}">$${v.toFixed(2)}</span></div>`;
  });
  tt.innerHTML=rows;
  tt.style.display='block';
  const tw=tt.offsetWidth,th=tt.offsetHeight;
  let tx=cx+14,ty=cy-th/2;
  if(tx+tw>window.innerWidth-8)tx=cx-tw-14;
  if(ty<8)ty=8; if(ty+th>window.innerHeight-8)ty=window.innerHeight-th-8;
  tt.style.left=tx+'px'; tt.style.top=ty+'px';
}

// Attach mouse events to the container and delegate
document.getElementById('period-sections').addEventListener('mousemove', e=>{
  if(e.target.tagName==='CANVAS') onMove(e);
});
document.getElementById('period-sections').addEventListener('mouseleave', e=>{
  if(e.target.tagName==='CANVAS') onLeave();
});

// ── Theme / resize ────────────────────────────────────────────────────────────
window.matchMedia('(prefers-color-scheme:dark)').addEventListener('change',()=>renderChart(activePeriod));
new MutationObserver(()=>renderChart(activePeriod)).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
let rt; window.addEventListener('resize',()=>{clearTimeout(rt);rt=setTimeout(()=>renderChart(activePeriod),80);});
</script>
"""


def _build_bh_equity(ticker_df: pd.DataFrame, period_data: dict, start_bal: float) -> list:
    """
    Reconstruct a buy-and-hold equity curve from the ticker's close prices
    in the period (normalized to start_bal).
    """
    eq = period_data.get("equity", [])
    if not eq:
        return []
    bh_end = period_data.get("bh_bal", start_bal)
    n = len(eq)
    # Linear interpolation: this approximates the actual BH curve well for display
    # Better: load the close prices again. But we already have the strategy equity
    # We can infer daily BH from the "bh_bal" and the strategy's equity dates.
    # Without original close data here, approximate via geometric growth.
    start_val = start_bal
    end_val   = bh_end
    result = []
    for i, (d, _) in enumerate(eq):
        frac = i / max(n - 1, 1)
        # Geometric interpolation
        if start_val > 0 and end_val > 0:
            val = start_val * (end_val / start_val) ** frac
        else:
            val = start_val
        result.append([d, round(val, 4)])
    return result


def generate_html_report(all_results: list, tickers: list, out_path: Path,
                         initial_balance: float = INITIAL_BALANCE):
    # Build the JSON data structure
    period_labels = []
    data: dict = {}

    for r in all_results:
        if r.period not in data:
            data[r.period] = {}
            period_labels.append(r.period)
        d = _r2d(r)
        # Attach BH equity curve (approximated)
        d["bh_equity"] = _build_bh_equity(None, d, initial_balance)
        data[r.period][r.ticker] = d

    # Deduplicate period_labels while preserving order
    seen = set()
    period_labels_u = [p for p in period_labels if not (p in seen or seen.add(p))]

    payload = {
        "meta": {
            "generated":     datetime.now().strftime("%Y-%m-%d %H:%M"),
            "initial_balance": initial_balance,
            "adx_threshold": ADX_THRESHOLD,
            "sma_lookback":  SMA_LOOKBACK,
        },
        "periods": period_labels_u,
        "tickers": tickers,
        "data":    data,
    }

    html = REPORT_TMPL.replace("@@REPORT_DATA@@", json.dumps(payload, separators=(",", ":")))
    out_path.write_text(html, encoding="utf-8")
    logger.info(f"HTML report written → {out_path} ({len(html)//1024} KB)")


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # Discover tickers from indicator CSVs
    csv_files = sorted(IND_DIR.glob("*_indicators.csv"))
    if not csv_files:
        logger.error(f"No indicator CSVs found in {IND_DIR}. Run gen_dashboard.py first.")
        sys.exit(1)

    tickers = [f.name.replace("_indicators.csv", "") for f in csv_files]
    logger.info(f"Tickers: {tickers}")

    # Load all indicator data and compute signals
    logger.info("Loading indicator CSVs and computing signals …")
    ticker_dfs = {}
    for t in tickers:
        df = load_ticker(t)
        if df is not None:
            ticker_dfs[t] = df
            logger.info(f"  {t}: {len(df)} rows  "
                        f"({df.iloc[0]['Date']} → {df.iloc[-1]['Date']})")

    # Run all test periods
    all_results = []
    for label, start, end in TEST_PERIODS:
        logger.info(f"─── Period: {label} ({start or 'all'} → {end or 'latest'}) ───")

        # Single-ticker backtests
        for t in tickers:
            if t not in ticker_dfs:
                continue
            r = run_single(t, ticker_dfs[t], label, start, end)
            if r is None:
                logger.debug(f"  {t}: no data in period, skipped")
                continue
            all_results.append(r)
            logger.info(f"  {t}: ${r.end_bal:.2f}  ret={r.return_pct:+.1f}%  "
                        f"bh={r.bh_return_pct:+.1f}%  trades={r.n_trades}")

        # Multi-ticker backtest
        r_multi = run_multi(ticker_dfs, label, start, end)
        if r_multi:
            all_results.append(r_multi)
            logger.info(f"  MULTI: ${r_multi.end_bal:.2f}  ret={r_multi.return_pct:+.1f}%  "
                        f"trades={r_multi.n_trades}")

    # Write outputs
    write_csv(all_results, OUT_DIR / "summary.csv")
    generate_html_report(all_results, tickers, OUT_DIR / "report.html", INITIAL_BALANCE)
    logger.info(f"\nDone. Results in {OUT_DIR}/")
    logger.info(f"  Open: {OUT_DIR}/report.html")


if __name__ == "__main__":
    main()
