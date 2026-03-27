from __future__ import annotations

import csv
import io
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple
import urllib.request

import numpy as np
import pandas as pd
from scipy import interpolate

from sina_option_board import fetch_sse_option_board


OPTION_COLUMNS = ["SEC_NAME", "EXE_MODE", "EXE_PRICE", "EXE_ENDDATE", "CLOSE"]
CHINESE_CALL = "认购"
CHINESE_PUT = "认沽"
QVIX_50ETF_DAILY_URL = "http://1.optbbs.com/d/csv/d/k.csv"
QVIX_REQUEST_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "http://1.optbbs.com/s/vix.shtml?50ETF",
    "Connection": "close",
}


@dataclass
class IvixDataBundle:
    options: pd.DataFrame
    shibor: pd.DataFrame


def load_saved_ivix_history(
    output_path: str = "./ivix.csv",
    tradeday_path: str = "./tradeday.csv",
) -> pd.DataFrame:
    output_file = Path(output_path)
    if not output_file.exists():
        return pd.DataFrame(columns=["DateTime", "value"])

    history = pd.read_csv(output_file)
    if "DateTime" not in history.columns:
        history["DateTime"] = pd.NA
    if "value" not in history.columns:
        history["value"] = np.nan

    date_series = history["DateTime"].copy()
    missing_mask = date_series.isna() | (date_series.astype(str).str.strip() == "")
    missing_count = int(missing_mask.sum())
    if missing_count:
        tradeday_df = pd.read_csv(tradeday_path)
        tradedays = tradeday_df["DateTime"].astype(str).tolist()
        if missing_count > len(tradedays):
            raise ValueError("tradeday.csv does not contain enough dates to align ivix.csv")
        date_series.loc[missing_mask] = tradedays[:missing_count]

    parsed_dates = pd.to_datetime(date_series, format="%Y/%m/%d", errors="coerce")
    result = pd.DataFrame(
        {
            "DateTime": parsed_dates,
            "value": pd.to_numeric(history["value"], errors="coerce"),
        }
    ).dropna()
    result = result.sort_values("DateTime").drop_duplicates(subset=["DateTime"], keep="last").reset_index(drop=True)
    result["DateTime"] = result["DateTime"].dt.strftime("%Y/%m/%d")
    return result


def load_local_data(
    options_path: str = "./options.csv",
    shibor_path: str = "./shibor.csv",
) -> IvixDataBundle:
    options = pd.read_csv(options_path, index_col=0, encoding="GBK")
    options.index.name = "trade_date"
    shibor = pd.read_csv(shibor_path, index_col=0, encoding="GBK")
    return IvixDataBundle(options=options, shibor=shibor)


def _parse_trade_date(date_text: str) -> datetime:
    return datetime.strptime(date_text, "%Y/%m/%d")


def periods_spline_risk_free_interest_rate(options: pd.DataFrame, date: str, shibor_rate: pd.DataFrame) -> Dict[datetime, float]:
    date_dt = _parse_trade_date(date)
    exp_dates = np.sort(options.EXE_ENDDATE.unique())

    periods = {}
    for exp_date in exp_dates:
        exp_dt = pd.to_datetime(exp_date)
        periods[exp_dt] = (exp_dt - date_dt).days / 365.0

    latest_shibor_dt = datetime.strptime(shibor_rate.index[0], "%Y-%m-%d")
    if date_dt >= latest_shibor_dt:
        shibor_values = shibor_rate.iloc[0].values
    else:
        shibor_values = shibor_rate.loc[date_dt.strftime("%Y-%m-%d")].values

    period_nodes = np.asarray([1.0, 7.0, 14.0, 30.0, 90.0, 180.0, 270.0, 360.0]) / 360.0
    min_period = float(np.min(period_nodes))
    max_period = float(np.max(period_nodes))

    linear_interpolator = interpolate.interp1d(period_nodes, shibor_values)
    shibor = {}
    for exp_dt, time_to_expire in periods.items():
        clipped = min(max(time_to_expire, min_period * 1.00001), max_period * 0.99999)
        shibor[exp_dt] = float(linear_interpolator(clipped)) / 100.0
    return shibor


