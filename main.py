from datetime import datetime, timedelta
import pytz
import time

import pandas as pd
import pandas_market_calendars as mcal

import utils
import Historical.history_utils as hist
import Evaluation.eval_utils as eval


# Execute with: $ nohup python main.py &
# Kill with: $ kill $(pgrep python)
def main():
    # define installation directory
    dirFilepath = "/home/ncg/Documents/Python_Stock_Utility"

    # Get market calendar for NYSE
    nyc = pytz.timezone("America/New_York")
    nyse = mcal.get_calendar("NYSE")

    # get list of stocks to watch
    watchlist_df = pd.read_csv(f"{dirFilepath}/Positions/Watchlist.csv")

    # initialize lists
    for ticker in watchlist_df["Ticker"]:
        for interval in ["1m", "1h", "1d"]:
            hist.update_savefiles(dirFilepath, interval, ticker, printout=True)

    # create SMS server
    sender = utils.SMS_Server("smtp.gmail.com", 587, dirFilepath)
    
    # main loop
    # while True:
    #     # search for next open market day
    #     today = datetime.now(nyc).date()
    #     schedule = pd.DataFrame()
    #     i = 1
    #     while schedule.empty:
    #         schedule = nyse.schedule(today, today+timedelta(days=i))
    #         i += 1
        
    #     try:
    #         # TODO: report time that program missed market open by
    #         # update savefiles once per minute during trading hours
    #         while nyse.is_open_now(schedule):
    #             # update savefiles for watchlist
    #             for ticker in watchlist_df["Ticker"]:
    #                 for interval in ["1m", "1h", "1d"]:
    #                     hist.update_savefiles(dirFilepath, interval, ticker, printout=True)

    #                     # Evaluate market indicators
    #                     chunk = utils.get_last_chunk(interval, ticker, 50, dirFilepath)
                        
    #                     # eval.update_indicators(interval, ticker, chunk)
    #                     signal = eval.buy_sell_indicator(chunk)
                        
    #                     # Send buy/signal
    #                     if signal:
    #                         sender.send_distro(f"{signal} signal acquired for {ticker} on {interval} data")

    #             # pause until next minute
    #             time.sleep(60 - datetime.now().second)
        
    #     except Exception:
    #         # today has trading hours but now() is before market open
    #         pass

    #     finally:
    #         # wait until the next scheduled trading hours
    #         for open_time in schedule["market_open"]:
    #             if open_time > datetime.now(nyc):
    #                 print(f"Market Closed: sleeping {open_time - datetime.now(nyc)} until next scheduled trading hours")
    #                 time.sleep((open_time - datetime.now(nyc)).total_seconds())

if __name__=='__main__':
    main()