import logging
import logging.handlers
from pathlib import Path

from datetime import datetime
import pytz
import time

import pandas as pd
import pandas_market_calendars as mcal

import utils
import Historical.history_utils as hist
import Evaluation.eval_utils as eval_utils

# GLOBALS
BASE_DIR = Path(__file__).parent.absolute()
NYC = pytz.timezone("America/New_York")
NYSE = mcal.get_calendar("NYSE")

DEFAULT_PERIOD = 365
SIGNAL_INTERVAL = "1d"
SIGNAL_LOOKBACK = 100 # bars of warm-up needed for SMA(50)/ADX(14)

LOG_DIR = BASE_DIR / "Logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(LOG_DIR / "main.log", maxBytes=1_000_000, backupCount=5),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("psu")

SENDER = utils.SMS_Server("smtp.gmail.com", 587, BASE_DIR)


def load_holdings(base_dir):
    try:
        holdings_df = pd.read_csv(base_dir / "Positions/Holdings.csv")
        return set(holdings_df["Ticker"])
    except (pd.errors.EmptyDataError, KeyError):
        return set()


def check_signals(watchlist_df, holdings, last_signals):
    '''
    Evaluate the combined Buy/Sell/Hold signal for each watchlisted ticker and SMS the
    distro list when a signal changes. Sell alerts are only sent for held positions.
    '''
    for ticker in watchlist_df["Ticker"]:
        try:
            history_df = utils.get_last_chunk_df(SIGNAL_INTERVAL, ticker, SIGNAL_LOOKBACK, BASE_DIR)
            signal = eval_utils.evaluate_signal(history_df)
        except Exception:
            logger.exception(f"Failed to evaluate signal for {ticker}")
            continue

        prev_signal = last_signals.get(ticker)
        last_signals[ticker] = signal

        if signal == prev_signal:
            continue

        logger.info(f"{ticker}: signal changed {prev_signal} -> {signal}")

        if signal == "Buy":
            SENDER.send_distro(f"{ticker}: BUY signal")

        elif signal == "Sell" and ticker in holdings:
            SENDER.send_distro(f"{ticker}: SELL signal")


# Execute with: $ nohup python main.py &
# Kill with: $ kill $(pgrep -f main.py)
# Or install Deploy/psu.service as a systemd user service for managed restarts
def main():
    last_signals = {}

    while True:
        wait_time = utils.seconds_until_market_open(NYSE)
        if wait_time > 0:
            logger.info(f"Market closed: sleeping {wait_time}s until next session")
            time.sleep(1+wait_time) # wait for one second for buffer

        try:
            watchlist_df = pd.read_csv(BASE_DIR / "Positions/Watchlist.csv")
            holdings = load_holdings(BASE_DIR)

            hist.touch_savefile(BASE_DIR, watchlist_df)
            hist.update_savefiles(BASE_DIR, watchlist_df, default_period=DEFAULT_PERIOD)
            check_signals(watchlist_df, holdings, last_signals)

        except Exception:
            logger.exception("Error in main loop")

        time.sleep(60 - datetime.now().second)


if __name__=='__main__':
    main()
