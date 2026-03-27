from __future__ import annotations

import argparse
import calendar
from pathlib import Path
from typing import Any

import akshare as ak
import numpy as np
import pandas as pd

from config.instruments import INSTRUMENTS
from ivvx import CHINESE_CALL, CHINESE_PUT, OPTION_COLUMNS, _normalize_board_to_option_rows, cal_day_ivix
from sina_option_board import fetch_sse_option_board


ROOT = Path(__file__).resolve().parent
FACTOR_DIR = ROOT / "storage" / "factors"
RAW_DIR = ROOT / "storage" / "raw"
CONTRACT_DIR = RAW_DIR / "contracts"
PANEL_PATH = FACTOR_DIR / "ivix_dual_panel.csv"
SIGNAL_PATH = FACTOR_DIR / "ivix_signals.csv"
SHIBOR_PATH = ROOT / "shibor.csv"
SHIBOR_CACHE_PATH = RAW_DIR / "shibor_all.csv"


def ensure_factor_dir() -> None:
    FACTOR_DIR.mkdir(parents=True, exist_ok=True)
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)


def rolling_zscore(series: pd.Series, window: int) -> pd.Series:
    rolling_mean = series.rolling(window=window, min_periods=window).mean()
    rolling_std = series.rolling(window=window, min_periods=window).std()
    rolling_std = rolling_std.replace(0, np.nan)
    return (series - rolling_mean) / rolling_std


def format_date_column(df: pd.DataFrame, column: str = "date") -> pd.DataFrame:
    result = df.copy()
    result[column] = pd.to_datetime(result[column], errors="coerce").dt.strftime("%Y-%m-%d")
    return result


def fetch_qvix_history(instrument_id: str) -> pd.DataFrame:
    instrument = INSTRUMENTS[instrument_id]
    qvix_func = getattr(ak, instrument["ak_qvix_func"])
    raw = qvix_func()
    if raw.empty:
        raise RuntimeError(f"{instrument_id} QVIX history is empty")

    history = raw.rename(columns=str.lower).copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history = history.dropna(subset=["date"])

    for col in ["open", "high", "low", "close"]:
        history[col] = pd.to_numeric(history[col], errors="coerce")

    valid_start = pd.to_datetime(instrument["valid_start"])
    history = history[history["date"] >= valid_start]
    history.loc[history["close"] <= 0, "close"] = np.nan
    history = history.dropna(subset=["close"]).sort_values("date")
    history = history.drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)

    for col in ["open", "high", "low"]:
        history.loc[history[col] <= 0, col] = np.nan
        history[col] = history[col].fillna(history["close"])

    result = pd.DataFrame(
        {
            "date": history["date"],
            "instrument_id": instrument_id,
            "ivix_close": history["close"],
            "ivix_open": history["open"],
            "ivix_high": history["high"],
            "ivix_low": history["low"],
            "source": f"akshare:{instrument['ak_qvix_func']}",
        }
    )
    return result


def sync_instrument(instrument_id: str) -> pd.DataFrame:
    ensure_factor_dir()
    history = fetch_qvix_history(instrument_id)
    output_path = FACTOR_DIR / INSTRUMENTS[instrument_id]["output_name"]
    format_date_column(history).to_csv(output_path, index=False, encoding="utf-8-sig")
    return history


def sync_all() -> dict[str, pd.DataFrame]:
    return {instrument_id: sync_instrument(instrument_id) for instrument_id in INSTRUMENTS}


def infer_end_months(base_date: pd.Timestamp | None = None, months_ahead: int = 3) -> list[str]:
    if base_date is None:
        base_date = pd.Timestamp.today().normalize()
    month_codes: list[str] = []
    for offset in range(months_ahead):
        month_start = base_date + pd.DateOffset(months=offset)
        month_codes.append(month_start.strftime("%y%m"))
    return month_codes


def load_trade_calendar() -> pd.DatetimeIndex:
    trade_dates = ak.tool_trade_date_hist_sina()
    calendar_index = pd.to_datetime(trade_dates["trade_date"], errors="coerce").dropna().sort_values().unique()
    return pd.DatetimeIndex(calendar_index)


def latest_trade_date(today: pd.Timestamp | None = None) -> pd.Timestamp:
    if today is None:
        today = pd.Timestamp.today().normalize()
    trade_calendar = load_trade_calendar()
    available = trade_calendar[trade_calendar <= today]
    if len(available) == 0:
        raise RuntimeError("no available trade date found from trade calendar")
    return pd.Timestamp(available[-1]).normalize()


