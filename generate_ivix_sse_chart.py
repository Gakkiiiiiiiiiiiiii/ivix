from __future__ import annotations

import html
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots
import akshare as ak


ROOT = Path(__file__).resolve().parent
FACTOR_DIR = ROOT / "storage" / "factors"
PANEL_PATH = FACTOR_DIR / "ivix_dual_panel.csv"
SIGNAL_PATH = FACTOR_DIR / "ivix_signals.csv"
IVIX_50_PATH = FACTOR_DIR / "ivix_50etf.csv"
IVIX_1000_PATH = FACTOR_DIR / "ivix_1000index.csv"
OUTPUT_PATH = ROOT / "vix.html"
CSI1000_SPOT_PATH = ROOT / "storage" / "raw" / "csi1000_spot_latest.csv"

PLOTLY_CONFIG = {
    "responsive": True,
    "displayModeBar": True,
    "scrollZoom": True,
    "displaylogo": False,
    "toImageButtonOptions": {"format": "png", "filename": "dual_ivix_dashboard", "scale": 2},
}

COLORS = {
    "bg": "#08131f",
    "panel": "#0d1c2d",
    "line50": "#ff875a",
    "line1000": "#59c6de",
    "price": "#dce6f2",
    "spread": "rgba(243,162,110,0.72)",
    "spread_z": "#ae9bff",
    "panic": "#36d9ae",
    "spread_sig": "#ffd06b",
    "confirm": "#67d6ff",
    "s0": "#ff875a",
    "s1": "#ffd06b",
    "s2": "#36d9ae",
    "text": "#e6eef8",
    "muted": "#a6b4c7",
    "grid": "rgba(230,238,248,0.10)",
    "axis": "rgba(230,238,248,0.18)",
}

REGIME_META = {
    "S0": ("S0 防守", "20%", "IVIX_1000 高于 MA20，Spread 偏高。"),
    "S1": ("S1 过渡", "50%", "恐慌在消退，但风格修复还没完全确认。"),
    "S2": ("S2 进攻", "80%-100%", "IVIX_1000 走弱，Spread 回到更健康区间。"),
}

SIGNAL_META = [
    ("signal_panic_reversal", "恐慌冲顶回落", "z60(IVIX_1000) > 1.5 且 3 日回落超过 8%"),
    ("signal_spread_revert", "Spread 收敛", "spread_z 前一日 > 1.2，且 spread 连续两天下降"),
    ("signal_spread_revert_confirmed", "Spread 收敛+价格确认", "Spread 收敛基础上，中证1000 收盘站上 MA5"),
]


def fmt_num(value: object, digits: int = 2) -> str:
    return "N/A" if pd.isna(value) else f"{float(value):.{digits}f}"


def fmt_pct(value: object, digits: int = 1) -> str:
    return "N/A" if pd.isna(value) else f"{float(value) * 100:.{digits}f}%"


