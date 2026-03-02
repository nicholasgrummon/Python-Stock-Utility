import sys
sys.path.append("/home/ncg/Documents/pythonStockUtility/")
import utils

# import data handling libraries
import os
import pandas as pd
import yfinance as yf

# import time handling libraries
from datetime import datetime, timedelta
from dateutil import parser as date_parser
import pytz
nyc = pytz.timezone("America/New_York")

def update_savefiles(dirFilepath, interval, ticker, printout=False):
    '''
    Collect historical data for specified stock.
    - Write new savefile with max history if no data saved
    - Append newer data if outdated data exists

    Pass dirFilepath to allow project to be installed s
    '''
    # download yfinance object for specified ticker
    stock = yf.Ticker(ticker)

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
        earliest_data_dt = datetime.now(nyc) - timedelta(days=7)
        last_date_dt = date_parser.parse(last_entry[0])
        last_date_dt = max(earliest_data_dt, last_date_dt)  # cut off interval to avoid search error

    # file error
    else:
        return None
    
    # use stock.history attribute for cleaner dataframe
    # default to max period if start date is None
    data = stock.history(start=last_date_dt, period="max", interval=interval)
    data.reset_index(inplace = True)                # remove date as index
    
    # if interval >= 1d, Change column "Date" to "Datetime"
    try:
        data = data.rename(columns={"Date":"Datetime"})
    except Exception:
        pass

    data["Datetime"] = data["Datetime"].astype(str) # convert timestep object to str

    # start=last_date_dt is inclusive, remove redundant result
    i = data[data["Datetime"] == last_date_dt].index
    data = data.drop(i)

    # Append to CSV. Note, empty CSV created earlier for first-time write
    data.to_csv(savefile_path, mode='a', index=False, header=False)

    if printout:
        print(f"{ticker} - {interval} data updated")


def convert_savefiles_to_parquet(dirFilepath):
    path = f"{dirFilepath}/Historical"
    parquet_basepath = f"{dirFilepath}/Historical_bin"

    for interval in os.listdir(path):
        interval_path = os.path.join(path,interval)

        if interval[0] != "_" and os.path.isdir(interval_path):
            for ticker in os.listdir(interval_path):
                df = pd.read_csv(os.path.join(interval_path, ticker))
                parquet_path = os.path.join(parquet_basepath,interval,ticker)

                print(parquet_path)
                # df.to_parquet(parquet_path, engine="pyarrow")


if __name__=='__main__':
    # update_savefiles("..")
    convert_savefiles_to_parquet(".")
    