def fetch_shibor_curve_history(force_refresh: bool = False) -> pd.DataFrame:
    ensure_factor_dir()
    trade_date = latest_trade_date()

    if SHIBOR_CACHE_PATH.exists() and not force_refresh:
        cached = pd.read_csv(SHIBOR_CACHE_PATH, index_col=0)
        cached.index = cached.index.astype(str)
        if len(cached.index) > 0 and cached.index[0] >= trade_date.strftime("%Y-%m-%d"):
            return cached

    raw = ak.macro_china_shibor_all()
    rename_map = {
        "日期": "date",
        "O/N-定价": "1D",
        "1W-定价": "1W",
        "2W-定价": "2W",
        "1M-定价": "1M",
        "3M-定价": "3M",
        "6M-定价": "6M",
        "9M-定价": "9M",
        "1Y-定价": "1Y",
    }
    shibor = raw.rename(columns=rename_map)[["date", "1D", "1W", "2W", "1M", "3M", "6M", "9M", "1Y"]].copy()
    shibor["date"] = pd.to_datetime(shibor["date"], errors="coerce")
    for col in ["1D", "1W", "2W", "1M", "3M", "6M", "9M", "1Y"]:
        shibor[col] = pd.to_numeric(shibor[col], errors="coerce")
    shibor = shibor.dropna(subset=["date"]).sort_values("date", ascending=False).drop_duplicates(subset=["date"], keep="first")
    shibor = shibor.set_index(shibor["date"].dt.strftime("%Y-%m-%d")).drop(columns=["date"])
    shibor.to_csv(SHIBOR_CACHE_PATH, index=True)
    shibor.to_csv(SHIBOR_PATH, index=True)
    return shibor


def cffex_month_expiry(end_month: str) -> pd.Timestamp:
    year = 2000 + int(end_month[:2])
    month = int(end_month[2:])
    month_matrix = calendar.monthcalendar(year, month)
    fridays = [week[calendar.FRIDAY] for week in month_matrix if week[calendar.FRIDAY] != 0]
    third_friday = pd.Timestamp(year=year, month=month, day=fridays[2])
    trade_calendar = load_trade_calendar()
    adjusted = trade_calendar[trade_calendar >= third_friday]
    if len(adjusted) == 0:
        raise RuntimeError(f"no adjusted expiry found for {end_month}")
    return pd.Timestamp(adjusted[0]).normalize()


def option_price_from_board_row(row: pd.Series) -> float | None:
    candidates = [
        pd.to_numeric(row.get("lastprice"), errors="coerce"),
        pd.to_numeric(row.get("bprice"), errors="coerce"),
        pd.to_numeric(row.get("sprice"), errors="coerce"),
    ]
    positives = [float(value) for value in candidates if pd.notna(value) and float(value) > 0]
    if not positives:
        return None
    return positives[0]


def normalize_cffex_board_to_option_rows(board: pd.DataFrame, trade_date: str, end_month: str) -> pd.DataFrame:
    expiry = cffex_month_expiry(end_month)
    expiry_text = f"{expiry.year}/{expiry.month:02d}/{expiry.day} 0:00"
    rows: list[dict[str, object]] = []

    for _, row in board.iterrows():
        instrument = str(row.get("instrument", "")).strip()
        parts = instrument.split("-")
        if len(parts) != 3:
            continue
        contract_code, option_flag, strike_text = parts
        if contract_code != f"MO{end_month}":
            continue

        price = option_price_from_board_row(row)
        if price is None:
            continue

        try:
            strike = float(strike_text)
        except ValueError:
            continue

        option_type = option_flag.upper()
        if option_type == "C":
            exe_mode = CHINESE_CALL
        elif option_type == "P":
            exe_mode = CHINESE_PUT
        else:
            continue

        rows.append(
            {
                "trade_date": trade_date,
                "SEC_NAME": instrument,
                "EXE_MODE": exe_mode,
                "EXE_PRICE": strike,
                "EXE_ENDDATE": expiry_text,
                "CLOSE": price,
            }
        )

    if not rows:
        raise RuntimeError(f"normalized board is empty for {end_month}")
    options = pd.DataFrame(rows)
    return options.set_index("trade_date")[OPTION_COLUMNS]


def month_symbol_from_end_month(end_month: str) -> str:
    return f"mo{end_month}"


def contract_cache_path(symbol: str) -> Path:
    return CONTRACT_DIR / f"{symbol}.csv"


def fetch_zz1000_month_contracts(end_month: str) -> pd.DataFrame:
    month_symbol = month_symbol_from_end_month(end_month)
    board = ak.option_cffex_zz1000_spot_sina(symbol=month_symbol)
    if board.empty:
        raise RuntimeError(f"empty month board for {month_symbol}")
    result = board.copy()
    result["end_month"] = end_month
    return result


def fetch_zz1000_contract_daily(symbol: str, force_refresh: bool = False) -> pd.DataFrame:
    ensure_factor_dir()
    cache_path = contract_cache_path(symbol)
    if cache_path.exists() and not force_refresh:
        cached = pd.read_csv(cache_path)
        cached["date"] = pd.to_datetime(cached["date"], errors="coerce")
        return cached.dropna(subset=["date"]).sort_values("date").reset_index(drop=True)

    raw = ak.option_cffex_zz1000_daily_sina(symbol=symbol)
    history = raw.rename(columns={"date": "date", "close": "close"}).copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    history["close"] = pd.to_numeric(history["close"], errors="coerce")
    history = history.dropna(subset=["date", "close"]).sort_values("date").reset_index(drop=True)
    history.to_csv(cache_path, index=False, encoding="utf-8-sig")
    return history