def load_csi1000_history(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    raw = ak.stock_zh_index_hist_csindex(
        symbol="000852",
        start_date=start_date.strftime("%Y%m%d"),
        end_date=end_date.strftime("%Y%m%d"),
    )
    history = raw.rename(
        columns={"日期": "date", "开盘": "csi1000_open", "最高": "csi1000_high", "最低": "csi1000_low", "收盘": "csi1000_close"}
    )[["date", "csi1000_open", "csi1000_high", "csi1000_low", "csi1000_close"]].copy()
    history["date"] = pd.to_datetime(history["date"], errors="coerce")
    for col in ["csi1000_open", "csi1000_high", "csi1000_low", "csi1000_close"]:
        history[col] = pd.to_numeric(history[col], errors="coerce")
    history = history.dropna().sort_values("date").drop_duplicates(subset=["date"], keep="last")
    if CSI1000_SPOT_PATH.exists():
        spot = pd.read_csv(CSI1000_SPOT_PATH)
        spot["date"] = pd.to_datetime(spot["date"], errors="coerce")
        for col in ["csi1000_open", "csi1000_high", "csi1000_low", "csi1000_close"]:
            if col in spot.columns:
                spot[col] = pd.to_numeric(spot[col], errors="coerce")
        spot = spot.dropna().sort_values("date").drop_duplicates(subset=["date"], keep="last")
        history = pd.concat([history, spot], ignore_index=True).sort_values("date").drop_duplicates(subset=["date"], keep="last")
    return history[(history["date"] >= start_date) & (history["date"] <= end_date)].reset_index(drop=True)


def load_frame() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    panel = pd.read_csv(PANEL_PATH)
    signals = pd.read_csv(SIGNAL_PATH)
    ivix_50 = pd.read_csv(IVIX_50_PATH)
    ivix_1000 = pd.read_csv(IVIX_1000_PATH)
    for df in [panel, signals, ivix_50, ivix_1000]:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    factor_frame = panel.merge(
        signals[["date", "signal_panic_reversal", "signal_spread_revert", "signal_spread_revert_confirmed", "regime_state", "regime_equity_exposure"]],
        on="date",
        how="left",
    ).sort_values("date")
    price_frame = load_csi1000_history(factor_frame["date"].min(), factor_frame["date"].max())
    ivix_50_chart = ivix_50.rename(columns={"ivix_close": "ivix_50"})[["date", "ivix_50"]]
    ivix_1000_chart = ivix_1000.rename(columns={"ivix_close": "ivix_1000"})[["date", "ivix_1000"]]
    frame = price_frame.merge(ivix_50_chart, on="date", how="left").merge(ivix_1000_chart, on="date", how="left")
    factor_for_chart = factor_frame.drop(columns=["csi1000_close", "ivix_50", "ivix_1000"], errors="ignore")
    frame = frame.merge(factor_for_chart, on="date", how="left").sort_values("date")
    frame["ret_5d_fwd"] = frame["csi1000_close"].shift(-5) / frame["csi1000_close"] - 1
    frame["ret_10d_fwd"] = frame["csi1000_close"].shift(-10) / frame["csi1000_close"] - 1
    frame["ret_20d_fwd"] = frame["csi1000_close"].shift(-20) / frame["csi1000_close"] - 1
    frame["regime_code"] = frame["regime_state"].map({"S0": 0, "S1": 1, "S2": 2})
    frame["trade_buy"] = 0
    frame["trade_sell"] = 0
    frame["position_state"] = 0
    in_position = False
    holding_days = 0
    min_hold_days = 5
    max_hold_days = 15
    for idx, row in frame.iterrows():
        entry_signal = bool((row.get("signal_spread_revert_confirmed") == 1) or (row.get("signal_panic_reversal") == 1))
        soft_exit = bool(
            pd.notna(row.get("csi1000_close"))
            and pd.notna(row.get("csi1000_ma10"))
            and pd.notna(row.get("z_60_spread"))
            and float(row.get("csi1000_close")) < float(row.get("csi1000_ma10"))
            and float(row.get("z_60_spread")) < 0.2
        )
        hard_exit = bool(
            pd.notna(row.get("z_60_spread"))
            and float(row.get("z_60_spread")) < -0.5
            and pd.notna(row.get("ivix_1000"))
            and pd.notna(row.get("ivix_1000_ma20"))
            and float(row.get("ivix_1000")) < float(row.get("ivix_1000_ma20"))
        )
        if (not in_position) and entry_signal:
            frame.at[idx, "trade_buy"] = 1
            frame.at[idx, "position_state"] = 1
            in_position = True
            holding_days = 1
            continue
        if in_position:
            frame.at[idx, "position_state"] = 1
            holding_days += 1
            if (holding_days >= min_hold_days and (soft_exit or hard_exit)) or holding_days >= max_hold_days:
                frame.at[idx, "trade_sell"] = 1
                in_position = False
                holding_days = 0
    return frame.reset_index(drop=True), factor_frame.reset_index(drop=True), ivix_50.sort_values("date").reset_index(drop=True), ivix_1000.sort_values("date").reset_index(drop=True)


def signal_stats(frame: pd.DataFrame, column: str) -> dict[str, object]:
    sample = frame.loc[frame[column] == 1, ["ret_5d_fwd", "ret_10d_fwd", "ret_20d_fwd"]].dropna()
    if sample.empty:
        return {"count": 0, "ret5": np.nan, "ret10": np.nan, "ret20": np.nan, "up20": np.nan}
    return {
        "count": int(len(sample)),
        "ret5": float(sample["ret_5d_fwd"].mean()),
        "ret10": float(sample["ret_10d_fwd"].mean()),
        "ret20": float(sample["ret_20d_fwd"].mean()),
        "up20": float((sample["ret_20d_fwd"] > 0).mean()),
    }


def build_main_figure(frame: pd.DataFrame) -> go.Figure:
    fig = make_subplots(rows=4, cols=1, shared_xaxes=True, vertical_spacing=0.045, row_heights=[0.35, 0.25, 0.24, 0.16], specs=[[{}], [{}], [{"secondary_y": True}], [{}]])
    fig.add_trace(
        go.Candlestick(
            x=frame["date"],
            open=frame["csi1000_open"],
            high=frame["csi1000_high"],
            low=frame["csi1000_low"],
            close=frame["csi1000_close"],
            name="CSI1000 K线",
            increasing_line_color="#f97316",
            decreasing_line_color="#60a5fa",
            increasing_fillcolor="#f97316",
            decreasing_fillcolor="#60a5fa",
            hovertemplate="日期=%{x|%Y-%m-%d}<br>开=%{open:.2f}<br>高=%{high:.2f}<br>低=%{low:.2f}<br>收=%{close:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
    )
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["csi1000_close"].rolling(5, min_periods=5).mean(), mode="lines", name="MA5", line={"color": "#facc15", "width": 1.4}), row=1, col=1)
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["csi1000_close"].rolling(10, min_periods=10).mean(), mode="lines", name="MA10", line={"color": "#a78bfa", "width": 1.4}), row=1, col=1)
    marker_specs = [
        ("signal_panic_reversal", "恐慌回落", COLORS["panic"], "triangle-up"),
        ("signal_spread_revert", "Spread 收敛", COLORS["spread_sig"], "diamond"),
        ("signal_spread_revert_confirmed", "收敛+确认", COLORS["confirm"], "star"),
    ]
    for column, label, color, symbol in marker_specs:
        sample = frame.loc[frame[column] == 1]
        fig.add_trace(go.Scatter(x=sample["date"], y=sample["csi1000_close"], mode="markers", name=label, marker={"color": color, "size": 7, "symbol": symbol, "opacity": 0.45}), row=1, col=1)
    buy_sample = frame.loc[frame["trade_buy"] == 1]
    sell_sample = frame.loc[frame["trade_sell"] == 1]
    buy_dates = buy_sample["date"].tolist()
    sell_dates = sell_sample["date"].tolist()
    pair_count = min(len(buy_dates), len(sell_dates))
    for buy_dt, sell_dt in zip(buy_dates[:pair_count], sell_dates[:pair_count]):
        if sell_dt <= buy_dt:
            continue
        fig.add_vrect(
            x0=buy_dt,
            x1=sell_dt,
            fillcolor="rgba(34,197,94,0.12)",
            line_width=0,
            layer="below",
            row=1,
            col=1,
        )
    fig.add_trace(
        go.Scatter(
            x=buy_sample["date"],
            y=buy_sample["csi1000_low"] * 0.985,
            mode="markers+text",
            text=["B" for _ in range(len(buy_sample))],
            textposition="bottom center",
            name="买点",
            marker={"color": "#22c55e", "size": 16, "symbol": "triangle-up", "line": {"width": 1.5, "color": "#06110a"}},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(
        go.Scatter(
            x=sell_sample["date"],
            y=sell_sample["csi1000_high"] * 1.015,
            mode="markers+text",
            text=["S" for _ in range(len(sell_sample))],
            textposition="top center",
            name="卖点",
            marker={"color": "#ef4444", "size": 16, "symbol": "triangle-down", "line": {"width": 1.5, "color": "#170606"}},
        ),
        row=1,
        col=1,
    )
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["ivix_50"], mode="lines", name="IVIX_50", line={"color": COLORS["line50"], "width": 2.4}), row=2, col=1)
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["ivix_1000"], mode="lines", name="IVIX_1000", line={"color": COLORS["line1000"], "width": 2.4}), row=2, col=1)
    fig.add_trace(go.Bar(x=frame["date"], y=frame["spread_1000_50"], name="Spread", marker={"color": COLORS["spread"]}), row=3, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["z_60_spread"], mode="lines", name="Spread Z60", line={"color": COLORS["spread_z"], "width": 2.0}), row=3, col=1, secondary_y=True)
    fig.add_trace(go.Scatter(x=frame["date"], y=frame["regime_code"], mode="lines+markers", name="Regime", line={"color": COLORS["axis"], "shape": "hv"}, marker={"size": 8, "color": frame["regime_state"].map({"S0": COLORS["s0"], "S1": COLORS["s1"], "S2": COLORS["s2"]}).fillna(COLORS["axis"])}), row=4, col=1)
    fig.update_layout(
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=COLORS["panel"],
        font={"family": "Segoe UI, Microsoft YaHei, sans-serif", "color": COLORS["text"]},
        hoverlabel={"bgcolor": "#f8fafc", "font": {"color": "#08131f"}},
        legend={"orientation": "h", "y": 1.02, "x": 0.01},
        margin={"l": 70, "r": 70, "t": 40, "b": 40},
        xaxis_rangeslider_visible=False,
    )
    for row in [1, 2, 3, 4]:
        fig.update_yaxes(showgrid=True, gridcolor=COLORS["grid"], linecolor=COLORS["axis"], row=row, col=1)
    fig.update_xaxes(showgrid=False, linecolor=COLORS["axis"], tickformat="%Y-%m", row=4, col=1)
    fig.update_yaxes(title_text="CSI1000", row=1, col=1)
    fig.update_yaxes(title_text="IVIX", row=2, col=1)
    fig.update_yaxes(title_text="Spread", row=3, col=1, secondary_y=False)
    fig.update_yaxes(title_text="Z60", row=3, col=1, secondary_y=True)
    fig.update_yaxes(title_text="Regime", tickmode="array", tickvals=[0, 1, 2], ticktext=["S0", "S1", "S2"], row=4, col=1)
    return fig


