from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parent
FACTOR_DIR = ROOT / "storage" / "factors"
PANEL_PATH = FACTOR_DIR / "ivix_dual_panel.csv"
SIGNAL_PATH = FACTOR_DIR / "ivix_signals.csv"
NAV_PATH = FACTOR_DIR / "ivix_strategy_backtest_nav.csv"
TRADES_PATH = FACTOR_DIR / "ivix_strategy_backtest_trades.csv"
SUMMARY_PATH = FACTOR_DIR / "ivix_strategy_backtest_summary.csv"
COMPARE_NAV_PATH = FACTOR_DIR / "ivix_strategy_compare_nav.csv"
COMPARE_TRADES_PATH = FACTOR_DIR / "ivix_strategy_compare_trades.csv"
COMPARE_SUMMARY_PATH = FACTOR_DIR / "ivix_strategy_compare_summary.csv"

REGIME_EXPOSURE = {"S0": 0.2, "S1": 0.5, "S2": 0.8}
COST_RATE = 0.0005
MIN_HOLD_DAYS = 5
MAX_HOLD_DAYS = 15


@dataclass
class StrategyState:
    in_position: bool = False
    exposure: float = 0.0
    holding_days: int = 0
    below_ma10_streak: int = 0
    entry_date: pd.Timestamp | None = None
    entry_price: float | None = None
    entry_regime: str | None = None
    max_exposure: float = 0.0


def load_frame() -> pd.DataFrame:
    panel = pd.read_csv(PANEL_PATH)
    signals = pd.read_csv(SIGNAL_PATH)
    frame = panel.merge(signals, on=["date", "ivix_50", "ivix_1000", "spread_1000_50", "ratio_1000_50", "z_20_spread", "z_60_spread", "z_60_ivix_1000", "d1_ivix_1000", "d3_ivix_1000", "csi1000_close"], how="left")
    frame["date"] = pd.to_datetime(frame["date"], errors="coerce")
    frame = frame.sort_values("date").reset_index(drop=True)
    frame["asset_ret"] = frame["csi1000_close"].pct_change(fill_method=None).fillna(0.0)
    frame["strategy_exposure"] = 0.0
    frame["turnover"] = 0.0
    frame["cost"] = 0.0
    frame["strategy_ret"] = 0.0
    frame["strategy_nav"] = 1.0
    frame["benchmark_nav"] = (1 + frame["asset_ret"]).cumprod()
    frame["trade_action"] = ""
    return frame


def annualized_return(nav: pd.Series) -> float:
    if len(nav) < 2:
        return float("nan")
    total_return = nav.iloc[-1] / nav.iloc[0] - 1
    years = len(nav) / 252.0
    if years <= 0:
        return float("nan")
    return (1 + total_return) ** (1 / years) - 1


def max_drawdown(nav: pd.Series) -> float:
    rolling_max = nav.cummax()
    drawdown = nav / rolling_max - 1
    return float(drawdown.min())