def build_zz1000_legacy_option_history(end_months: list[str], start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for end_month in end_months:
        month_board = fetch_zz1000_month_contracts(end_month)
        expiry = cffex_month_expiry(end_month)
        expiry_text = f"{expiry.year}/{expiry.month:02d}/{expiry.day} 0:00"

        for _, board_row in month_board.iterrows():
            strike = pd.to_numeric(board_row["行权价"], errors="coerce")
            if pd.isna(strike):
                continue
            symbol_pairs = [
                (str(board_row["看涨合约-标识"]).strip(), CHINESE_CALL),
                (str(board_row["看跌合约-标识"]).strip(), CHINESE_PUT),
            ]
            for symbol, exe_mode in symbol_pairs:
                history = fetch_zz1000_contract_daily(symbol)
                history = history[(history["date"] >= start_date) & (history["date"] <= end_date)]
                if history.empty:
                    continue
                rows.extend(
                    {
                        "trade_date": trade_day.strftime("%Y/%m/%d"),
                        "SEC_NAME": symbol,
                        "EXE_MODE": exe_mode,
                        "EXE_PRICE": float(strike),
                        "EXE_ENDDATE": expiry_text,
                        "CLOSE": float(close),
                    }
                    for trade_day, close in zip(history["date"], history["close"])
                    if pd.notna(close) and float(close) > 0
                )

    if not rows:
        raise RuntimeError("no zz1000 legacy option history rows built")
    option_history = pd.DataFrame(rows).drop_duplicates(
        subset=["trade_date", "SEC_NAME", "EXE_MODE", "EXE_PRICE", "EXE_ENDDATE"],
        keep="last",
    )
    return option_history.set_index("trade_date")[OPTION_COLUMNS].sort_values(["EXE_ENDDATE", "EXE_PRICE", "EXE_MODE"])


def fetch_realtime_option_board(instrument_id: str, end_month: str) -> pd.DataFrame:
    instrument = INSTRUMENTS[instrument_id]
    board_symbol = instrument.get("ak_board_symbol")
    if not board_symbol:
        raise ValueError(f"{instrument_id} does not define a realtime board symbol")
    raw = ak.option_finance_board(symbol=board_symbol, end_month=end_month)
    if raw.empty:
        raise RuntimeError(f"{instrument_id} realtime board is empty for month {end_month}")
    contract_prefix = f"MO{end_month}-"
    if "instrument" in raw.columns:
        raw = raw[raw["instrument"].astype(str).str.startswith(contract_prefix)].copy()
    if raw.empty:
        raise RuntimeError(f"{instrument_id} realtime board has no contracts for exact month {end_month}")
    result = raw.copy()
    result["fetch_time"] = pd.Timestamp.now().strftime("%Y-%m-%d %H:%M:%S")
    result["instrument_id"] = instrument_id
    result["end_month"] = end_month
    return result


def probe_realtime_boards(instrument_id: str, months_ahead: int = 3) -> list[tuple[str, pd.DataFrame, Path]]:
    ensure_factor_dir()
    snapshots: list[tuple[str, pd.DataFrame, Path]] = []
    for end_month in infer_end_months(months_ahead=months_ahead):
        try:
            board = fetch_realtime_option_board(instrument_id, end_month)
        except Exception:
            continue
        snapshot_path = RAW_DIR / f"{instrument_id.lower()}_{end_month}_realtime.csv"
        board.to_csv(snapshot_path, index=False, encoding="utf-8-sig")
        snapshots.append((end_month, board, snapshot_path))
    if not snapshots:
        raise RuntimeError(f"no realtime boards fetched for {instrument_id}")
    return snapshots


def refresh_realtime_ivix_1000index(months_ahead: int = 4) -> dict[str, Any]:
    ensure_factor_dir()
    instrument_id = "1000INDEX"
    trade_date_ts = latest_trade_date()
    trade_date_text = trade_date_ts.strftime("%Y/%m/%d")

    normalized_boards: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    normalized_paths: list[str] = []

    for end_month in infer_end_months(base_date=trade_date_ts, months_ahead=months_ahead):
        try:
            board = fetch_realtime_option_board(instrument_id, end_month)
            raw_path = RAW_DIR / f"{instrument_id.lower()}_{end_month}_realtime.csv"
            board.to_csv(raw_path, index=False, encoding="utf-8-sig")
            raw_paths.append(raw_path.name)

            normalized = normalize_cffex_board_to_option_rows(board, trade_date=trade_date_text, end_month=end_month)
            normalized_path = RAW_DIR / f"{instrument_id.lower()}_{end_month}_normalized.csv"
            normalized.reset_index().to_csv(normalized_path, index=False, encoding="utf-8-sig")
            normalized_paths.append(normalized_path.name)
            normalized_boards.append(normalized)
        except Exception:
            continue

    if len(normalized_boards) < 2:
        raise RuntimeError("insufficient realtime option expiries for 1000INDEX; need at least near and next month")

    options = pd.concat(normalized_boards).sort_values(["EXE_ENDDATE", "EXE_PRICE", "EXE_MODE"])
    shibor = fetch_shibor_curve_history()
    ivix_value = cal_day_ivix(trade_date_text, options, shibor)

    output_path = FACTOR_DIR / INSTRUMENTS[instrument_id]["output_name"]
    if output_path.exists():
        history = read_instrument_history(instrument_id)
    else:
        history = fetch_qvix_history(instrument_id)

    history = history[history["date"] != trade_date_ts]
    realtime_row = pd.DataFrame(
        [
            {
                "date": trade_date_ts,
                "instrument_id": instrument_id,
                "ivix_close": ivix_value,
                "ivix_open": ivix_value,
                "ivix_high": ivix_value,
                "ivix_low": ivix_value,
                "source": "cffex:quote_MO.txt",
            }
        ]
    )
    updated = pd.concat([history, realtime_row], ignore_index=True).sort_values("date").reset_index(drop=True)
    format_date_column(updated).to_csv(output_path, index=False, encoding="utf-8-sig")
    return {
        "trade_date": trade_date_ts.strftime("%Y-%m-%d"),
        "ivix_close": float(ivix_value),
        "raw_paths": raw_paths,
        "normalized_paths": normalized_paths,
        "history_rows": len(updated),
    }


def refresh_realtime_ivix_50etf(months_ahead: int = 4) -> dict[str, Any]:
    ensure_factor_dir()
    instrument_id = "50ETF"
    trade_date_ts = latest_trade_date()
    trade_date_text = trade_date_ts.strftime("%Y/%m/%d")

    normalized_boards: list[pd.DataFrame] = []
    raw_paths: list[str] = []
    normalized_paths: list[str] = []

    for end_month in infer_end_months(base_date=trade_date_ts, months_ahead=months_ahead):
        try:
            board = fetch_sse_option_board(end_month)
            if board.empty:
                continue
            raw_path = RAW_DIR / f"{instrument_id.lower()}_{end_month}_realtime.csv"
            board.to_csv(raw_path, index=False, encoding="utf-8-sig")
            raw_paths.append(raw_path.name)

            normalized = _normalize_board_to_option_rows(board, trade_date=trade_date_text, end_month=end_month)
            normalized_path = RAW_DIR / f"{instrument_id.lower()}_{end_month}_normalized.csv"
            normalized.reset_index().to_csv(normalized_path, index=False, encoding="utf-8-sig")
            normalized_paths.append(normalized_path.name)
            normalized_boards.append(normalized)
        except Exception:
            continue

    if len(normalized_boards) < 2:
        raise RuntimeError("insufficient realtime option expiries for 50ETF; need at least near and next month")

    options = pd.concat(normalized_boards).sort_values(["EXE_ENDDATE", "EXE_PRICE", "EXE_MODE"])
    shibor = fetch_shibor_curve_history()
    ivix_value = cal_day_ivix(trade_date_text, options, shibor)

    output_path = FACTOR_DIR / INSTRUMENTS[instrument_id]["output_name"]
    if output_path.exists():
        history = read_instrument_history(instrument_id)
    else:
        history = fetch_qvix_history(instrument_id)

    history = history[history["date"] != trade_date_ts]
    realtime_row = pd.DataFrame(
        [
            {
                "date": trade_date_ts,
                "instrument_id": instrument_id,
                "ivix_close": ivix_value,
                "ivix_open": ivix_value,
                "ivix_high": ivix_value,
                "ivix_low": ivix_value,
                "source": "sina:sse_option_board",
            }
        ]
    )
    updated = pd.concat([history, realtime_row], ignore_index=True).sort_values("date").reset_index(drop=True)
    format_date_column(updated).to_csv(output_path, index=False, encoding="utf-8-sig")
    return {
        "trade_date": trade_date_ts.strftime("%Y-%m-%d"),
        "ivix_close": float(ivix_value),
        "raw_paths": raw_paths,
        "normalized_paths": normalized_paths,
        "history_rows": len(updated),
    }


def infer_missing_trade_dates(history: pd.DataFrame, start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[pd.Timestamp]:
    calendar_index = load_trade_calendar()
    target_calendar = calendar_index[(calendar_index >= start_date) & (calendar_index <= end_date)]
    existing_dates = set(pd.to_datetime(history["date"], errors="coerce").dropna().dt.normalize().tolist())
    return [pd.Timestamp(day).normalize() for day in target_calendar if pd.Timestamp(day).normalize() not in existing_dates]


def infer_relevant_end_months(start_date: pd.Timestamp, end_date: pd.Timestamp) -> list[str]:
    months: list[str] = []
    cursor = pd.Timestamp(year=start_date.year, month=start_date.month, day=1)
    last_month = pd.Timestamp(year=end_date.year, month=end_date.month, day=1) + pd.DateOffset(months=2)
    while cursor <= last_month:
        months.append(cursor.strftime("%y%m"))
        cursor = cursor + pd.DateOffset(months=1)
    return months


def infer_relevant_end_months_from_dates(dates: list[pd.Timestamp]) -> list[str]:
    months: set[str] = set()
    for trade_day in dates:
        month_anchor = pd.Timestamp(year=trade_day.year, month=trade_day.month, day=1)
        for offset in range(3):
            months.add((month_anchor + pd.DateOffset(months=offset)).strftime("%y%m"))
    return sorted(months)


def backfill_1000index_history_from_sina(start_date: str, end_date: str) -> dict[str, Any]:
    ensure_factor_dir()
    start_ts = pd.Timestamp(start_date).normalize()
    end_ts = pd.Timestamp(end_date).normalize()
    history = read_instrument_history("1000INDEX") if (FACTOR_DIR / INSTRUMENTS["1000INDEX"]["output_name"]).exists() else fetch_qvix_history("1000INDEX")
    missing_dates = infer_missing_trade_dates(history, start_ts, end_ts)
    if not missing_dates:
        return {"filled_rows": 0, "history_rows": len(history), "start_date": start_ts.strftime("%Y-%m-%d"), "end_date": end_ts.strftime("%Y-%m-%d")}

    end_months = infer_relevant_end_months_from_dates(missing_dates)
    option_history = build_zz1000_legacy_option_history(end_months, start_ts, end_ts)
    shibor = fetch_shibor_curve_history()

    filled_rows: list[dict[str, object]] = []
    for trade_day in missing_dates:
        trade_date_text = trade_day.strftime("%Y/%m/%d")
        try:
            day_options = option_history.loc[trade_date_text]
        except KeyError:
            continue
        day_frame = day_options if isinstance(day_options, pd.DataFrame) else day_options.to_frame().T
        exp_count = day_frame["EXE_ENDDATE"].nunique()
        if exp_count < 2:
            continue
        try:
            ivix_value = cal_day_ivix(trade_date_text, option_history, shibor)
        except Exception:
            continue
        filled_rows.append(
            {
                "date": trade_day,
                "instrument_id": "1000INDEX",
                "ivix_close": float(ivix_value),
                "ivix_open": float(ivix_value),
                "ivix_high": float(ivix_value),
                "ivix_low": float(ivix_value),
                "source": "sina:option_cffex_zz1000_daily_sina",
            }
        )

    if not filled_rows:
        raise RuntimeError("no missing 1000INDEX rows were filled from sina contract history")

    filled_df = pd.DataFrame(filled_rows)
    filled_snapshot = RAW_DIR / f"1000index_backfill_{start_ts.strftime('%Y%m%d')}_{end_ts.strftime('%Y%m%d')}.csv"
    format_date_column(filled_df).to_csv(filled_snapshot, index=False, encoding="utf-8-sig")

    history = history[~history["date"].isin(filled_df["date"])]
    updated = pd.concat([history, filled_df], ignore_index=True).sort_values("date").reset_index(drop=True)
    output_path = FACTOR_DIR / INSTRUMENTS["1000INDEX"]["output_name"]
    format_date_column(updated).to_csv(output_path, index=False, encoding="utf-8-sig")
    return {
        "filled_rows": len(filled_df),
        "history_rows": len(updated),
        "start_date": start_ts.strftime("%Y-%m-%d"),
        "end_date": end_ts.strftime("%Y-%m-%d"),
        "snapshot": filled_snapshot.name,
    }


def backfill_1000index_all_missing() -> dict[str, Any]:
    history = read_instrument_history("1000INDEX") if (FACTOR_DIR / INSTRUMENTS["1000INDEX"]["output_name"]).exists() else fetch_qvix_history("1000INDEX")
    start_ts = pd.Timestamp(INSTRUMENTS["1000INDEX"]["valid_start"]).normalize()
    end_ts = latest_trade_date() - pd.Timedelta(days=1)
    missing_dates = infer_missing_trade_dates(history, start_ts, end_ts)
    if not missing_dates:
        return {"filled_rows": 0, "history_rows": len(history), "start_date": start_ts.strftime("%Y-%m-%d"), "end_date": end_ts.strftime("%Y-%m-%d")}
    return backfill_1000index_history_from_sina(missing_dates[0].strftime("%Y-%m-%d"), missing_dates[-1].strftime("%Y-%m-%d"))


def refresh_realtime_dual(months_ahead_50: int = 4, months_ahead_1000: int = 4) -> tuple[dict[str, Any], dict[str, Any], pd.DataFrame, pd.DataFrame]:
    result_50 = refresh_realtime_ivix_50etf(months_ahead=months_ahead_50)
    result_1000 = refresh_realtime_ivix_1000index(months_ahead=months_ahead_1000)
    panel = run_build_panel()
    signals = run_build_signals()
    return result_50, result_1000, panel, signals


def read_instrument_history(instrument_id: str) -> pd.DataFrame:
    path = FACTOR_DIR / INSTRUMENTS[instrument_id]["output_name"]
    if not path.exists():
        raise FileNotFoundError(f"missing factor file: {path}")
    df = pd.read_csv(path)
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    for col in ["ivix_close", "ivix_open", "ivix_high", "ivix_low"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    return df.dropna(subset=["date", "ivix_close"]).sort_values("date").reset_index(drop=True)


def fetch_csi1000_index_history(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    raw = ak.stock_zh_index_hist_csindex(
        symbol="000852",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
    )
    if raw.empty:
        raise RuntimeError("CSI1000 index history is empty")

    result = raw.rename(columns={"日期": "date", "收盘": "csi1000_close"}).copy()
    result["date"] = pd.to_datetime(result["date"], errors="coerce")
    result["csi1000_close"] = pd.to_numeric(result["csi1000_close"], errors="coerce")
    result = result.dropna(subset=["date", "csi1000_close"])
    result = result.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
    return result[["date", "csi1000_close"]]


def fetch_csi1000_spot() -> pd.DataFrame:
    spot = ak.stock_zh_index_spot_sina()
    candidates = spot[spot["代码"].astype(str).isin(["sh000852", "sz399852"])].copy()
    if candidates.empty:
        raise RuntimeError("CSI1000 realtime spot not found in sina index spot")

    preferred = candidates[candidates["代码"].astype(str) == "sh000852"]
    if preferred.empty:
        preferred = candidates.iloc[[0]].copy()

    trade_date = latest_trade_date()
    close_price = pd.to_numeric(preferred.iloc[0]["最新价"], errors="coerce")
    open_price = pd.to_numeric(preferred.iloc[0]["今开"], errors="coerce")
    high_price = pd.to_numeric(preferred.iloc[0]["最高"], errors="coerce")
    low_price = pd.to_numeric(preferred.iloc[0]["最低"], errors="coerce")
    if pd.isna(close_price):
        raise RuntimeError("CSI1000 realtime spot price is empty")

    result = pd.DataFrame(
        [
            {
                "date": trade_date,
                "csi1000_open": float(open_price) if pd.notna(open_price) else float(close_price),
                "csi1000_high": float(high_price) if pd.notna(high_price) else float(close_price),
                "csi1000_low": float(low_price) if pd.notna(low_price) else float(close_price),
                "csi1000_close": float(close_price),
            }
        ]
    )
    snapshot_path = RAW_DIR / "csi1000_spot_latest.csv"
    result.to_csv(snapshot_path, index=False, encoding="utf-8-sig")
    return result[["date", "csi1000_close"]]


def build_dual_ivix_panel(ivix_50: pd.DataFrame, ivix_1000: pd.DataFrame) -> pd.DataFrame:
    panel = ivix_50[["date", "ivix_close"]].rename(columns={"ivix_close": "ivix_50"}).merge(
        ivix_1000[["date", "ivix_close"]].rename(columns={"ivix_close": "ivix_1000"}),
        on="date",
        how="inner",
    )
    panel = panel.sort_values("date").reset_index(drop=True)

    csi1000 = fetch_csi1000_index_history(panel["date"].min(), panel["date"].max())
    desired_latest = panel["date"].max()
    if not csi1000.empty and csi1000["date"].max() < desired_latest:
        try:
            spot = fetch_csi1000_spot()
            if not spot.empty and spot["date"].iloc[0] <= desired_latest:
                csi1000 = pd.concat([csi1000, spot], ignore_index=True)
                csi1000 = csi1000.sort_values("date").drop_duplicates(subset=["date"], keep="last").reset_index(drop=True)
        except Exception:
            pass
    panel = panel.merge(csi1000, on="date", how="left")

    panel["spread_1000_50"] = panel["ivix_1000"] - panel["ivix_50"]
    panel["ratio_1000_50"] = panel["ivix_1000"] / panel["ivix_50"]
    panel["z_20_spread"] = rolling_zscore(panel["spread_1000_50"], 20)
    panel["z_60_spread"] = rolling_zscore(panel["spread_1000_50"], 60)
    panel["z_60_ivix_1000"] = rolling_zscore(panel["ivix_1000"], 60)
    panel["d1_ivix_1000"] = panel["ivix_1000"].pct_change(fill_method=None)
    panel["d3_ivix_1000"] = panel["ivix_1000"].pct_change(periods=3, fill_method=None)
    panel = panel.replace([np.inf, -np.inf], np.nan)
    panel["ivix_1000_ma20"] = panel["ivix_1000"].rolling(20, min_periods=20).mean()
    panel["spread_ma20"] = panel["spread_1000_50"].rolling(20, min_periods=20).mean()
    panel["csi1000_ma5"] = panel["csi1000_close"].rolling(5, min_periods=5).mean()
    panel["csi1000_ma10"] = panel["csi1000_close"].rolling(10, min_periods=10).mean()
    panel["csi1000_ma20"] = panel["csi1000_close"].rolling(20, min_periods=20).mean()
    return panel


def build_signal_frame(panel: pd.DataFrame) -> pd.DataFrame:
    signals = panel.copy()

    panic_reversal = (signals["z_60_ivix_1000"] > 1.5) & (signals["d3_ivix_1000"] < -0.08)
    spread_revert = (
        (signals["z_60_spread"].shift(1) > 1.2)
        & (signals["spread_1000_50"].diff() < 0)
        & (signals["spread_1000_50"].diff().shift(1) < 0)
    )
    spread_revert_confirmed = spread_revert & (signals["csi1000_close"] > signals["csi1000_ma5"])

    s0_mask = (
        (signals["ivix_1000"] > signals["ivix_1000_ma20"])
        & (signals["spread_1000_50"] > 0)
        & (signals["z_60_spread"] > 0.8)
    )
    s2_mask = (
        (signals["ivix_1000"] < signals["ivix_1000_ma20"])
        & (signals["spread_1000_50"] < signals["spread_ma20"])
        & (signals["csi1000_close"] > signals["csi1000_ma20"])
    )
    ready_mask = signals[["ivix_1000_ma20", "spread_ma20", "csi1000_ma20"]].notna().all(axis=1)
    s1_mask = (~s0_mask) & (~s2_mask) & ready_mask

    regime_state = pd.Series(pd.NA, index=signals.index, dtype="object")
    regime_state.loc[s0_mask] = "S0"
    regime_state.loc[s2_mask] = "S2"
    regime_state.loc[s1_mask] = "S1"

    signals["signal_panic_reversal"] = panic_reversal.astype("Int64")
    signals["signal_spread_revert"] = spread_revert.astype("Int64")
    signals["signal_spread_revert_confirmed"] = spread_revert_confirmed.astype("Int64")
    signals["regime_state"] = regime_state
    signals["regime_equity_exposure"] = signals["regime_state"].map(
        {"S0": "20%", "S1": "50%", "S2": "80%-100%"}
    )
    return signals[
        [
            "date",
            "ivix_50",
            "ivix_1000",
            "spread_1000_50",
            "ratio_1000_50",
            "z_20_spread",
            "z_60_spread",
            "z_60_ivix_1000",
            "d1_ivix_1000",
            "d3_ivix_1000",
            "csi1000_close",
            "signal_panic_reversal",
            "signal_spread_revert",
            "signal_spread_revert_confirmed",
            "regime_state",
            "regime_equity_exposure",
        ]
    ]


def write_panel(panel: pd.DataFrame) -> None:
    ensure_factor_dir()
    format_date_column(panel).to_csv(PANEL_PATH, index=False, encoding="utf-8-sig")


def write_signals(signals: pd.DataFrame) -> None:
    ensure_factor_dir()
    format_date_column(signals).to_csv(SIGNAL_PATH, index=False, encoding="utf-8-sig")


def run_build_panel() -> pd.DataFrame:
    ivix_50 = read_instrument_history("50ETF")
    ivix_1000 = read_instrument_history("1000INDEX")
    panel = build_dual_ivix_panel(ivix_50, ivix_1000)
    write_panel(panel)
    return panel


def run_build_signals() -> pd.DataFrame:
    if not PANEL_PATH.exists():
        panel = run_build_panel()
    else:
        panel = pd.read_csv(PANEL_PATH)
        panel["date"] = pd.to_datetime(panel["date"], errors="coerce")
    signals = build_signal_frame(panel)
    write_signals(signals)
    return signals


def run_rebuild_all() -> tuple[dict[str, pd.DataFrame], pd.DataFrame, pd.DataFrame]:
    histories = sync_all()
    panel = run_build_panel()
    signals = run_build_signals()
    return histories, panel, signals


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Dual IVIX history, panel, and signal builder")
    subparsers = parser.add_subparsers(dest="command", required=True)

    sync_parser = subparsers.add_parser("sync", help="sync a single instrument history")
    sync_parser.add_argument("--instrument", choices=sorted(INSTRUMENTS.keys()), required=True)

    subparsers.add_parser("sync-all", help="sync all instrument histories")
    subparsers.add_parser("build-panel", help="build the dual IVIX factor panel")
    subparsers.add_parser("build-signals", help="build the dual IVIX signal file")
    subparsers.add_parser("rebuild-all", help="sync histories, build panel, and build signals")
    probe_parser = subparsers.add_parser("probe-realtime", help="fetch and save realtime option boards")
    probe_parser.add_argument("--instrument", choices=["1000INDEX"], required=True)
    probe_parser.add_argument("--months-ahead", type=int, default=3)
    realtime_50_parser = subparsers.add_parser("refresh-realtime-50", help="recalculate today's 50ETF IVIX from realtime boards")
    realtime_50_parser.add_argument("--months-ahead", type=int, default=4)
    realtime_parser = subparsers.add_parser("refresh-realtime-1000", help="recalculate today's 1000INDEX IVIX from MO realtime boards")
    realtime_parser.add_argument("--months-ahead", type=int, default=4)
    dual_parser = subparsers.add_parser("refresh-realtime-dual", help="refresh both realtime IVIX series and rebuild panel/signals")
    dual_parser.add_argument("--months-ahead-50", type=int, default=4)
    dual_parser.add_argument("--months-ahead-1000", type=int, default=4)
    backfill_parser = subparsers.add_parser("backfill-1000-sina", help="backfill missing 1000INDEX history from sina contract daily data")
    backfill_parser.add_argument("--start-date", required=True)
    backfill_parser.add_argument("--end-date", required=True)
    subparsers.add_parser("backfill-1000-all-missing", help="backfill all remaining missing 1000INDEX history rows")
    return parser


def print_sync_summary(histories: dict[str, pd.DataFrame]) -> None:
    for instrument_id, history in histories.items():
        latest = history.iloc[-1]
        print(
            f"{instrument_id}: rows={len(history)} latest={latest['date'].strftime('%Y-%m-%d')} "
            f"close={latest['ivix_close']:.4f}"
        )


def print_panel_summary(panel: pd.DataFrame) -> None:
    latest = panel.iloc[-1]
    print(
        "panel: "
        f"rows={len(panel)} latest={latest['date'].strftime('%Y-%m-%d')} "
        f"ivix_50={latest['ivix_50']:.4f} ivix_1000={latest['ivix_1000']:.4f} "
        f"spread={latest['spread_1000_50']:.4f}"
    )


def print_signal_summary(signals: pd.DataFrame) -> None:
    latest = signals.iloc[-1]
    panic_count = int(signals["signal_panic_reversal"].fillna(0).sum())
    spread_count = int(signals["signal_spread_revert"].fillna(0).sum())
    confirmed_count = int(signals["signal_spread_revert_confirmed"].fillna(0).sum())
    print(
        "signals: "
        f"rows={len(signals)} panic={panic_count} spread={spread_count} confirmed={confirmed_count} "
        f"latest_regime={latest['regime_state']}"
    )


def print_realtime_probe_summary(snapshots: list[tuple[str, pd.DataFrame, Path]]) -> None:
    for end_month, board, snapshot_path in snapshots:
        latest = board.iloc[0]
        print(
            f"realtime {end_month}: rows={len(board)} "
            f"sample={latest.get('instrument', 'N/A')} last={latest.get('lastprice', 'N/A')} "
            f"saved={snapshot_path.name}"
        )


def print_realtime_ivix_summary(instrument_id: str, result: dict[str, Any]) -> None:
    print(
        f"{instrument_id} realtime ivix: date={result['trade_date']} value={result['ivix_close']:.4f} "
        f"history_rows={result['history_rows']}"
    )
    print(f"raw snapshots: {', '.join(result['raw_paths'])}")
    print(f"normalized boards: {', '.join(result['normalized_paths'])}")


def print_backfill_summary(result: dict[str, Any]) -> None:
    print(
        f"1000INDEX backfill: range={result['start_date']} to {result['end_date']} "
        f"filled_rows={result['filled_rows']} history_rows={result['history_rows']}"
    )
    if "snapshot" in result:
        print(f"backfill snapshot: {result['snapshot']}")


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if args.command == "sync":
        history = sync_instrument(args.instrument)
        print_sync_summary({args.instrument: history})
        return

    if args.command == "sync-all":
        histories = sync_all()
        print_sync_summary(histories)
        return

    if args.command == "build-panel":
        panel = run_build_panel()
        print_panel_summary(panel)
        return

    if args.command == "build-signals":
        signals = run_build_signals()
        print_signal_summary(signals)
        return

    if args.command == "rebuild-all":
        histories, panel, signals = run_rebuild_all()
        print_sync_summary(histories)
        print_panel_summary(panel)
        print_signal_summary(signals)
        return

    if args.command == "probe-realtime":
        snapshots = probe_realtime_boards(args.instrument, months_ahead=args.months_ahead)
        print_realtime_probe_summary(snapshots)
        return

    if args.command == "refresh-realtime-50":
        result = refresh_realtime_ivix_50etf(months_ahead=args.months_ahead)
        print_realtime_ivix_summary("50ETF", result)
        return

    if args.command == "refresh-realtime-1000":
        result = refresh_realtime_ivix_1000index(months_ahead=args.months_ahead)
        print_realtime_ivix_summary("1000INDEX", result)
        return

    if args.command == "refresh-realtime-dual":
        result_50, result_1000, panel, signals = refresh_realtime_dual(
            months_ahead_50=args.months_ahead_50,
            months_ahead_1000=args.months_ahead_1000,
        )
        print_realtime_ivix_summary("50ETF", result_50)
        print_realtime_ivix_summary("1000INDEX", result_1000)
        print_panel_summary(panel)
        print_signal_summary(signals)
        return

    if args.command == "backfill-1000-sina":
        result = backfill_1000index_history_from_sina(args.start_date, args.end_date)
        print_backfill_summary(result)
        return

    if args.command == "backfill-1000-all-missing":
        result = backfill_1000index_all_missing()
        print_backfill_summary(result)
        return

    raise ValueError(f"unsupported command: {args.command}")


if __name__ == "__main__":
    main()