def build_research_figure(frame: pd.DataFrame) -> go.Figure:
    regime_x = ["S0 防守", "S1 过渡", "S2 进攻"]
    regime_mean = [frame.loc[frame["regime_state"] == code, "ret_20d_fwd"].dropna().mean() for code in ["S0", "S1", "S2"]]
    regime_up = [(frame.loc[frame["regime_state"] == code, "ret_20d_fwd"].dropna() > 0).mean() for code in ["S0", "S1", "S2"]]
    sig_stats = [signal_stats(frame, column) for column, _, _ in SIGNAL_META]
    fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.12, specs=[[{"secondary_y": True}, {"secondary_y": True}]])
    fig.add_trace(go.Bar(x=regime_x, y=regime_mean, name="Regime 平均未来20日", marker={"color": [COLORS["s0"], COLORS["s1"], COLORS["s2"]]}), row=1, col=1, secondary_y=False)
    fig.add_trace(go.Scatter(x=regime_x, y=regime_up, mode="lines+markers", name="Regime 20日上涨概率", line={"color": COLORS["line1000"], "width": 2.2}), row=1, col=1, secondary_y=True)
    fig.add_trace(go.Bar(x=[label for _, label, _ in SIGNAL_META], y=[item["ret20"] for item in sig_stats], name="信号平均未来20日", marker={"color": [COLORS["panic"], COLORS["spread_sig"], COLORS["confirm"]]}), row=1, col=2, secondary_y=False)
    fig.add_trace(go.Scatter(x=[label for _, label, _ in SIGNAL_META], y=[item["up20"] for item in sig_stats], mode="lines+markers", name="信号20日上涨概率", line={"color": COLORS["line50"], "width": 2.2}), row=1, col=2, secondary_y=True)
    fig.update_layout(paper_bgcolor="rgba(0,0,0,0)", plot_bgcolor=COLORS["panel"], font={"family": "Segoe UI, Microsoft YaHei, sans-serif", "color": COLORS["text"]}, hoverlabel={"bgcolor": "#f8fafc", "font": {"color": "#08131f"}}, legend={"orientation": "h", "y": 1.04, "x": 0.01}, margin={"l": 60, "r": 60, "t": 50, "b": 40})
    for col in [1, 2]:
        fig.update_xaxes(showgrid=False, linecolor=COLORS["axis"], row=1, col=col)
        fig.update_yaxes(showgrid=True, gridcolor=COLORS["grid"], linecolor=COLORS["axis"], tickformat=".0%", row=1, col=col, secondary_y=False)
        fig.update_yaxes(showgrid=False, linecolor=COLORS["axis"], tickformat=".0%", row=1, col=col, secondary_y=True)
    return fig


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{html.escape(item)}</th>" for item in headers)
    body = "".join("<tr>" + "".join(f"<td>{html.escape(cell)}</td>" for cell in row) + "</tr>" for row in rows)
    return f"<div class='table-wrap'><table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"