def simulate(include_panic_reversal: bool = False, strategy_name: str = "confirmed_spread") -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    frame = load_frame()
    start_mask = (
        frame["z_60_spread"].notna()
        & frame["csi1000_ma10"].notna()
        & frame["csi1000_ma20"].notna()
        & frame["regime_state"].notna()
    )
    first_valid_idx = int(start_mask.idxmax())
    frame = frame.iloc[first_valid_idx:].reset_index(drop=True)
    if not frame.empty:
        frame["benchmark_nav"] = frame["benchmark_nav"] / frame.loc[0, "benchmark_nav"]

    state = StrategyState()
    trade_records: list[dict[str, object]] = []

    for idx in range(len(frame)):
        row = frame.iloc[idx]
        frame.at[idx, "strategy_exposure"] = state.exposure
        turnover = 0.0

        if idx > 0:
            gross_ret = state.exposure * row["asset_ret"]
            frame.at[idx, "strategy_ret"] = gross_ret
            prev_nav = frame.at[idx - 1, "strategy_nav"]
            frame.at[idx, "strategy_nav"] = prev_nav * (1 + gross_ret)
        else:
            frame.at[idx, "strategy_nav"] = 1.0

        regime = row["regime_state"]
        regime_cap = REGIME_EXPOSURE.get(regime, 0.0)
        confirmed_entry = bool(row.get("signal_spread_revert_confirmed") == 1)
        panic_reversal = bool(row.get("signal_panic_reversal") == 1)
        entry_signal = confirmed_entry or (include_panic_reversal and panic_reversal)
        price_above_ma10 = bool(pd.notna(row["csi1000_ma10"]) and row["csi1000_close"] >= row["csi1000_ma10"])
        price_below_ma10 = bool(pd.notna(row["csi1000_ma10"]) and row["csi1000_close"] < row["csi1000_ma10"])
        spread_negative = bool(pd.notna(row["z_60_spread"]) and row["z_60_spread"] < 0)

        if price_below_ma10:
            state.below_ma10_streak += 1
        else:
            state.below_ma10_streak = 0

        next_exposure = state.exposure
        action = ""

        if not state.in_position:
            if entry_signal and regime in {"S0", "S1", "S2"} and regime_cap > 0:
                next_exposure = regime_cap
                state.in_position = True
                state.holding_days = 0
                state.entry_date = row["date"]
                state.entry_price = row["csi1000_close"]
                state.entry_regime = regime
                state.max_exposure = next_exposure
                action = "open"
        else:
            state.holding_days += 1

            if regime == "S2" and price_above_ma10 and state.exposure < 0.8:
                next_exposure = 0.8
                state.max_exposure = max(state.max_exposure, next_exposure)
                action = "add"
            elif regime == "S1" and state.exposure > 0.5:
                next_exposure = 0.5
                action = "reduce"
            elif regime == "S0" and state.exposure > 0.2:
                next_exposure = 0.2
                action = "reduce"

            if price_below_ma10 and state.exposure > 0.2 and state.holding_days >= MIN_HOLD_DAYS:
                next_exposure = min(next_exposure, 0.2)
                action = "reduce"

            clear_condition = (
                (state.holding_days >= MAX_HOLD_DAYS)
                or (spread_negative and state.holding_days >= MIN_HOLD_DAYS)
                or (state.below_ma10_streak >= 2 and state.holding_days >= MIN_HOLD_DAYS)
            )
            if clear_condition:
                next_exposure = 0.0
                action = "clear"

        if action:
            turnover = abs(next_exposure - state.exposure)
            frame.at[idx, "turnover"] = turnover
            frame.at[idx, "cost"] = turnover * COST_RATE
            frame.at[idx, "strategy_nav"] *= 1 - frame.at[idx, "cost"]
            frame.at[idx, "trade_action"] = action

        if action == "clear" and state.entry_date is not None and state.entry_price is not None:
            trade_records.append(
                {
                    "entry_date": state.entry_date.strftime("%Y-%m-%d"),
                    "exit_date": row["date"].strftime("%Y-%m-%d"),
                    "entry_price": state.entry_price,
                    "exit_price": row["csi1000_close"],
                    "entry_regime": state.entry_regime,
                    "max_exposure": state.max_exposure,
                    "holding_days": state.holding_days,
                    "trade_return": row["csi1000_close"] / state.entry_price - 1,
                    "strategy_name": strategy_name,
                    "entry_signal_set": "confirmed+panic" if include_panic_reversal else "confirmed_only",
                }
            )
            state = StrategyState()
        else:
            state.exposure = next_exposure

        if idx > 0 and frame.at[idx, "strategy_nav"] == 0:
            frame.at[idx, "strategy_nav"] = frame.at[idx - 1, "strategy_nav"]

    trades = pd.DataFrame(trade_records)

    daily_ret = frame["strategy_nav"].pct_change(fill_method=None).dropna()
    benchmark_ret = frame["benchmark_nav"].pct_change(fill_method=None).dropna()
    sharpe = float(np.sqrt(252) * daily_ret.mean() / daily_ret.std()) if len(daily_ret) > 1 and daily_ret.std() > 0 else float("nan")
    benchmark_sharpe = float(np.sqrt(252) * benchmark_ret.mean() / benchmark_ret.std()) if len(benchmark_ret) > 1 and benchmark_ret.std() > 0 else float("nan")

    summary = pd.DataFrame(
        [
            {"metric": "strategy_name", "value": strategy_name},
            {"metric": "entry_signal_set", "value": "confirmed+panic" if include_panic_reversal else "confirmed_only"},
            {"metric": "start_date", "value": frame.iloc[0]["date"].strftime("%Y-%m-%d")},
            {"metric": "end_date", "value": frame.iloc[-1]["date"].strftime("%Y-%m-%d")},
            {"metric": "rows", "value": len(frame)},
            {"metric": "strategy_total_return", "value": frame.iloc[-1]["strategy_nav"] - 1},
            {"metric": "strategy_annual_return", "value": annualized_return(frame["strategy_nav"])},
            {"metric": "strategy_max_drawdown", "value": max_drawdown(frame["strategy_nav"])},
            {"metric": "strategy_sharpe", "value": sharpe},
            {"metric": "benchmark_total_return", "value": frame.iloc[-1]["benchmark_nav"] - 1},
            {"metric": "benchmark_annual_return", "value": annualized_return(frame["benchmark_nav"])},
            {"metric": "benchmark_max_drawdown", "value": max_drawdown(frame["benchmark_nav"])},
            {"metric": "benchmark_sharpe", "value": benchmark_sharpe},
            {"metric": "trade_count", "value": len(trades)},
            {"metric": "trade_win_rate", "value": float((trades["trade_return"] > 0).mean()) if not trades.empty else float("nan")},
            {"metric": "avg_holding_days", "value": float(trades["holding_days"].mean()) if not trades.empty else float("nan")},
            {"metric": "avg_trade_return", "value": float(trades["trade_return"].mean()) if not trades.empty else float("nan")},
        ]
    )
    return frame, trades, summary


