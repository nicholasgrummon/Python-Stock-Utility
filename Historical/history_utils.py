import sys
sys.path.append("/home/ncg/Documents/pythonStockUtility/")
import utils

# import data handling libraries
import pandas as pd
import yfinance as yf

# import time handling libraries
from datetime import datetime, timedelta
from dateutil import parser as date_parser
import pytz
nyc = pytz.timezone("America/New_York")

def update_savefiles(dirFilepath, ticker, printout=False):
    '''
    Collect historical data for specified stock.
    - Write new savefile with max history if no data saved
    - Append newer data if outdated data exists

    Pass dirFilepath to allow project to be installed s
    '''
    # download yfinance object for specified ticker
    stock = yf.Ticker(ticker)

    # download historical data for selected intervals
    for interval in ["1m","1h","1d"]:
        # construct savefile location
        savefolder_path = utils.mkdir(f"{dirFilepath}/Historical/{interval}_history")
        savefile_path = f"{savefolder_path}/{ticker}.csv"

        # get last entry in savefile
        # TODO: add in try/except checking for last_entry formatting. For now, assume correct
        last_entry = utils.get_lastline(savefile_path)
        
        # no stock history
        if last_entry == -1:
            # create file for stock history
            df = pd.DataFrame(columns=["Datetime","Open","High","Low","Close","Volume","Dividends","Stock Splits","Capital Gains"])
            df.to_csv(savefile_path, index=False)

            # construct dummy yfinance datum for max period
            last_date_str = ""
            last_date_dt = None
        
        # stock history exists
        # TODO: edge case when headers but no data
        elif last_entry:
            # construct yfinance datum for newer data only
            last_date_str = last_entry[0]
            last_date_dt = date_parser.parse(last_date_str)     # convert str to datetime object

        # file error
        else:
            return None
        
        # use stock.history attribute for cleaner dataframe
        # always search for max period, unless more recent last_date_dt
        data = stock.history(period="max", start=last_date_dt, interval=interval)
        data.reset_index(inplace = True)                # remove date as index
        
        # if interval >= 1d, Change column "Date" to "Datetime"
        try:
            data = data.rename(columns={"Date":"Datetime"})
        except Exception:
            pass

        data["Datetime"] = data["Datetime"].astype(str) # convert timestep object to str

        # start=last_date_dt is inclusive, remove redundant result
        i = data[data["Datetime"] == last_date_str].index
        data = data.drop(i)

        # Append to CSV. Note, empty CSV created earlier for first-time write
        data.to_csv(savefile_path, mode='a', index=False, header=False)

        if printout:
            print(f"{ticker} - {interval} data updated")

if __name__=='__main__':
    update_savefiles("..")