def render_html(frame: pd.DataFrame, factor_frame: pd.DataFrame, ivix_50: pd.DataFrame, ivix_1000: pd.DataFrame, main_html: str, research_html: str) -> str:
    latest = factor_frame.iloc[-1]
    latest_price = frame.iloc[-1]
    latest_50 = ivix_50.iloc[-1]
    latest_1000 = ivix_1000.iloc[-1]
    today = pd.Timestamp.today().normalize()
    lag_days = int((latest_50["date"] - latest_1000["date"]).days)
    stale_days = int((today - latest_1000["date"]).days)
    regime_title, exposure, regime_detail = REGIME_META.get(latest["regime_state"], ("Warm-up", "N/A", "滚动窗口尚未就绪。"))
    cards = [
        ("双 IVIX 因子最新日期", latest["date"].strftime("%Y-%m-%d"), "价格线使用完整 CSI1000 日线，因子与信号按日期左连接。"),
        ("CSI1000 价格最新", f"{latest_price['date'].strftime('%Y-%m-%d')} / {fmt_num(latest_price['csi1000_close'])}", "价格轴不再受 IVIX 缺口挤压。"),
        ("50ETF 最新", f"{latest_50['date'].strftime('%Y-%m-%d')} / {fmt_num(latest_50['ivix_close'])}", "系统性风险锚。"),
        ("1000INDEX 最新", f"{latest_1000['date'].strftime('%Y-%m-%d')} / {fmt_num(latest_1000['ivix_close'])}", "小盘风险偏好放大器。"),
        ("最新 Spread", fmt_num(latest["spread_1000_50"]), f"Ratio {fmt_num(latest['ratio_1000_50'], 3)}"),
        ("Spread Z60", fmt_num(latest["z_60_spread"]), "风格恐慌溢价偏离程度。"),
        ("当前 Regime", regime_title, f"建议权益仓位 {exposure}"),
    ]
    card_html = "".join(f"<article class='card'><div class='label'>{html.escape(a)}</div><div class='value'>{html.escape(b)}</div><div class='detail'>{html.escape(c)}</div></article>" for a, b, c in cards)
    sig_rows = []
    for column, label, rule in SIGNAL_META:
        stats = signal_stats(frame, column)
        sig_rows.append([label, rule, str(stats["count"]), fmt_pct(stats["ret5"]), fmt_pct(stats["ret10"]), fmt_pct(stats["ret20"]), fmt_pct(stats["up20"])])
    recent_rows = []
    for column, label, _ in SIGNAL_META:
        sample = frame.loc[frame[column] == 1, ["date", "ivix_50", "ivix_1000", "spread_1000_50", "z_60_spread", "ret_20d_fwd"]].sort_values("date", ascending=False).head(4)
        for _, row in sample.iterrows():
            recent_rows.append([row["date"].strftime("%Y-%m-%d"), label, fmt_num(row["ivix_50"]), fmt_num(row["ivix_1000"]), fmt_num(row["spread_1000_50"]), fmt_num(row["z_60_spread"]), fmt_pct(row["ret_20d_fwd"])])
    recent_rows = sorted(recent_rows, key=lambda x: x[0], reverse=True)[:12]
    regime_rows = []
    for code in ["S0", "S1", "S2"]:
        sample = frame.loc[frame["regime_state"] == code, "ret_20d_fwd"].dropna()
        regime_rows.append([REGIME_META[code][0], str(int((frame["regime_state"] == code).sum())), fmt_pct(sample.mean() if not sample.empty else np.nan), fmt_pct((sample > 0).mean() if not sample.empty else np.nan), REGIME_META[code][1]])
    return f"""<!DOCTYPE html><html lang='zh-CN'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'><title>Dual IVIX Dashboard</title><style>
body{{margin:0;font-family:'Segoe UI','Microsoft YaHei',sans-serif;background:radial-gradient(circle at 0 0, rgba(255,135,90,.16), transparent 28%),radial-gradient(circle at 100% 0, rgba(89,198,222,.14), transparent 30%),{COLORS["bg"]};color:{COLORS["text"]};}}
.shell{{max-width:1460px;margin:0 auto;padding:28px 20px 40px;}}
.panel{{background:{COLORS["panel"]};border:1px solid rgba(255,255,255,.08);border-radius:24px;padding:22px;box-shadow:0 22px 60px rgba(0,0,0,.26);}}
.hero{{display:grid;grid-template-columns:1.3fr .9fr;gap:18px;margin-bottom:18px;}}
.eyebrow,.detail,.subtitle,.footer,p,.signal-rule{{color:{COLORS["muted"]};}}
.eyebrow{{font-size:12px;letter-spacing:.18em;text-transform:uppercase;margin-bottom:12px;}}
h1{{font-size:clamp(34px,4vw,58px);line-height:.94;letter-spacing:-.04em;margin:0 0 12px;max-width:11ch;}}
.copy{{font-size:16px;line-height:1.7;color:{COLORS["muted"]};max-width:60ch;}}
.note{{border-left:4px solid {COLORS["line50"]};padding-left:14px;font-size:14px;line-height:1.7;color:{COLORS["muted"]};}}
.cards{{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:18px 0;}}
.card{{background:linear-gradient(180deg, rgba(255,255,255,.06), rgba(255,255,255,.03));border:1px solid rgba(255,255,255,.08);border-radius:20px;padding:18px;min-height:130px;}}
.label{{font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:{COLORS["muted"]};margin-bottom:12px;}}
.value{{font-size:26px;line-height:1.05;margin-bottom:10px;font-weight:700;}}
.subtitle{{font-size:14px;line-height:1.6;margin-bottom:14px;}}
.two-col,.tables{{display:grid;grid-template-columns:1.25fr .75fr;gap:18px;margin-top:18px;}}
.signal-card{{padding:16px 18px;border-radius:18px;background:linear-gradient(135deg, rgba(255,255,255,.06), rgba(255,255,255,.02));border:1px solid rgba(255,255,255,.08);margin-bottom:12px;}}
.signal-title{{font-size:18px;margin-bottom:8px;font-weight:700;}}
.table-wrap{{overflow-x:auto;}} table{{width:100%;border-collapse:collapse;font-size:13px;}} th,td{{padding:12px 10px;text-align:left;white-space:nowrap;border-bottom:1px solid rgba(255,255,255,.08);}} th{{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:{COLORS["muted"]};}}
.footer{{margin-top:18px;font-size:13px;}}
@media (max-width:1080px){{.hero,.cards,.two-col,.tables{{grid-template-columns:1fr;}} h1{{max-width:none;}}}}
</style></head><body><main class='shell'>
<section class='hero'><section class='panel'><div class='eyebrow'>Dual IVIX Research Console</div><h1>50ETF 做风险锚，1000INDEX 看风格温度。</h1><div class='copy'>页面直接读取双 IVIX 面板和信号文件。上面看中证1000价格与信号触发点，中间看 IVIX_50 / IVIX_1000 与 Spread，下面看 Regime 和信号在未来 20 个交易日里的统计表现。</div></section><section class='panel'><div class='note'>当前 1000INDEX 历史日线 QVIX 使用的上游源，在本地核验时从 2026-03-16 起返回 #NAME?，所以最新有效值停在 {latest_1000['date'].strftime('%Y-%m-%d')}。如果你要拿到 2026-03-26 的 1000INDEX IVIX，必须改走实时期权板并按公式自行重算，而不是继续依赖这条历史日线源。</div></section></section>
<section class='cards'>{card_html}</section>
<section class='panel'><div class='value' style='font-size:24px;margin-bottom:10px;'>CSI1000 K线 / Dual IVIX / Spread / Regime</div><div class='subtitle'>主图已改成 K 线。绿色上箭头是聚合买点，红色下箭头是对应退出点；其它彩色标记保留原始信号触发。价格线使用完整 CSI1000 日线，IVIX 缺口则按真实情况断线显示。</div>{main_html}</section>
<section class='two-col'><section class='panel'><div class='value' style='font-size:24px;margin-bottom:10px;'>Research Cuts</div><div class='subtitle'>左边看 Regime 的未来 20 日表现，右边看三类信号的未来 20 日表现。</div>{research_html}</section><section class='panel'><div class='value' style='font-size:24px;margin-bottom:10px;'>Rules & Reading</div>
<div class='signal-card'><div class='signal-title'>恐慌冲顶回落</div><div class='signal-rule'>z60(IVIX_1000) > 1.5 且 3 日回落超过 8%</div></div>
<div class='signal-card'><div class='signal-title'>Spread 收敛</div><div class='signal-rule'>spread_z 前一日 > 1.2，且 spread 连续两天下降</div></div>
<div class='signal-card'><div class='signal-title'>Spread 收敛+价格确认</div><div class='signal-rule'>Spread 收敛基础上，中证1000 收盘站上 MA5</div></div>
<p>{html.escape(regime_detail)}</p>{render_table(["状态", "样本数", "平均未来20日", "20日上涨概率", "建议权益仓位"], regime_rows)}</section></section>
<section class='tables'><section class='panel'><div class='value' style='font-size:24px;margin-bottom:10px;'>Signal Stats</div><div class='subtitle'>观察对象统一使用中证1000价格。</div>{render_table(["信号", "规则", "样本数", "未来5日", "未来10日", "未来20日", "20日上涨概率"], sig_rows)}</section><section class='panel'><div class='value' style='font-size:24px;margin-bottom:10px;'>Recent Trigger Log</div><div class='subtitle'>最近触发样本，方便直接回看时点。</div>{render_table(["日期", "信号", "IVIX_50", "IVIX_1000", "Spread", "Spread Z60", "未来20日"], recent_rows)}</section></section>
<section class='footer'>数据摘要：价格序列 {len(frame)} 行；双 IVIX 因子行数 {len(factor_frame)}；恐慌回落 {int(frame['signal_panic_reversal'].fillna(0).sum())} 次；Spread 收敛 {int(frame['signal_spread_revert'].fillna(0).sum())} 次；收敛+价格确认 {int(frame['signal_spread_revert_confirmed'].fillna(0).sum())} 次；当前状态 {html.escape(regime_title)}。</section>
</main></body></html>"""


def main() -> None:
    frame, factor_frame, ivix_50, ivix_1000 = load_frame()
    main_html = pio.to_html(build_main_figure(frame), include_plotlyjs="cdn", full_html=False, config=PLOTLY_CONFIG)
    research_html = pio.to_html(build_research_figure(frame), include_plotlyjs=False, full_html=False, config=PLOTLY_CONFIG)
    OUTPUT_PATH.write_text(render_html(frame, factor_frame, ivix_50, ivix_1000, main_html, research_html), encoding="utf-8")
    print(f"generated chart: {OUTPUT_PATH}")
    print(f"price rows: {len(frame)}")
    print(f"factor rows: {len(factor_frame)}")
    print(f"latest factor date: {factor_frame.iloc[-1]['date'].strftime('%Y-%m-%d')}")
    print(f"latest regime: {factor_frame.iloc[-1]['regime_state']}")


if __name__ == "__main__":
    main()
