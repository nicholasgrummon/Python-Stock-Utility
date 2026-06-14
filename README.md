# Python Stock Utility
Author: Nicholas Grummon <br>
Date: 8/31/2025 Initial Commit <br>

## Summary
Python Stock Utility is a background task that records market data for stocks in a user-specified watchlist, using the yfinance library. It also monitors a variety of technical indicators and has the capability to send BUY/SELL signals to a user via SMS.

### Key Folder Structure and Files
#### main.py
main runner file. Refreshes once per minute. Monitors market hours, polls yfinance for new price data, evaluates the combined technical signal for each watchlisted ticker, and SMS's the contact distro list whenever a ticker's signal changes (BUY signals for any watchlisted ticker, SELL signals only for tickers held in Holdings.csv).<br>
Logs are written to `Logs/main.log` (rotated at 1 MB, 5 backups kept) and echoed to stdout.

Run directly with: `$ nohup python main.py &`<br>
Kill job via `$ kill $(pgrep -f main.py)`<br>
For a managed background service that restarts automatically, see [Deployment](#deployment) below.

### Util Files - Ensure project directory is added to path in order to import
#### utils.py
Contains helper functions for file management, including the ability to check for existence of a folder, to make new folder if not found, or to read the last line of a file. Helper functions are defined separately to avoid clutter.<br>

#### ./Evaluation/eval_utils.py
Contains helper functions for calculating technical indicators and combining them into a BUY/SELL/HOLD signal:
- `moving_avg` - simple moving average over a window
- `fibonacci_support_delta` - fibonacci-ratio support/resistance levels for a price swing
- `relative_strength_index` - Wilder's RSI momentum oscillator (>70 overbought/Sell, <30 oversold/Buy)
- `bollinger_bands` - SMA +/- standard-deviation bands (price outside the bands signals overbought/oversold)
- `average_directional_index` - Wilder's ADX trend-strength indicator, used to gate signals to trending markets (ADX >= 20)
- `buy_sell_indicator` - SMA(20)/LMA(50) crossover compared against fibonacci support
- `evaluate_signal(history_df)` - combines all of the above into a single "Buy"/"Sell"/"Hold" signal for a ticker's OHLC history

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

### Environment Variables
#### ./.env
Holds the Gmail-to-SMS sender credentials (`GMAIL_ADDR`, `GMAIL_APP_PASSWORD`), loaded at runtime via `python-dotenv`. This file is gitignored - copy `.env.example` to `.env` and fill in a [Gmail App Password](https://myaccount.google.com/apppasswords) before running.

## Deployment
`main.py` runs forever, sleeping through non-trading hours and polling once per minute during market hours, so it is meant to run as a background service rather than in a foreground terminal.

### systemd user service (recommended)
A unit file is provided at `Deploy/psu.service`. To install:
```
$ ./Deploy/install.sh
```
This copies the unit to `~/.config/systemd/user/`, then enables and starts it. Useful commands afterwards:
```
$ systemctl --user status psu.service     # check it's running
$ journalctl --user -u psu.service -f     # follow logs (Logs/main.log has the same output)
$ systemctl --user restart psu.service    # restart after a code/config change
$ systemctl --user stop psu.service       # stop
```
The service restarts automatically on failure. To keep it running after you log out (e.g. on a headless server), run `loginctl enable-linger $USER` once.

### Manual (no systemd)
```
$ nohup python main.py &
$ kill $(pgrep -f main.py)
```