def main() -> None:
    baseline_frame, baseline_trades, baseline_summary = simulate(
        include_panic_reversal=False,
        strategy_name="confirmed_spread",
    )
    enhanced_frame, enhanced_trades, enhanced_summary = simulate(
        include_panic_reversal=True,
        strategy_name="confirmed_spread_plus_panic",
    )

    baseline_frame.to_csv(NAV_PATH, index=False, encoding="utf-8-sig")
    baseline_trades.to_csv(TRADES_PATH, index=False, encoding="utf-8-sig")
    baseline_summary.to_csv(SUMMARY_PATH, index=False, encoding="utf-8-sig")

    compare_nav = baseline_frame.loc[:, ["date", "benchmark_nav"]].copy()
    compare_nav["strategy_nav_confirmed"] = baseline_frame["strategy_nav"]
    compare_nav["strategy_nav_confirmed_plus_panic"] = enhanced_frame["strategy_nav"]
    compare_nav.to_csv(COMPARE_NAV_PATH, index=False, encoding="utf-8-sig")

    compare_trades = pd.concat([baseline_trades, enhanced_trades], ignore_index=True)
    compare_trades.to_csv(COMPARE_TRADES_PATH, index=False, encoding="utf-8-sig")

    baseline_map = dict(zip(baseline_summary["metric"], baseline_summary["value"]))
    enhanced_map = dict(zip(enhanced_summary["metric"], enhanced_summary["value"]))
    compare_summary = pd.DataFrame(
        [
            {
                "metric": "start_date",
                "confirmed_only": baseline_map["start_date"],
                "confirmed_plus_panic": enhanced_map["start_date"],
            },
            {
                "metric": "end_date",
                "confirmed_only": baseline_map["end_date"],
                "confirmed_plus_panic": enhanced_map["end_date"],
            },
            {
                "metric": "rows",
                "confirmed_only": baseline_map["rows"],
                "confirmed_plus_panic": enhanced_map["rows"],
            },
            {
                "metric": "strategy_total_return",
                "confirmed_only": baseline_map["strategy_total_return"],
                "confirmed_plus_panic": enhanced_map["strategy_total_return"],
            },
            {
                "metric": "strategy_annual_return",
                "confirmed_only": baseline_map["strategy_annual_return"],
                "confirmed_plus_panic": enhanced_map["strategy_annual_return"],
            },
            {
                "metric": "strategy_max_drawdown",
                "confirmed_only": baseline_map["strategy_max_drawdown"],
                "confirmed_plus_panic": enhanced_map["strategy_max_drawdown"],
            },
            {
                "metric": "strategy_sharpe",
                "confirmed_only": baseline_map["strategy_sharpe"],
                "confirmed_plus_panic": enhanced_map["strategy_sharpe"],
            },
            {
                "metric": "trade_count",
                "confirmed_only": baseline_map["trade_count"],
                "confirmed_plus_panic": enhanced_map["trade_count"],
            },
            {
                "metric": "trade_win_rate",
                "confirmed_only": baseline_map["trade_win_rate"],
                "confirmed_plus_panic": enhanced_map["trade_win_rate"],
            },
            {
                "metric": "avg_holding_days",
                "confirmed_only": baseline_map["avg_holding_days"],
                "confirmed_plus_panic": enhanced_map["avg_holding_days"],
            },
            {
                "metric": "avg_trade_return",
                "confirmed_only": baseline_map["avg_trade_return"],
                "confirmed_plus_panic": enhanced_map["avg_trade_return"],
            },
            {
                "metric": "benchmark_total_return",
                "confirmed_only": baseline_map["benchmark_total_return"],
                "confirmed_plus_panic": enhanced_map["benchmark_total_return"],
            },
            {
                "metric": "benchmark_annual_return",
                "confirmed_only": baseline_map["benchmark_annual_return"],
                "confirmed_plus_panic": enhanced_map["benchmark_annual_return"],
            },
            {
                "metric": "benchmark_max_drawdown",
                "confirmed_only": baseline_map["benchmark_max_drawdown"],
                "confirmed_plus_panic": enhanced_map["benchmark_max_drawdown"],
            },
            {
                "metric": "benchmark_sharpe",
                "confirmed_only": baseline_map["benchmark_sharpe"],
                "confirmed_plus_panic": enhanced_map["benchmark_sharpe"],
            },
        ]
    )
    compare_summary.to_csv(COMPARE_SUMMARY_PATH, index=False, encoding="utf-8-sig")

    print("confirmed_only")
    print(f"rows={int(float(baseline_map['rows']))}")
    print(f"period={baseline_map['start_date']} to {baseline_map['end_date']}")
    print(f"strategy_total_return={float(baseline_map['strategy_total_return']):.4f}")
    print(f"strategy_max_drawdown={float(baseline_map['strategy_max_drawdown']):.4f}")
    print(f"trade_count={int(float(baseline_map['trade_count']))}")
    print(f"trade_win_rate={float(baseline_map['trade_win_rate']):.4f}")
    print("confirmed_plus_panic")
    print(f"rows={int(float(enhanced_map['rows']))}")
    print(f"period={enhanced_map['start_date']} to {enhanced_map['end_date']}")
    print(f"strategy_total_return={float(enhanced_map['strategy_total_return']):.4f}")
    print(f"strategy_max_drawdown={float(enhanced_map['strategy_max_drawdown']):.4f}")
    print(f"trade_count={int(float(enhanced_map['trade_count']))}")
    print(f"trade_win_rate={float(enhanced_map['trade_win_rate']):.4f}")


if __name__ == "__main__":
    main()
