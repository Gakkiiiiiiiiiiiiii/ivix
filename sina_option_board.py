from __future__ import annotations

import re
from typing import List

import pandas as pd
import requests


_HEADERS = {
    "Accept": "*/*",
    "Referer": "https://stock.finance.sina.com.cn/",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
}

_DETAIL_RE = re.compile(r'^var hq_str_CON_OP_(\d+)="(.*)";$')
_SESSION = requests.Session()
_SESSION.trust_env = False
_SESSION.headers.update(_HEADERS)


def _request_text(url: str, params: dict | None = None) -> str:
    response = _SESSION.get(url, params=params, timeout=20)
    response.raise_for_status()
    return response.text


def list_option_months(symbol: str = "50ETF", exchange: str = "null") -> List[str]:
    text = _SESSION.get(
        "https://stock.finance.sina.com.cn/futures/api/openapi.php/StockOptionService.getStockName",
        params={"exchange": exchange, "cate": symbol},
        timeout=20,
    )
    text.raise_for_status()
    data_json = text.json()
    months = []
    for item in data_json["result"]["data"]["contractMonth"]:
        month = item.replace("-", "")
        if month not in months:
            months.append(month)
    return months


def _fetch_codes(direction: str, month_code: str, underlying: str = "510050") -> List[str]:
    text = _request_text(
        f"https://hq.sinajs.cn/list=OP_{direction}_{underlying}{month_code[-4:]}"
    )
    return [item[7:] for item in text.replace('"', ",").split(",") if item.startswith("CON_OP_")]


def fetch_sse_option_board(month_code: str, underlying: str = "510050") -> pd.DataFrame:
    full_month = month_code if len(month_code) == 6 else f"20{month_code}"
    if full_month not in list_option_months(symbol="50ETF"):
        return pd.DataFrame(
            columns=["EXE_PRICE", "call_name", "put_name", "call_latest", "put_latest", "expiry_date"]
        )

    call_codes = _fetch_codes("UP", full_month, underlying=underlying)
    put_codes = _fetch_codes("DOWN", full_month, underlying=underlying)
    detail_codes = sorted(set(call_codes + put_codes))
    if not detail_codes:
        return pd.DataFrame(
            columns=["EXE_PRICE", "call_name", "put_name", "call_latest", "put_latest", "expiry_date"]
        )

    detail_text = _request_text(
        "https://hq.sinajs.cn/list=" + ",".join(f"CON_OP_{code}" for code in detail_codes)
    )

    rows = []
    for raw_line in detail_text.splitlines():
        match = _DETAIL_RE.match(raw_line.strip())
        if not match:
            continue
        _, payload = match.groups()
        parts = payload.split(",")
        if len(parts) < 47:
            continue
        rows.append(
            {
                "EXE_PRICE": pd.to_numeric(parts[7], errors="coerce"),
                "latest": pd.to_numeric(parts[2], errors="coerce"),
                "contract_name": parts[37],
                "option_type": parts[45],
                "expiry_date": pd.to_datetime(parts[46], errors="coerce"),
            }
        )

    detail_df = pd.DataFrame(rows).dropna(subset=["EXE_PRICE", "latest", "expiry_date"])
    if detail_df.empty:
        return pd.DataFrame(
            columns=["EXE_PRICE", "call_name", "put_name", "call_latest", "put_latest", "expiry_date"]
        )

    calls = (
        detail_df[detail_df["option_type"] == "C"][
            ["EXE_PRICE", "contract_name", "latest", "expiry_date"]
        ]
        .rename(columns={"contract_name": "call_name", "latest": "call_latest"})
        .drop_duplicates(subset=["EXE_PRICE", "expiry_date"])
    )
    puts = (
        detail_df[detail_df["option_type"] == "P"][
            ["EXE_PRICE", "contract_name", "latest", "expiry_date"]
        ]
        .rename(columns={"contract_name": "put_name", "latest": "put_latest"})
        .drop_duplicates(subset=["EXE_PRICE", "expiry_date"])
    )
    board = calls.merge(puts, on=["EXE_PRICE", "expiry_date"], how="outer")
    return board.sort_values(["expiry_date", "EXE_PRICE"]).reset_index(drop=True)
