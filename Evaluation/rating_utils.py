"""
Buy/sell rating (0-10) for each ticker, computed from the same indicator CSVs
that back Evaluation/indicator_dashboard.html.

Mirrors the `rating()`/`targets()` functions in Evaluation/gen_dashboard.py's
dashboard JS — keep the two in sync if either formula changes.
"""
import logging
from pathlib import Path
import pandas as pd

logger = logging.getLogger(__name__)

RSI_WEIGHT = 0.4
BB_WEIGHT  = 0.3
SMA_WEIGHT = 0.3

ATR_PERIOD = 14

# Exit spread for BUY-tier ratings (rating >= 6): upside is ATR * a multiplier
# that scales UP directly with confidence — from CONF_MULT_MIN at a bare BUY
# (rating 6) to CONF_MULT_MAX at a perfect 10 — not a fixed base multiplier
# scaled down by a 0-1 fraction, which buried how big the multiplier actually
# gets and made a "good" signal look barely different from a "bad" one.
# Downside is always half the upside ("risk half of what you want to gain")
# rather than its own independent ATR multiple — pinning it to ATR directly
# let low-confidence signals on volatile tickers risk *more* than they
# targeted to gain, since only the upside side scaled with confidence.
# 1.0 -> 2.8 puts a typically-volatile stock (ATR ~3%) at ~2.0x (~6% upside)
# around rating 8-8.5, and further out (~2.8x, ~8.4%) at a perfect 10.
CONF_MULT_MIN, CONF_MULT_MAX = 1.0, 2.8
RISK_REWARD_RATIO = 2.0
MIN_UPSIDE_PCT, MAX_UPSIDE_PCT = 1.0, 12.0
MIN_DOWNSIDE_PCT, MAX_DOWNSIDE_PCT = 0.6, 6.0


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


def atr_pct(df, period=ATR_PERIOD):
    """
    Average True Range as a % of the latest close — the volatility measure used
    to scale exit targets. Computed on-demand from the High/Low/Close columns
    already stored in the indicator CSV, no separate ATR column needed.
    """
    df = df.tail(period * 3)
    high, low, close = df["High"], df["Low"], df["Close"]
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    tr = tr.dropna()
    if len(tr) < period:
        return None

    last_close = _last_valid(close)
    atr = tr.tail(period).mean()
    if last_close is None or not last_close or pd.isna(atr):
        return None

    return float(atr / last_close * 100)


def compute_targets(rating, atr):
    """
    Upside/downside exit spread (in %) for a BUY-tier rating.
    Returns (upside_pct, downside_pct), or (None, None) below the BUY threshold
    or when ATR can't be computed (not enough history yet).
    """
    if rating < 6 or atr is None:
        return None, None

    confidence = _clamp((rating - 6) / 4, 0.0, 1.0)
    multiplier = CONF_MULT_MIN + (CONF_MULT_MAX - CONF_MULT_MIN) * confidence
    upside = _clamp(atr * multiplier, MIN_UPSIDE_PCT, MAX_UPSIDE_PCT)
    downside = _clamp(upside / RISK_REWARD_RATIO, MIN_DOWNSIDE_PCT, MAX_DOWNSIDE_PCT)

    return round(upside, 1), round(downside, 1)


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

    atr = atr_pct(df)
    upside_pct, downside_pct = compute_targets(value, atr)
    target_price = close * (1 + upside_pct / 100) if upside_pct is not None else None
    stop_price = close * (1 - downside_pct / 100) if downside_pct is not None else None

    return dict(
        ticker=ticker, close=close, rating=value, tier=tier(value),
        rsi=rsi, sma20=sma20, sma50=sma50, adx=adx, pct_b=pct_b,
        atr_pct=atr, upside_pct=upside_pct, downside_pct=downside_pct,
        target_price=target_price, stop_price=stop_price,
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
