# Python Stock Utility
Author: Nicholas Grummon <br>
Date: 8/31/2025 Initial Commit <br>

## Summary
Python Stock Utility is a background task that records market data for stocks in a user-specified watchlist, using the yfinance library. It also monitors a variety of technical indicators, rolls them up into a 0-10 buy/sell rating per ticker, and posts updates to a Discord channel via a bot.

### Key Folder Structure and Files
#### main.py
main runner file. Refreshes once per minute. Monitors market hours, polls yfinance for new price data, updates each ticker's indicator CSV and rating, and posts to Discord whenever a ticker's rating crosses into STRONG BUY (any watchlisted ticker) or STRONG SELL (tickers held in Holdings.csv only). Also posts a full ratings-table summary once a week (see [Notifications Folder](#notifications-folder)).<br>
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

#### ./Evaluation/rating_utils.py
Reads each ticker's indicator CSV and blends RSI, Bollinger %B, and SMA20/50 spread into a continuous 0 (Sell) - 10 (Strong Buy) rating, damped by ADX trend strength — the same formula used by the dashboard's Home page. `tier(value)` maps the rating to STRONG BUY/BUY/HOLD/SELL/STRONG SELL, which is what drives Discord alerts.

#### ./Historical/hist_utils.py
Contains helper functions for maintaining history data save files. Updates existing save file or creates new file with max period if no history found

### Positions Folder
#### ./Positions/Holdings.csv
Contains a list of current positions held by the user. SELL signals are only generated for positions in this list.

#### ./Positions/Watchlist.csv
Contains a list of all positions to monitor. Historical data is maintained for all positions in this list.

### Notifications Folder
#### ./Notifications/discord_utils.py
Posts to a Discord channel via the bot REST API (`POST /channels/{id}/messages` with `Authorization: Bot <token>`) — no gateway connection needed since these messages only flow outward. Two things trigger a post, both from the main loop in `main.py`:
- `check_rating_alerts` - fires whenever a ticker's rating tier (from `rating_utils`) transitions into STRONG BUY or STRONG SELL.
- `maybe_send_weekly_summary` - posts the full ratings table once every 7 days, tracked in the gitignored state file `./Notifications/.weekly_state`.

If `DISCORD_BOT_TOKEN`/`DISCORD_CHANNEL_ID` aren't set, the notifier logs and no-ops instead of raising, so the rest of the loop (history/indicator updates, dashboard generation) keeps running.

#### ./Notifications/discord_bot.py
Registers a `/dashboard` slash command that replies with the same ratings table on demand. Unlike the REST posts above, receiving a slash-command interaction requires a live gateway connection, so this runs `discord.py`'s `Client` on its own asyncio event loop in a daemon thread (started from `main.py` alongside the synchronous polling loop — they don't share state; the command just re-reads `Positions/Watchlist.csv` and the indicator CSVs fresh each time it's invoked). The command is synced to whichever guild the configured channel belongs to, so it's available immediately rather than waiting on Discord's global-command propagation delay.

### Environment Variables
#### ./.env
Holds the Discord bot credentials (`DISCORD_BOT_TOKEN`, `DISCORD_CHANNEL_ID`), loaded at runtime via `python-dotenv`. This file is gitignored - copy `.env.example` to `.env` and fill in a bot token (from the [Discord Developer Portal](https://discord.com/developers/applications) — create an application, add a Bot, enable it, and invite it to your server with the `applications.commands` and `bot` scopes plus the `Send Messages` permission) and the target channel's ID (right-click the channel in Discord with Developer Mode enabled → Copy Channel ID) before running.

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