def get_hist_day_options(vix_date: str, options_data: pd.DataFrame) -> pd.DataFrame:
    return options_data.loc[vix_date, :]


def get_near_next_opt_exp_date(options: pd.DataFrame, vix_date: str) -> Tuple[datetime, datetime]:
    vix_dt = _parse_trade_date(vix_date)
    exp_dates = list(pd.Series(options.EXE_ENDDATE.values.ravel()).unique())
    exp_dates = [datetime.strptime(i, "%Y/%m/%d %H:%M") for i in exp_dates]

    near = min(exp_dates)
    exp_dates.remove(near)
    if (near - vix_dt).days < 1:
        near = min(exp_dates)
        exp_dates.remove(near)
    next_exp = min(exp_dates)
    return near, next_exp


def cal_sigma_square(options: pd.DataFrame, risk_free_rate: float, time_to_expire: float) -> float:
    call_all = options[options.EXE_MODE == CHINESE_CALL].set_index("EXE_PRICE").sort_index()
    put_all = options[options.EXE_MODE == CHINESE_PUT].set_index("EXE_PRICE").sort_index()

    columns_to_drop = ["SEC_NAME", "EXE_ENDDATE", "EXE_MODE"]
    call_all = call_all.drop(columns=columns_to_drop)
    put_all = put_all.drop(columns=columns_to_drop)

    call_all = call_all.groupby(level=0).agg({"CLOSE": "min"})
    put_all = put_all.groupby(level=0).agg({"CLOSE": "max"})

    option = call_all.merge(put_all, on="EXE_PRICE", how="inner").rename(
        columns={"CLOSE_x": "call", "CLOSE_y": "put"}
    )
    option["gap"] = abs(option["call"] - option["put"])

    f_idx = option["gap"].idxmin()
    forward_price = f_idx + np.exp(time_to_expire * risk_free_rate) * option.loc[f_idx, "gap"]

    option["price"] = np.where(
        option.index < f_idx,
        option["put"],
        np.where(option.index == f_idx, (option["put"] + option["call"]) / 2, option["call"]),
    )

    idx = option.index
    option.loc[idx[0], "deltaK"] = option.index[1] - option.index[0]
    for i in range(1, len(option) - 1):
        option.loc[idx[i], "deltaK"] = (option.index[i + 1] - option.index[i - 1]) / 2
    option.loc[idx[-1], "deltaK"] = option.index[-1] - option.index[-2]

    option["sigma"] = (option["deltaK"] / (option.index**2)) * np.exp(risk_free_rate * time_to_expire) * option["price"]
    sigma = option["sigma"].sum() * 2 / time_to_expire - ((forward_price / f_idx - 1) ** 2) / time_to_expire
    return float(sigma)


def _format_expiry(expiry_dt: datetime) -> str:
    month = f"{expiry_dt.month:02d}"
    return f"{expiry_dt.year}/{month}/{expiry_dt.day} 0:00"


def cal_day_ivix(vix_date: str, options_data: pd.DataFrame, shibor_rate: pd.DataFrame) -> float:
    options = get_hist_day_options(vix_date, options_data)
    near_exp, next_exp = get_near_next_opt_exp_date(options, vix_date)

    shibor = periods_spline_risk_free_interest_rate(options, vix_date, shibor_rate)
    r_near = shibor[datetime(near_exp.year, near_exp.month, near_exp.day)]
    r_next = shibor[datetime(next_exp.year, next_exp.month, next_exp.day)]

    options_near = options[options.EXE_ENDDATE == _format_expiry(near_exp)]
    options_next = options[options.EXE_ENDDATE == _format_expiry(next_exp)]

    vix_dt = _parse_trade_date(vix_date)
    t_near = (near_exp - vix_dt).days / 365.0
    t_next = (next_exp - vix_dt).days / 365.0

    near_sigma = cal_sigma_square(options_near, r_near, t_near)
    next_sigma = cal_sigma_square(options_next, r_next, t_next)

    weight = (t_next - 30.0 / 365.0) / (t_next - t_near)
    vix = t_near * weight * near_sigma + t_next * (1 - weight) * next_sigma
    return 100 * np.sqrt(abs(vix) * 365.0 / 30.0)


