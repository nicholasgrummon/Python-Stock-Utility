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

SAVEFILE_HEADER = ["Datetime","Open","High","Low","Close","Volume","Dividends","Stock Splits","Capital Gains"]
NYC = pytz.timezone("America/New_York")


def touch_savefile(base_dir, watchlist_df):
    for ticker in watchlist_df["Ticker"]:
        for interval in ["1m", "1h", "1d"]:
            savefolder_path = os.path.join(base_dir, f"Historical/{interval}_history")
            os.makedirs(savefolder_path, exist_ok=True)
            savefile_path = os.path.join(savefolder_path, f"{ticker}.csv")
            if not os.path.isfile(savefile_path):
                df = pd.DataFrame(columns=SAVEFILE_HEADER)
                df.to_csv(savefile_path, index=False)


def get_start_search(savefile_path, default_period=365):
    # TODO: add in try/except checking for last_entry formatting. For now, assume correct
    last_entry = utils.get_lastline(savefile_path)
    try:
        default_search_dt = datetime.now(NYC) - timedelta(days=default_period)
        last_entry_dt = date_parser.parse(last_entry[0])
        return max(last_entry_dt, default_search_dt)
    
    except Exception as e:
        return None
        

def get_yf_data(stock, start_search_dt, interval):
    data = stock.history(start=start_search_dt, interval=interval)
    if data.empty:
        data = stock.history(period="max", interval=interval)

    # clean data
    data.reset_index(inplace=True)
    if "Date" in data.columns:
        data = data.rename(columns={"Date":"Datetime"})
    
    return data.drop(data[data["Datetime"] == start_search_dt].index)


def update_savefiles(base_dir, watchlist_df, default_period=365, printout=False):
    '''
    Collect historical data for specified stock.
    - Write new savefile with max history if no data saved
    - Append newer data if outdated data exists

    Pass dirFilepath to allow project to be installed s
    '''
    for ticker in watchlist_df["Ticker"]:
        for interval in ["1m", "1h", "1d"]:
            savefolder_path = os.path.join(base_dir, f"Historical/{interval}_history")
            savefile_path = os.path.join(savefolder_path, f"{ticker}.csv")

            stock = yf.Ticker(ticker)
            start_search_dt = get_start_search(savefile_path, default_period)
            data = get_yf_data(stock, start_search_dt, interval)
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
    