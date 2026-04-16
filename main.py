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
    

# Execute with: $ nohup python main.py &
# Kill with: $ kill $(pgrep python)
def main():
    while True:
        wait_time = utils.seconds_until_market_open(NYSE)
        if wait_time > 0:
            print(f"Market Closed: sleeping {wait_time} until next scheduled trading hours")
            time.sleep(1+wait_time) # wait for one second for buffer
        
        if True:
            watchlist_df = pd.read_csv(f"{BASE_DIR}/Positions/Watchlist.csv")
            hist.touch_savefile(BASE_DIR, watchlist_df)
            hist.update_savefiles(BASE_DIR, watchlist_df, printout=True)
            time.sleep(60 - datetime.now().second)


if __name__=='__main__':
    main()