def _infer_column(df: pd.DataFrame, candidates: Iterable[str]) -> Optional[str]:
    for col in candidates:
        if col in df.columns:
            return col
    return None


def _normalize_board_to_option_rows(board: pd.DataFrame, trade_date: str, end_month: str) -> pd.DataFrame:
    strike_col = _infer_column(board, ["行权价", "执行价", "执行价格", "EXE_PRICE"])
    if strike_col is None:
        raise ValueError("无法识别期权行权价列")

    call_name_col = _infer_column(board, ["看涨合约-名称", "认购合约名称", "认购合约", "call_name"])
    put_name_col = _infer_column(board, ["看跌合约-名称", "认沽合约名称", "认沽合约", "put_name"])

    call_price_col = _infer_column(board, ["看涨合约-最新价", "认购最新价", "看涨最新价", "call_latest"])
    put_price_col = _infer_column(board, ["看跌合约-最新价", "认沽最新价", "看跌最新价", "put_latest"])
    if call_price_col is None or put_price_col is None:
        raise ValueError("无法识别期权最新价列")

    expiry_col = _infer_column(board, ["到期日", "到期日期", "expiry_date"])
    if expiry_col is not None:
        expiry_value = pd.to_datetime(board.iloc[0][expiry_col])
    else:
        expiry_value = datetime.strptime("20" + end_month + "25", "%Y%m%d")
    expiry_text = _format_expiry(expiry_value)

    rows: List[dict] = []
    for _, row in board.iterrows():
        strike = float(row[strike_col])
        call_name = row[call_name_col] if call_name_col else f"50ETF购{end_month}{strike}"
        put_name = row[put_name_col] if put_name_col else f"50ETF沽{end_month}{strike}"

        call_price = row[call_price_col]
        put_price = row[put_price_col]
        if pd.notna(call_price):
            rows.append(
                {
                    "trade_date": trade_date,
                    "SEC_NAME": call_name,
                    "EXE_MODE": CHINESE_CALL,
                    "EXE_PRICE": strike,
                    "EXE_ENDDATE": expiry_text,
                    "CLOSE": float(call_price),
                }
            )
        if pd.notna(put_price):
            rows.append(
                {
                    "trade_date": trade_date,
                    "SEC_NAME": put_name,
                    "EXE_MODE": CHINESE_PUT,
                    "EXE_PRICE": strike,
                    "EXE_ENDDATE": expiry_text,
                    "CLOSE": float(put_price),
                }
            )

    options = pd.DataFrame(rows)
    return options.set_index("trade_date")[OPTION_COLUMNS]


def fetch_qvix_50etf_history(url: str = QVIX_50ETF_DAILY_URL) -> pd.DataFrame:
    request = urllib.request.Request(url, headers=QVIX_REQUEST_HEADERS)
    with urllib.request.urlopen(request, timeout=30) as response:
        text = response.read().decode("utf-8-sig", errors="replace")

    rows: List[dict] = []
    for index, row in enumerate(csv.reader(io.StringIO(text))):
        if index == 0 or len(row) <= 4:
            continue
        date_text = row[0].strip()
        close_text = row[4].strip()
        if not date_text or not close_text or close_text.startswith("#"):
            continue
        rows.append(
            {
                "DateTime": pd.to_datetime(date_text, format="%Y/%m/%d", errors="coerce"),
                "value": pd.to_numeric(close_text, errors="coerce"),
            }
        )

    history = pd.DataFrame(rows).dropna()
    if history.empty:
        raise RuntimeError("QVIX 50ETF 历史数据为空")

    history = history.sort_values("DateTime").drop_duplicates(subset=["DateTime"], keep="last").reset_index(drop=True)
    history["DateTime"] = history["DateTime"].dt.strftime("%Y/%m/%d")
    return history


