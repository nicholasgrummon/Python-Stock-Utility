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
import Evaluation.indicator_utils as ind_utils
import Evaluation.gen_dashboard as gen_dash
import Notifications.discord_utils as discord_utils
import Notifications.discord_bot as discord_bot

# GLOBALS
BASE_DIR = Path(__file__).parent.absolute()
NYC = pytz.timezone("America/New_York")
NYSE = mcal.get_calendar("NYSE")

DEFAULT_PERIOD = 365

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

NOTIFIER = discord_utils.DiscordNotifier(BASE_DIR)
if NOTIFIER.enabled:
    discord_bot.run_in_background(BASE_DIR, NOTIFIER.token, NOTIFIER.channel_id)


def load_holdings(base_dir):
    try:
        holdings_df = pd.read_csv(base_dir / "Positions/Holdings.csv")
        return set(holdings_df["Ticker"])
    except (pd.errors.EmptyDataError, KeyError):
        return set()


# Execute with: $ nohup python main.py &
# Kill with: $ kill $(pgrep -f main.py)
# Or install Deploy/psu.service as a systemd user service for managed restarts
def main():
    last_tiers = {}

    while True:
        wait_time = utils.seconds_until_market_open(NYSE)
        if wait_time > 0:
            logger.info(f"Market closed: sleeping {wait_time}s until next session")
            time.sleep(1+wait_time) # wait for one second for buffer

        try:
            watchlist_df = pd.read_csv(BASE_DIR / "Positions/Watchlist.csv")
            holdings = load_holdings(BASE_DIR)
            tickers = watchlist_df["Ticker"]

            hist.touch_savefile(BASE_DIR, watchlist_df)
            hist.update_savefiles(BASE_DIR, watchlist_df, default_period=DEFAULT_PERIOD)
            if ind_utils.update_indicator_csvs(BASE_DIR, watchlist_df):
                gen_dash.generate_dashboard(BASE_DIR)

            discord_utils.check_rating_alerts(BASE_DIR, tickers, NOTIFIER, last_tiers, holdings)
            discord_utils.maybe_send_weekly_summary(BASE_DIR, tickers, NOTIFIER)

        except Exception:
            logger.exception("Error in main loop")

        time.sleep(60 - datetime.now().second)


if __name__=='__main__':
    main()
