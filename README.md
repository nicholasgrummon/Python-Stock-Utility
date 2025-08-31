# Python Stock Utility
Author: Nicholas Grummon <br>
Date: 8/31/2025 Initial Commit <br>

## Summary
Python Stock Utility is a background task that records market data for stocks in a user-specified watchlist, using the yfinance library. It also monitors a variety of technical indicators and has the capability to send BUY/SELL signals to a user via SMS.

### Key Folder Structure and Files
#### main.py
main runner file. Refreshes once per minute. Monitors market hours, polls yfinance for new price data, and calls helper functions to calculate technical indicators and send SMS.<br>
Execute via `$ nohup python Playground/sandbox.py &`<br>
Kill job via `$ kill $(pgrep python)` or `$ kill $(ps -e | grep python | awk '{print $1}')`

### Util Files - Ensure project directory is added to path in order to import
#### utils.py
Contains helper functions for file management, including the ability to check for existence of a folder, to make new folder if not found, or to read the last line of a file. Helper functions are defined separately to avoid clutter.<br>

#### ./Evaluation/evals_utils.py
Contains helper functions for calculating technical indicators, including BUY/SELL signal.

#### ./Historical/hist_utils.py
Contains helper functions for maintaining history data save files. Updates existing save file or creates new file with max period if no history found

### Positions Folder
#### ./Positions/Holdings.csv
Contains a list of current positions held by the user. SELL signals are only generated for positions in this list.

#### ./Positions/Watchlist.csv
Contains a list of all positions to monitor. Historical data is maintained for all positions in this list.

### SMS Manager Folder
#### ./SMS_Manager/contacts.csv
List of contacts to send BUY/SELL signals to.

#### ./SMS_Manager/sender_details.csv
Login info for email server.
