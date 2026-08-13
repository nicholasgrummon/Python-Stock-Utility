"""
Buy/sell rating (0-10) for each ticker, computed from the same indicator CSVs
that back Evaluation/indicator_dashboard.html.

Mirrors the `rating()` function in Evaluation/gen_dashboard.py's dashboard JS —
keep the two in sync if the formula changes.
"""
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

RSI_WEIGHT = 0.4
BB_WEIGHT  = 0.3
SMA_WEIGHT = 0.3


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _last_valid(series):
    s = series.dropna()
    return float(s.iloc[-1]) if not s.empty else None


def compute_rating(close, sma20, sma50, rsi, bbl, bbu, adx):
    """
    Blends RSI, Bollinger %B, and SMA20/50 spread into a 0 (Sell) - 10 (Strong Buy)
    mean-reversion rating: oversold RSI, price near the lower Bollinger band, and
    SMA20 pulled below SMA50 all read as "buy the dip". ADX dampens the read toward
    neutral when a strong prevailing trend makes fading it riskier.
    """
    rsi_s = _clamp(10 - rsi / 10, 0, 10) if rsi is not None else 5.0

    pct_b = (
        (close - bbl) / (bbu - bbl)
        if (bbl is not None and bbu is not None and bbu > bbl) else 0.5
    )
    bb_s = _clamp(10 * (1 - pct_b), 0, 10)

    spread = (sma20 - sma50) / sma50 * 100 if (sma20 is not None and sma50) else 0.0
    sma_s = _clamp(5 - spread * 1.5, 0, 10)

    raw = rsi_s * RSI_WEIGHT + bb_s * BB_WEIGHT + sma_s * SMA_WEIGHT
    conv = _clamp(1 - (adx - 20) / 40, 0.4, 1) if adx is not None else 1.0
    val = _clamp(5 + (raw - 5) * conv, 0, 10)

    return round(val * 2) / 2


def tier(value):
    """Maps a 0-10 rating to a discrete signal tier."""
    if value >= 7.5:
        return "STRONG BUY"
    if value >= 6:
        return "BUY"
    if value > 4:
        return "HOLD"
    if value >= 2.5:
        return "SELL"
    return "STRONG SELL"


def rating_for_ticker(ticker, base_dir):
    """Latest rating + inputs for `ticker`, or None if no indicator data exists yet."""
    ind_path = Path(base_dir) / "Evaluation" / "Indicators" / f"{ticker}_indicators.csv"
    if not ind_path.exists():
        return None

    df = pd.read_csv(ind_path)
    if df.empty:
        return None

    close = _last_valid(df["Close"])
    if close is None:
        return None

    sma20 = _last_valid(df["SMA20"])
    sma50 = _last_valid(df["SMA50"])
    rsi   = _last_valid(df["RSI14"])
    bbl   = _last_valid(df["BB_Lower"])
    bbu   = _last_valid(df["BB_Upper"])
    adx   = _last_valid(df["ADX14"])

    value = compute_rating(close, sma20, sma50, rsi, bbl, bbu, adx)
    pct_b = (close - bbl) / (bbu - bbl) if (bbl is not None and bbu is not None and bbu > bbl) else None

    return dict(
        ticker=ticker, close=close, rating=value, tier=tier(value),
        rsi=rsi, sma20=sma20, sma50=sma50, adx=adx, pct_b=pct_b,
    )


def all_ratings(tickers, base_dir):
    """Ratings for every ticker with indicator data, sorted best (Strong Buy) first."""
    rows = []
    for t in tickers:
        try:
            r = rating_for_ticker(t, base_dir)
        except Exception:
            logger.exception(f"Failed to compute rating for {t}")
            continue
        if r is not None:
            rows.append(r)
    rows.sort(key=lambda r: r["rating"], reverse=True)
    return rows
