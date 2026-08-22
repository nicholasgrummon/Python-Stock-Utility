import sys
import logging
import pandas as pd
from pathlib import Path
from dateutil import parser as date_parser

sys.path.insert(0, str(Path(__file__).parent.parent))
import utils
import Evaluation.eval_utils as eval_utils

logger = logging.getLogger(__name__)

INDICATOR_HEADER = [
    "Datetime", "Close", "High", "Low",
    "SMA20", "SMA50", "RSI14",
    "BB_Lower", "BB_Middle", "BB_Upper",
    "ADX14",
]
# Rolling window size for incremental computation. ADX(14) needs 2*14+14=42 bars
# to produce a value; 80 gives comfortable convergence without loading full history.
INDICATOR_LOOKBACK = 80


def _get_last_indicator_dt(ind_path):
    last = utils.get_lastline(str(ind_path))
    if last == -1 or not last or last[0] in ("Datetime", ""):
        return None
    try:
        return date_parser.parse(last[0])
    except Exception:
        return None


def _compute_row(close, high, low):
    """Compute all indicator values for the last bar in the given window lists."""
    sma20 = eval_utils.moving_avg(close, 20)[-1] if len(close) >= 20 else None
    sma50 = eval_utils.moving_avg(close, 50)[-1] if len(close) >= 50 else None

    rsi_list = eval_utils.relative_strength_index(close)
    rsi14 = rsi_list[-1] if rsi_list else None

    bb_list = eval_utils.bollinger_bands(close)
    bbl, bbm, bbu = bb_list[-1] if bb_list else (None, None, None)

    adx_list = eval_utils.average_directional_index(high, low, close)
    adx14 = adx_list[-1] if adx_list else None

    return sma20, sma50, rsi14, bbl, bbm, bbu, adx14


def _backlog_full(hist_df, ind_path):
    """
    Compute indicators from scratch over the full 1d history series.
    Called once when the indicator CSV does not exist yet for a ticker.
    """
    n = len(hist_df)
    close = hist_df["Close"].tolist()
    high  = hist_df["High"].tolist()
    low   = hist_df["Low"].tolist()
    dt_strs = hist_df["Datetime"].tolist()

    # Compute series with proper alignment; prefix with None for warm-up period
    # SMA20/BB20: first value covers close[0..19] → prefix 19 Nones
    sma20_arr = [None] * 19 + eval_utils.moving_avg(close, 20)
    sma50_arr = [None] * 49 + eval_utils.moving_avg(close, 50)
    # RSI14: first value uses close[0..14] → prefix 14 Nones
    rsi_arr   = [None] * 14 + eval_utils.relative_strength_index(close)
    # BB20: aligned with SMA20
    bb_raw    = eval_utils.bollinger_bands(close)
    bb_arr    = [None] * 19 + list(bb_raw)
    # ADX14: 2*14 + 14 − 1 = 41 → actually 28 Nones (traced through function)
    adx_arr   = [None] * 28 + eval_utils.average_directional_index(high, low, close)

    def _pad(arr):
        if len(arr) < n:
            arr = arr + [None] * (n - len(arr))
        return arr[:n]

    sma20_arr = _pad(sma20_arr)
    sma50_arr = _pad(sma50_arr)
    rsi_arr   = _pad(rsi_arr)
    bb_arr    = _pad(bb_arr)
    adx_arr   = _pad(adx_arr)

    rows = []
    for i in range(n):
        bb = bb_arr[i]
        rows.append([
            dt_strs[i],
            close[i], high[i], low[i],
            sma20_arr[i], sma50_arr[i], rsi_arr[i],
            bb[0] if bb else None, bb[1] if bb else None, bb[2] if bb else None,
            adx_arr[i],
        ])

    ind_path.parent.mkdir(parents=True, exist_ok=True)
    pd.DataFrame(rows, columns=INDICATOR_HEADER).to_csv(str(ind_path), index=False)
    logger.info(f"{ind_path.name}: created with {n} rows (full backlog)")


def _update_ticker_indicators(ticker, base_dir):
    """
    Appends indicator rows for any 1d history timestamps not yet in the indicator CSV.
    Returns True if any rows were written.
    """
    base_dir  = Path(base_dir)
    ind_path  = base_dir / "Evaluation" / "Indicators" / f"{ticker}_indicators.csv"
    hist_path = base_dir / "Historical" / "1d_history" / f"{ticker}.csv"

    if not hist_path.exists():
        return False

    last_ind_dt = _get_last_indicator_dt(ind_path)

    # Load 1d history (only performed when there may be new rows)
    hist_df = pd.read_csv(str(hist_path))
    if hist_df.empty or "Close" not in hist_df.columns:
        return False

    hist_df.drop_duplicates(subset="Datetime", keep="last", inplace=True)
    hist_df.reset_index(drop=True, inplace=True)

    # Preserve original datetime strings for writing back
    dt_strs = hist_df["Datetime"].tolist()

    # Parse datetimes for comparison (normalize to UTC)
    hist_df["_dt"] = pd.to_datetime(hist_df["Datetime"], utc=True)

    # No indicator file yet → full backlog
    if not ind_path.exists() or last_ind_dt is None:
        _backlog_full(hist_df, ind_path)
        return True

    # Incremental: find rows newer than last indicator entry
    last_ts = (
        pd.Timestamp(last_ind_dt).tz_convert("UTC")
        if last_ind_dt.tzinfo else
        pd.Timestamp(last_ind_dt, tz="UTC")
    )
    new_mask = hist_df["_dt"] > last_ts
    if not new_mask.any():
        return False

    close_all = hist_df["Close"].tolist()
    high_all  = hist_df["High"].tolist()
    low_all   = hist_df["Low"].tolist()

    rows_to_write = []
    for i in hist_df.index[new_mask]:
        end   = i + 1
        start = max(0, end - INDICATOR_LOOKBACK)
        sma20, sma50, rsi14, bbl, bbm, bbu, adx14 = _compute_row(
            close_all[start:end], high_all[start:end], low_all[start:end]
        )
        rows_to_write.append([
            dt_strs[i],
            close_all[i], high_all[i], low_all[i],
            sma20, sma50, rsi14, bbl, bbm, bbu, adx14,
        ])

    pd.DataFrame(rows_to_write, columns=INDICATOR_HEADER).to_csv(
        str(ind_path), mode='a', header=False, index=False
    )
    logger.info(f"{ticker}: appended {len(rows_to_write)} indicator row(s)")
    return True


def update_indicator_csvs(base_dir, watchlist_df):
    """
    Update Evaluation/Indicators/{ticker}_indicators.csv for each watchlist ticker.
    Returns True if any file was updated (caller can decide to regenerate dashboard).
    """
    updated = False
    for ticker in watchlist_df["Ticker"]:
        try:
            if _update_ticker_indicators(ticker, base_dir):
                updated = True
        except Exception:
            logger.exception(f"Failed to update indicators for {ticker}")
    return updated