def backfill_ivix_history(
    output_path: str = "./ivix.csv",
    tradeday_path: str = "./tradeday.csv",
) -> pd.DataFrame:
    existing_history = load_saved_ivix_history(output_path=output_path, tradeday_path=tradeday_path)
    qvix_history = fetch_qvix_50etf_history()

    # Prefer locally computed legacy values when the same date exists in both sources.
    merged_history = pd.concat([qvix_history, existing_history], ignore_index=True)
    merged_history["value"] = pd.to_numeric(merged_history["value"], errors="coerce")
    merged_history = merged_history.dropna(subset=["DateTime", "value"])
    merged_history = merged_history.sort_values("DateTime").drop_duplicates(subset=["DateTime"], keep="last")
    merged_history = merged_history.reset_index(drop=True)
    merged_history.to_csv(output_path, index=False)
    return merged_history


def fetch_latest_option_data(trade_date: str, months_ahead: int = 4) -> pd.DataFrame:
    day = _parse_trade_date(trade_date)
    month_codes = []
    for i in range(months_ahead):
        y = day.year + (day.month - 1 + i) // 12
        m = (day.month - 1 + i) % 12 + 1
        month_codes.append(f"{str(y)[-2:]}{m:02d}")

    collected = []
    for month_code in month_codes:
        try:
            board = fetch_sse_option_board(month_code=month_code)
        except Exception:
            continue
        if board is None or board.empty:
            continue
        normalized = _normalize_board_to_option_rows(board, trade_date=trade_date, end_month=month_code)
        collected.append(normalized)

    if len(collected) < 2:
        raise RuntimeError("获取到的期权月合约不足，至少需要近月与次近月两组数据")
    return pd.concat(collected).sort_values(["EXE_ENDDATE", "EXE_PRICE", "EXE_MODE"])


def refresh_latest_ivix(
    output_path: str = "./ivix.csv",
    options_path: str = "./options.csv",
    shibor_path: str = "./shibor.csv",
    tradeday_path: str = "./tradeday.csv",
) -> Tuple[str, float]:
    bundle = load_local_data(options_path=options_path, shibor_path=shibor_path)

    # 以当前系统日期作为默认交易日。若非交易日，最新期权月合约抓取会触发异常。
    latest_trade_date = datetime.now().strftime("%Y/%m/%d")
    latest_options = fetch_latest_option_data(latest_trade_date)

    all_options = pd.concat([bundle.options, latest_options]).reset_index().drop_duplicates(
        subset=["trade_date", "SEC_NAME", "EXE_MODE", "EXE_PRICE", "EXE_ENDDATE"],
        keep="last",
    ).set_index("trade_date")

    latest_ivix = cal_day_ivix(latest_trade_date, all_options, bundle.shibor)

    history = load_saved_ivix_history(output_path=output_path, tradeday_path=tradeday_path)
    history = history[history["DateTime"] != latest_trade_date]
    history = pd.concat(
        [history, pd.DataFrame([{"DateTime": latest_trade_date, "value": latest_ivix}])],
        ignore_index=True,
    )
    history.to_csv(output_path, index=False)
    return latest_trade_date, latest_ivix


def sync_and_refresh_ivix(
    output_path: str = "./ivix.csv",
    options_path: str = "./options.csv",
    shibor_path: str = "./shibor.csv",
    tradeday_path: str = "./tradeday.csv",
) -> Tuple[str, float]:
    try:
        history = backfill_ivix_history(output_path=output_path, tradeday_path=tradeday_path)
        print(f"backfilled ivix history rows={len(history)}")
    except Exception as exc:
        print(f"warning: failed to backfill ivix history: {exc}")

    return refresh_latest_ivix(
        output_path=output_path,
        options_path=options_path,
        shibor_path=shibor_path,
        tradeday_path=tradeday_path,
    )


if __name__ == "__main__":
    date_text, ivix_value = sync_and_refresh_ivix()
    print(f"latest ivix({date_text})={ivix_value:.4f}")
