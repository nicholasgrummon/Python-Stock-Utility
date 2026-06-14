import logging
import numpy as np

logger = logging.getLogger(__name__)

def moving_avg(data_hist, period):
    '''
    Determines mean of data in window for each window of width=period in data_hist

    Moving average used to indicate undervalued when SMA<LMA and overvalued when SMA>LMA
    SMA and LMA periods are set using heuristics or tuning algorithms
    '''
    mavg = []
    for i in range(period, len(data_hist)+1):
        mavg.append(sum(data_hist[i-period:i])/period)

    return mavg

def XmR(data_hist):
    k = len(data_hist)
    x_bar = sum(data_hist) / k
    mR = sum([float(data_hist[i+1] - data_hist[i]) for i in range(k - 1)]) / (k-1)

    E = np.sqrt(sum([float(data_hist[i+1] - data_hist[i])**2 for i in range(k - 1)]))

    upper_limit = x_bar + E*mR
    lower_limit = x_bar - E*mR

    print(upper_limit, lower_limit)

def fibonacci_support_delta(swing, lvl):
    '''
    Determines support levels at given price using fibonacci replacement approach

    Fibonacci replacement levels used to set significance threshold for indicator variance
    '''
    f_lvls = np.array([0.236, 0.382, 0.500, 0.618, 0.786]) # ratios of subsequent fibonacci numbers
    return np.multiply(swing, f_lvls)[lvl]


def relative_strength_index(data_hist, period=14):
    '''
    Determines the RSI momentum indicator given a data_hist using Wilder's smoothing

    RSI>70 indicates overvalued (Sell), RSI<30 indicates undervalued (Buy)

    Returns a list of RSI values aligned with data_hist[period:]
    '''
    if len(data_hist) <= period:
        return []

    deltas = np.diff(data_hist)
    gains = np.clip(deltas, 0, None)
    losses = np.clip(-deltas, 0, None)

    avg_gain = np.mean(gains[:period])
    avg_loss = np.mean(losses[:period])

    def _rsi(avg_gain, avg_loss):
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100 - (100 / (1 + rs))

    rsi = [_rsi(avg_gain, avg_loss)]
    for i in range(period, len(deltas)):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        rsi.append(_rsi(avg_gain, avg_loss))

    return rsi


def bollinger_bands(data_hist, period=20, num_std=2):
    '''
    Determines Bollinger Bands (SMA +/- num_std standard deviations) for data_hist

    Price above upper band indicates overvalued (Sell), below lower band indicates undervalued (Buy)

    Returns a list of (lower, middle, upper) tuples aligned with data_hist[period-1:]
    '''
    if len(data_hist) < period:
        return []

    data = np.asarray(data_hist, dtype=float)
    middle = moving_avg(data_hist, period)

    bands = []
    for i in range(period, len(data) + 1):
        window = data[i-period:i]
        std = np.std(window)
        mean = middle[i-period]
        bands.append((mean - num_std*std, mean, mean + num_std*std))

    return bands


def average_directional_index(high_hist, low_hist, close_hist, period=14):
    '''
    Determines the Average Directional Index (ADX) trend-strength indicator using Wilder's smoothing

    hist lists must have the same length

    ADX>25 indicates a strong trend (directional signals more reliable)
    ADX<20 indicates a weak/non-trending market (directional signals less reliable)

    Returns a list of ADX values
    '''
    n = len(high_hist)
    if n < 2*period:
        return []

    plus_dm = [0.0] * n
    minus_dm = [0.0] * n
    tr = [0.0] * n

    for i in range(1, n):
        up_move = high_hist[i] - high_hist[i-1]
        down_move = low_hist[i-1] - low_hist[i]

        plus_dm[i] = up_move if (up_move > down_move and up_move > 0) else 0.0
        minus_dm[i] = down_move if (down_move > up_move and down_move > 0) else 0.0

        tr[i] = max(
            high_hist[i] - low_hist[i],
            abs(high_hist[i] - close_hist[i-1]),
            abs(low_hist[i] - close_hist[i-1])
        )

    # seed Wilder smoothing with the sum of the first `period` values
    smoothed_tr = sum(tr[1:period+1])
    smoothed_plus_dm = sum(plus_dm[1:period+1])
    smoothed_minus_dm = sum(minus_dm[1:period+1])

    dx_values = []
    for i in range(period+1, n):
        smoothed_tr = smoothed_tr - (smoothed_tr/period) + tr[i]
        smoothed_plus_dm = smoothed_plus_dm - (smoothed_plus_dm/period) + plus_dm[i]
        smoothed_minus_dm = smoothed_minus_dm - (smoothed_minus_dm/period) + minus_dm[i]

        plus_di = 100 * (smoothed_plus_dm/smoothed_tr) if smoothed_tr else 0.0
        minus_di = 100 * (smoothed_minus_dm/smoothed_tr) if smoothed_tr else 0.0

        di_sum = plus_di + minus_di
        dx_values.append(100 * abs(plus_di - minus_di)/di_sum if di_sum else 0.0)

    if len(dx_values) < period:
        return []

    # ADX is itself a Wilder-smoothed average of DX
    adx = [sum(dx_values[:period]) / period]
    for dx in dx_values[period:]:
        adx.append((adx[-1] * (period-1) + dx) / period)

    return adx


def buy_sell_indicator(data_hist):
    '''
    Current evaluation only determines if LMA,SMA delta exceeds fibonacci support

    Returns "Buy", "Sell", or "Hold". Returns "Hold" if there is not enough history
    to compute the SMA(20)/LMA(50) crossover.
    '''
    if len(data_hist) < 50:
        return "Hold"

    period_swing = max(data_hist) - min(data_hist)
    sma = moving_avg(data_hist, 20)
    lma = moving_avg(data_hist, 50)

    support = fibonacci_support_delta(period_swing, 4) # level 4 is moderate support

    logger.debug(f"sma: {sma[-1]}, lma: {lma[-1]}, support: {support}")
    if sma[-1] - lma[-1] < - support:
        return "Buy"

    elif sma[-1] - lma[-1] > support:
        return "Sell"

    else:
        return "Hold"


def evaluate_signal(history_df, adx_threshold=20):
    '''
    Combines the SMA/LMA-fibonacci crossover, RSI, and Bollinger Band indicators into a single
    Buy/Sell/Hold signal, gated by ADX trend strength.

    history_df must contain "High", "Low", and "Close" columns ordered oldest -> newest.

    Returns "Buy", "Sell", or "Hold"
    '''
    close = history_df["Close"].tolist()
    high = history_df["High"].tolist()
    low = history_df["Low"].tolist()

    votes = []

    sma_lma_signal = buy_sell_indicator(close)
    if sma_lma_signal != "Hold":
        votes.append(sma_lma_signal)

    rsi = relative_strength_index(close)
    if rsi:
        if rsi[-1] < 30:
            votes.append("Buy")
        elif rsi[-1] > 70:
            votes.append("Sell")

    bands = bollinger_bands(close)
    if bands:
        lower, _, upper = bands[-1]
        if close[-1] < lower:
            votes.append("Buy")
        elif close[-1] > upper:
            votes.append("Sell")

    if not votes:
        return "Hold"

    # only trust directional votes when ADX indicates a trending market
    adx = average_directional_index(high, low, close)
    if adx and adx[-1] < adx_threshold:
        return "Hold"

    buy_votes = votes.count("Buy")
    sell_votes = votes.count("Sell")

    if buy_votes > sell_votes:
        return "Buy"
    elif sell_votes > buy_votes:
        return "Sell"
    else:
        return "Hold"
