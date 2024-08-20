import akshare as ak
import pandas as pd


def outputShibor():
    shibor_1D = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="隔夜")
    shibor_1W = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="1周")
    shibor_2W = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="2周")
    shibor_1M = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="1月")
    shibor_3M = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="3月")
    shibor_6M = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="6月")
    shibor_9M = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="9月")
    shibor_1Y = ak.rate_interbank(market="上海银行同业拆借市场", symbol="Shibor人民币", indicator="1年")

    shibor_1D.rename(columns={'利率': '1D'}, inplace=True)
    shibor_1D.drop(['涨跌'], axis=1, inplace=True)
    shibor_1W.rename(columns={'利率': '1W'}, inplace=True)
    shibor_1W.drop(['涨跌'], axis=1, inplace=True)
    shibor_2W.rename(columns={'利率': '2W'}, inplace=True)
    shibor_2W.drop(['涨跌'], axis=1, inplace=True)
    shibor_1M.rename(columns={'利率': '1M'}, inplace=True)
    shibor_1M.drop(['涨跌'], axis=1, inplace=True)
    shibor_3M.rename(columns={'利率': '3M'}, inplace=True)
    shibor_3M.drop(['涨跌'], axis=1, inplace=True)
    shibor_6M.rename(columns={'利率': '6M'}, inplace=True)
    shibor_6M.drop(['涨跌'], axis=1, inplace=True)
    shibor_9M.rename(columns={'利率': '9M'}, inplace=True)
    shibor_9M.drop(['涨跌'], axis=1, inplace=True)
    shibor_1Y.rename(columns={'利率': '1Y'}, inplace=True)
    shibor_1Y.drop(['涨跌'], axis=1, inplace=True)

    shibor_frames = [shibor_1D, shibor_1W, shibor_2W, shibor_1M, shibor_3M, shibor_6M, shibor_9M, shibor_1Y]
    from functools import reduce
    shibor = reduce(lambda left, right: pd.merge(left, right, on='报告日'), shibor_frames)
    shibor.set_index('报告日', inplace=True)
    shibor.iloc[::-1].to_csv('./shibor2.csv', encoding='gbk', header=True)


def outputOption():
    option_finance_board_df = ak.option_finance_board(symbol="华夏上证50ETF期权", end_month="2407")
    # option_finance_board_df = ak.option_finance_board(symbol="上证50股指期权", end_month="2407")
    print(option_finance_board_df)


outputOption()