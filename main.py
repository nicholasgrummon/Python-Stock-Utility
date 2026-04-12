from pathlib import Path

from datetime import datetime, timedelta
import pytz
import time

import pandas as pd
import pandas_market_calendars as mcal

import utils
import Historical.history_utils as hist
import Evaluation.eval_utils as eval

# GLOBALS
BASE_DIR = Path(__file__).parent.absolute()
NYC = pytz.timezone("America/New_York")
NYSE = mcal.get_calendar("NYSE")

DEFAULT_PERIOD = 365

SENDER = utils.SMS_Server("smtp.gmail.com", 587, BASE_DIR)

def seconds_until_market_open(wait_less=0.99):
    # get trading schedule today
    now_dt = datetime.now(NYC)
    start_day = now_dt.date()
    end_day = now_dt.date()
    schedule = NYSE.schedule(start_day, end_day)

    # expand list if currently after trading hours or none exist today
    while schedule.empty or now_dt > schedule["market_close"].iloc[-1]:
        end_day += timedelta(days=1)
        schedule = NYSE.schedule(start_day, end_day)

    # wait until first market_open after now
    for market_open in schedule["market_open"]:
        if now_dt < market_open:
            return round(max(10, wait_less*(market_open - now_dt).total_seconds()))
        
        else:
            return 0
    

# Execute with: $ nohup python main.py &
# Kill with: $ kill $(pgrep python)
def main():
    while True:
        wait_time = seconds_until_market_open()
        if wait_time > 0:
            print(f"Market Closed: sleeping {wait_time} until next scheduled trading hours")
            time.sleep(wait_time)
        
        else:
            watchlist_df = pd.read_csv(f"{BASE_DIR}/Positions/Watchlist.csv")
            hist.touch_savefile(BASE_DIR, watchlist_df)
            hist.update_savefiles(BASE_DIR, watchlist_df, printout=True)
            time.sleep(60 - datetime.now().second)


if __name__=='__main__':
    main()