import pandas as pd
import numpy as np

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

def fibonacci_support_delta(swing, lvl):
    '''
    Determines support levels at given price using fibonacci replacement approach

    Fibonacci replacement levels used to set significance threshold for indicator variance
    '''
    f_lvls = np.array([0.236, 0.382, 0.500, 0.618, 0.786]) # ratios of subsequent fibonacci numbers
    return np.multiply(swing, f_lvls)[lvl]


def directional_movement(high_hist, low_hist, close_hist, period):
    '''
    
    hist lists must have the same length
    '''
    for i in range(1,len(high_hist)):
        # determine plus/minus directional movement
        plus_mvmt = high_hist[i] - high_hist[i-1]
        minus_mvmt = low_hist[i] - low_hist[i-1]
        
        # correct for both positive
        if plus_mvmt > minus_mvmt > 0:
            minus_mvmt = 0
        elif minus_mvmt > plus_mvmt > 0:
            plus_mvmt = 0
        
        # calculate true range
        tr = max([high_hist[i]-low_hist[i], high_hist[i]-close_hist[i-1], low_hist[i]-close_hist[i-1]])


# def relative_strength_index(data_hist, period, rsi_history=None):
#     '''
#     Determines the RSI momentum indicator given a data_hist

#     RSI>70 indicates overvalues, RSI<30 indicates undervalued
#     '''
#     if rsi_history:


def update_indicators(interval, ticker, dirFilepath):
    # retrieve stock history
    # history = pd.read_csv(f"{dirFilepath}/Historical/{interval}_history/{ticker}.csv", index_col=0)

    # close = history["Close"]

    # for indicator in [lambda d: moving_avg(d, 10), lambda d: moving_avg(d, 50)]:
    #     indicator_data = indicator(close)
    #     print(indicator_data[-20:])

    print(directional_movement([1,2,3,4,5,4,3,4,5,6,7,8,9,8,7]))

def buy_sell_indicator(data_hist):
    '''
    Current evaluation only determines is LMA,SMA delta exceeds fibonacci support
    
    '''
    period_swing = max(data_hist) - min(data_hist)
    sma = moving_avg(data_hist, 20)
    lma = moving_avg(data_hist, 50)

    support = fibonacci_support_delta(period_swing, 4) # level 4 is moderate support

    # TODO: different data structure for most recent indicator value to avoid reading list every time
    print(f"sma: {sma[-1]}, lma: {lma[-1]}, support: {support}")
    if sma[-1] - lma[-1] < - support:
        return "Buy"
    
    elif sma[-1] - lma[-1] > support:
        return "Sell"
    
    else:
        return 0

