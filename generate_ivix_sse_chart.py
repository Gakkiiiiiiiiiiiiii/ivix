from __future__ import annotations

import html
import json
from pathlib import Path
import urllib.parse
import urllib.request

import pandas as pd
import plotly.graph_objects as go
import plotly.io as pio
from plotly.subplots import make_subplots


ROOT = Path(__file__).resolve().parent
IVIX_PATH = ROOT / "ivix.csv"
TRADEDAY_PATH = ROOT / "tradeday.csv"
SSE_CACHE_PATH = ROOT / "shanghai_index.csv"
OUTPUT_PATH = ROOT / "vix.html"
MIN_MISSING_TRADING_DAYS_TO_ANNOTATE = 4

PLOTLY_CONFIG = {
    "responsive": True,
    "displayModeBar": True,
    "scrollZoom": True,
    "displaylogo": False,
    "toImageButtonOptions": {
        "format": "png",
        "filename": "ivix_sse_dashboard",
        "scale": 2,
    },
}

THEMES = {
    "light": {
        "chart_plot_bg": "rgba(255,250,244,0.76)",
        "chart_font": "#13263D",
        "grid": "rgba(19,38,61,0.06)",
        "axis_line": "rgba(19,38,61,0.16)",
        "hover_bg": "rgba(18,28,45,0.96)",
        "hover_font": "#F8F5EF",
        "legend_bg": "rgba(255,250,244,0.60)",
        "annotation_bg": "rgba(255,250,244,0.96)",
        "annotation_border": "rgba(17,34,64,0.12)",
        "annotation_font": "#4B5B73",
        "ivix_line": "#D76A3D",
        "ivix_fill": "rgba(215,106,61,0.14)",
        "sse_line": "#2D7FB8",
        "buy_marker": "#0E9F6E",
        "buy_marker_line": "#ECFFF7",
        "sell_marker": "#D89A24",
        "sell_marker_line": "#FFF8E6",
        "rank_line": "#6B4EFF",
        "rank_fill": "rgba(107,78,255,0.08)",
        "fear_band": "rgba(215,106,61,0.10)",
        "calm_band": "rgba(45,127,184,0.10)",
        "mid_line": "rgba(19,38,61,0.20)",
        "bar_low": "#2D7FB8",
        "bar_high": "#D76A3D",
        "bar_pos": "#4E8772",
        "bar_neg": "#76869A",
    },
    "dark": {
        "chart_plot_bg": "rgba(10,18,30,0.88)",
        "chart_font": "#E7EDF7",
        "grid": "rgba(231,237,247,0.08)",
        "axis_line": "rgba(231,237,247,0.16)",
        "hover_bg": "rgba(248,250,252,0.98)",
        "hover_font": "#0B1220",
        "legend_bg": "rgba(10,18,30,0.68)",
        "annotation_bg": "rgba(13,24,38,0.96)",
        "annotation_border": "rgba(255,255,255,0.10)",
        "annotation_font": "#B8C5D7",
        "ivix_line": "#FF8A5B",
        "ivix_fill": "rgba(255,138,91,0.20)",
        "sse_line": "#6BB8FF",
        "buy_marker": "#2BD4A4",
        "buy_marker_line": "#081914",
        "sell_marker": "#FFBF5C",
        "sell_marker_line": "#2B1B08",
        "rank_line": "#9C89FF",
        "rank_fill": "rgba(156,137,255,0.16)",
        "fear_band": "rgba(255,138,91,0.12)",
        "calm_band": "rgba(107,184,255,0.10)",
        "mid_line": "rgba(231,237,247,0.22)",
        "bar_low": "#6BB8FF",
        "bar_high": "#FF8A5B",
        "bar_pos": "#2BD4A4",
        "bar_neg": "#7E8DA3",
    },
}

SIGNAL_SPECS = [
    {
        "column": "buy_candidate",
        "label": "买点候选",
        "short_rule": "高分位恐慌 + 价格短跌过冲 + IVIX 开始回落",
        "tone": "buy",
    },
    {
        "column": "sell_candidate",
        "label": "卖点候选",
        "short_rule": "低波动上冲 + 低分位滞留",
        "tone": "sell",
    },
]


def load_ivix_history() -> pd.DataFrame:
    ivix_df = pd.read_csv(IVIX_PATH)
    tradeday_df = pd.read_csv(TRADEDAY_PATH)

    if "DateTime" not in ivix_df.columns:
        ivix_df["DateTime"] = pd.NA

    date_series = ivix_df["DateTime"].copy()
    missing_mask = date_series.isna() | (date_series.astype(str).str.strip() == "")
    missing_count = int(missing_mask.sum())

    tradedays = tradeday_df["DateTime"].astype(str).tolist()
    if missing_count > len(tradedays):
        raise ValueError("tradeday.csv does not contain enough dates to align ivix.csv")

    if missing_count:
        date_series.loc[missing_mask] = tradedays[:missing_count]

    result = pd.DataFrame(
        {
            "Date": pd.to_datetime(date_series, format="%Y/%m/%d", errors="coerce"),
            "IVIX": pd.to_numeric(ivix_df["value"], errors="coerce"),
        }
    ).dropna()
    result = result.sort_values("Date").drop_duplicates(subset=["Date"], keep="last")
    return result.reset_index(drop=True)


def fetch_sse_history(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    params = urllib.parse.urlencode(
        {
            "secid": "1.000001",
            "fields1": "f1,f2,f3,f4,f5,f6",
            "fields2": "f51,f52,f53,f54,f55,f56,f57,f58",
            "klt": "101",
            "fqt": "0",
            "beg": start_date.strftime("%Y%m%d"),
            "end": end_date.strftime("%Y%m%d"),
        },
    )
    request = urllib.request.Request(
        "https://push2his.eastmoney.com/api/qt/stock/kline/get?" + params,
        headers={
            "User-Agent": "Mozilla/5.0",
            "Referer": "https://quote.eastmoney.com/",
            "Connection": "close",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        data_json = json.loads(response.read().decode("utf-8"))
    klines = data_json["data"]["klines"]

    rows = []
    for line in klines:
        parts = line.split(",")
        rows.append({"Date": pd.to_datetime(parts[0]), "SSE Close": float(parts[2])})

    result = pd.DataFrame(rows).sort_values("Date").reset_index(drop=True)
    result.to_csv(SSE_CACHE_PATH, index=False, encoding="utf-8-sig")
    return result


def load_cached_sse_history() -> pd.DataFrame:
    if not SSE_CACHE_PATH.exists():
        raise FileNotFoundError(f"SSE cache not found: {SSE_CACHE_PATH}")

    cached = pd.read_csv(SSE_CACHE_PATH)
    result = pd.DataFrame(
        {
            "Date": pd.to_datetime(cached["Date"], errors="coerce"),
            "SSE Close": pd.to_numeric(cached["SSE Close"], errors="coerce"),
        }
    ).dropna()
    return result.sort_values("Date").drop_duplicates(subset=["Date"], keep="last").reset_index(drop=True)


def load_sse_history(start_date: pd.Timestamp, end_date: pd.Timestamp) -> pd.DataFrame:
    cached = None
    if SSE_CACHE_PATH.exists():
        cached = load_cached_sse_history()
        if not cached.empty:
            cache_min = cached["Date"].min()
            cache_max = cached["Date"].max()
            if cache_min <= start_date and cache_max >= end_date:
                return cached[(cached["Date"] >= start_date) & (cached["Date"] <= end_date)].reset_index(drop=True)

    try:
        return fetch_sse_history(start_date, end_date)
    except Exception:
        if cached is not None and not cached.empty:
            return cached[(cached["Date"] >= start_date) & (cached["Date"] <= end_date)].reset_index(drop=True)
        raise


def prepare_analysis_frame(ivix_df: pd.DataFrame, sse_df: pd.DataFrame) -> pd.DataFrame:
    frame = sse_df.rename(columns={"SSE Close": "SSE"}).merge(ivix_df, on="Date", how="left")
    frame = frame.sort_values("Date").reset_index(drop=True)

    frame["sse_ret_1d"] = frame["SSE"].pct_change(fill_method=None)
    frame["ivix_ret_1d"] = frame["IVIX"].pct_change(fill_method=None)
    frame["ivix_delta"] = frame["IVIX"].diff()
    frame["sse_ret_5d_back"] = frame["SSE"] / frame["SSE"].shift(5) - 1
    frame["sse_ret_20d_back"] = frame["SSE"] / frame["SSE"].shift(20) - 1
    frame["sse_ret_5d_fwd"] = frame["SSE"].shift(-5) / frame["SSE"] - 1
    frame["sse_ret_10d_fwd"] = frame["SSE"].shift(-10) / frame["SSE"] - 1
    frame["sse_ret_20d_fwd"] = frame["SSE"].shift(-20) / frame["SSE"] - 1

    frame["ivix_ma20"] = frame["IVIX"].rolling(20, min_periods=20).mean()
    frame["ivix_std20"] = frame["IVIX"].rolling(20, min_periods=20).std()
    frame["ivix_z20"] = (frame["IVIX"] - frame["ivix_ma20"]) / frame["ivix_std20"]
    frame["ivix_rank_252"] = frame["IVIX"].rolling(252, min_periods=60).rank(pct=True)
    frame["ivix_rank_pct"] = frame["ivix_rank_252"] * 100
    frame["corr_60"] = frame["ivix_ret_1d"].rolling(60, min_periods=30).corr(frame["sse_ret_1d"])
    frame["buy_setup"] = (
        (frame["ivix_rank_252"] >= 0.85)
        & (frame["ivix_z20"] >= 1.0)
        & (frame["sse_ret_5d_back"] <= -0.03)
    ).fillna(False)
    frame["buy_candidate"] = (
        frame["buy_setup"]
        & (frame["ivix_ret_1d"] < 0)
    ).fillna(False)
    frame["sell_setup"] = (
        (frame["ivix_rank_252"] <= 0.25)
        & (frame["ivix_z20"] <= 0)
        & (frame["sse_ret_5d_back"] >= 0.03)
    ).fillna(False)
    frame["sell_candidate"] = frame["sell_setup"]
    frame["signal_tag"] = pd.NA
    frame.loc[frame["buy_candidate"], "signal_tag"] = "B"
    frame.loc[frame["sell_candidate"], "signal_tag"] = "S"
    return frame


def calculate_signal_stats(frame: pd.DataFrame, mask: pd.Series) -> dict[str, float]:
    sample = frame.loc[mask, ["sse_ret_5d_fwd", "sse_ret_10d_fwd", "sse_ret_20d_fwd"]].dropna()
    if sample.empty:
        return {
            "count": 0,
            "mean_5d": float("nan"),
            "mean_10d": float("nan"),
            "mean_20d": float("nan"),
            "up_20d": float("nan"),
            "down_20d": float("nan"),
        }

    return {
        "count": int(len(sample)),
        "mean_5d": float(sample["sse_ret_5d_fwd"].mean()),
        "mean_10d": float(sample["sse_ret_10d_fwd"].mean()),
        "mean_20d": float(sample["sse_ret_20d_fwd"].mean()),
        "up_20d": float((sample["sse_ret_20d_fwd"] > 0).mean()),
        "down_20d": float((sample["sse_ret_20d_fwd"] < 0).mean()),
    }


def build_signal_summary_rows(frame: pd.DataFrame) -> list[dict[str, str]]:
    latest = frame.iloc[-1]
    rows = []
    for spec in SIGNAL_SPECS:
        mask = frame[spec["column"]]
        stats = calculate_signal_stats(frame, mask)
        last_date = frame.loc[mask, "Date"].max() if bool(mask.any()) else pd.NaT
        rows.append(
            {
                "label": spec["label"],
                "rule": spec["short_rule"],
                "count": str(stats["count"]),
                "mean_5d": format_percent(stats["mean_5d"]),
                "mean_10d": format_percent(stats["mean_10d"]),
                "mean_20d": format_percent(stats["mean_20d"]),
                "up_20d": format_percent(stats["up_20d"], digits=1, signed=False),
                "down_20d": format_percent(stats["down_20d"], digits=1, signed=False),
                "last_date": last_date.strftime("%Y/%m/%d") if pd.notna(last_date) else "--",
                "status": "触发中" if bool(latest[spec["column"]]) else "未触发",
                "status_class": "status-live" if bool(latest[spec["column"]]) else "status-idle",
                "tone": spec["tone"],
            }
        )
    return rows


def build_recent_signal_rows(frame: pd.DataFrame, limit: int = 12) -> list[dict[str, str]]:
    event_frames = []
    for spec in SIGNAL_SPECS:
        event_frame = frame.loc[
            frame[spec["column"]],
            [
                "Date",
                "SSE",
                "IVIX",
                "ivix_rank_pct",
                "ivix_z20",
                "sse_ret_5d_back",
                "sse_ret_20d_fwd",
            ],
        ].copy()
        if event_frame.empty:
            continue
        event_frame["signal_label"] = spec["label"]
        event_frame["tone"] = spec["tone"]
        event_frames.append(event_frame)

    if not event_frames:
        return []

    events = pd.concat(event_frames, ignore_index=True).sort_values("Date", ascending=False).head(limit)
    rows = []
    for _, row in events.iterrows():
        rows.append(
            {
                "date": row["Date"].strftime("%Y/%m/%d"),
                "label": row["signal_label"],
                "tone": row["tone"],
                "sse": format_value(row["SSE"]),
                "ivix": format_value(row["IVIX"]),
                "rank": format_percent(row["ivix_rank_pct"] / 100.0, digits=1, signed=False),
                "z20": format_value(row["ivix_z20"]),
                "back_5d": format_percent(row["sse_ret_5d_back"]),
                "fwd_20d": format_percent(row["sse_ret_20d_fwd"]) if pd.notna(row["sse_ret_20d_fwd"]) else "观测中",
            }
        )
    return rows


def format_value(value: float, digits: int = 2) -> str:
    if pd.isna(value):
        return "--"
    return f"{value:.{digits}f}"


def format_percent(value: float, digits: int = 2, signed: bool = True) -> str:
    if pd.isna(value):
        return "--"
    sign = "+" if signed else ""
    return f"{value * 100:{sign}.{digits}f}%"


def classify_current_regime(latest: pd.Series) -> dict[str, str]:
    rank_pct = latest.get("ivix_rank_pct")
    pullback_20d = latest.get("sse_ret_20d_back")

    if bool(latest.get("buy_candidate", False)):
        return {
            "title": "买点候选触发",
            "detail": "高分位恐慌与短线急跌同时出现，且 IVIX 开始回落，历史上更接近情绪释放后的反抽窗口。",
            "tone": "warm",
        }
    if bool(latest.get("sell_candidate", False)):
        return {
            "title": "卖点候选触发",
            "detail": "低波动叠加短线拉升，市场更容易从顺风状态切到钝化回撤，适合做保护和减仓观察。",
            "tone": "cool",
        }
    if pd.notna(rank_pct) and rank_pct >= 70 and pd.notna(pullback_20d) and pullback_20d < 0:
        return {
            "title": "防御升温",
            "detail": "IVIX 位于较高分位，但还没到极端恐慌。通常代表市场开始防守，不等于立即见底。",
            "tone": "warm",
        }
    if pd.notna(rank_pct) and rank_pct <= 30 and pd.notna(pullback_20d) and pullback_20d > 0:
        return {
            "title": "情绪偏暖",
            "detail": "低波动配合指数走强，趋势往往更平顺，但也要提防过热后的钝化。",
            "tone": "cool",
        }
    return {
        "title": "中性过渡",
        "detail": "IVIX 不在极端区间，单看波动水平难以判定反转，需结合价格结构与成交量。",
        "tone": "neutral",
    }


def add_ivix_gap_annotation(figure: go.Figure, analysis_frame: pd.DataFrame, theme: dict[str, str]) -> None:
    missing_mask = analysis_frame["IVIX"].isna()
    if not missing_mask.any():
        return

    ordered = analysis_frame.sort_values("Date").reset_index(drop=True)
    state_change = missing_mask.ne(missing_mask.shift(fill_value=False)).cumsum()
    missing_runs = []
    for _, group in ordered.groupby(state_change):
        if pd.isna(group["IVIX"]).all():
            missing_runs.append((int(group.index[0]), int(group.index[-1]), len(group)))

    if not missing_runs:
        return

    start_idx, end_idx, missing_days = max(missing_runs, key=lambda item: item[2])
    if missing_days < MIN_MISSING_TRADING_DAYS_TO_ANNOTATE:
        return

    prev_date = ordered.loc[start_idx - 1, "Date"].strftime("%Y/%m/%d") if start_idx > 0 else ordered.loc[start_idx, "Date"].strftime("%Y/%m/%d")
    next_date = ordered.loc[end_idx + 1, "Date"].strftime("%Y/%m/%d") if end_idx + 1 < len(ordered) else ordered.loc[end_idx, "Date"].strftime("%Y/%m/%d")
    figure.add_annotation(
        xref="paper",
        yref="paper",
        x=0.01,
        y=1.07,
        xanchor="left",
        yanchor="bottom",
        showarrow=False,
        align="left",
        bgcolor=theme["annotation_bg"],
        bordercolor=theme["annotation_border"],
        borderwidth=1,
        font={"size": 11, "color": theme["annotation_font"]},
        text=f"IVIX 数据缺口：{prev_date} 到 {next_date}（缺少 {missing_days} 个交易日）",
    )


def build_main_figure(frame: pd.DataFrame, theme_name: str) -> go.Figure:
    theme = THEMES[theme_name]
    buy_points = frame.loc[frame["buy_candidate"] & frame["SSE"].notna()]
    sell_points = frame.loc[frame["sell_candidate"] & frame["SSE"].notna()]

    figure = make_subplots(
        rows=2,
        cols=1,
        shared_xaxes=True,
        vertical_spacing=0.08,
        row_heights=[0.72, 0.28],
        specs=[[{"secondary_y": True}], [{"secondary_y": False}]],
    )

    figure.add_trace(
        go.Scatter(
            x=frame["Date"],
            y=frame["IVIX"],
            mode="lines",
            name="IVIX",
            connectgaps=False,
            line={"color": theme["ivix_line"], "width": 2.6},
            fill="tozeroy",
            fillcolor=theme["ivix_fill"],
            hovertemplate="日期=%{x|%Y/%m/%d}<br>IVIX=%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=frame["Date"],
            y=frame["SSE"],
            mode="lines",
            name="上证指数",
            line={"color": theme["sse_line"], "width": 2.4},
            hovertemplate="日期=%{x|%Y/%m/%d}<br>上证指数=%{y:.2f}<extra></extra>",
        ),
        row=1,
        col=1,
        secondary_y=True,
    )

    if not buy_points.empty:
        figure.add_trace(
            go.Scatter(
                x=buy_points["Date"],
                y=buy_points["SSE"],
                mode="markers+text",
                text=["B"] * len(buy_points),
                textposition="top center",
                textfont={"size": 9, "color": theme["buy_marker"]},
                name="买点候选",
                marker={
                    "symbol": "diamond",
                    "size": 11,
                    "color": theme["buy_marker"],
                    "line": {"color": theme["buy_marker_line"], "width": 1.2},
                },
                hovertemplate="日期=%{x|%Y/%m/%d}<br>上证指数=%{y:.2f}<br>信号=买点候选<extra></extra>",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    if not sell_points.empty:
        figure.add_trace(
            go.Scatter(
                x=sell_points["Date"],
                y=sell_points["SSE"],
                mode="markers+text",
                text=["S"] * len(sell_points),
                textposition="bottom center",
                textfont={"size": 9, "color": theme["sell_marker"]},
                name="卖点候选",
                marker={
                    "symbol": "triangle-down",
                    "size": 11,
                    "color": theme["sell_marker"],
                    "line": {"color": theme["sell_marker_line"], "width": 1.2},
                },
                hovertemplate="日期=%{x|%Y/%m/%d}<br>上证指数=%{y:.2f}<br>信号=卖点候选<extra></extra>",
            ),
            row=1,
            col=1,
            secondary_y=True,
        )

    figure.add_trace(
        go.Scatter(
            x=frame["Date"],
            y=frame["ivix_rank_pct"],
            mode="lines",
            name="IVIX 近252日分位",
            line={"color": theme["rank_line"], "width": 2},
            fill="tozeroy",
            fillcolor=theme["rank_fill"],
            hovertemplate="日期=%{x|%Y/%m/%d}<br>IVIX 分位=%{y:.1f}%<extra></extra>",
            showlegend=False,
        ),
        row=2,
        col=1,
    )

    figure.add_hrect(
        y0=85,
        y1=100,
        line_width=0,
        fillcolor=theme["fear_band"],
        row=2,
        col=1,
    )
    figure.add_hrect(
        y0=0,
        y1=25,
        line_width=0,
        fillcolor=theme["calm_band"],
        row=2,
        col=1,
    )
    figure.add_hline(y=50, line_dash="dot", line_color=theme["mid_line"], row=2, col=1)

    figure.update_layout(
        template="none",
        height=920,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=theme["chart_plot_bg"],
        dragmode="zoom",
        hovermode="x unified",
        margin={"l": 70, "r": 70, "t": 40, "b": 40},
        legend={
            "orientation": "h",
            "yanchor": "bottom",
            "y": 1.03,
            "xanchor": "left",
            "x": 0,
            "font": {"size": 12},
            "bgcolor": theme["legend_bg"],
        },
        font={
            "family": '"Avenir Next", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
            "size": 13,
            "color": theme["chart_font"],
        },
        hoverlabel={
            "bgcolor": theme["hover_bg"],
            "bordercolor": theme["axis_line"],
            "font": {"color": theme["hover_font"], "size": 12},
        },
    )

    figure.update_xaxes(
        showgrid=True,
        gridcolor=theme["grid"],
        linecolor=theme["axis_line"],
        showspikes=True,
        spikecolor=theme["axis_line"],
        spikethickness=1,
        spikesnap="cursor",
        spikemode="across",
        tickformat="%Y/%m/%d",
        hoverformat="%Y/%m/%d",
    )
    figure.update_xaxes(
        title_text="日期",
        rangeslider={
            "visible": True,
            "thickness": 0.08,
            "bgcolor": theme["calm_band"],
            "bordercolor": theme["axis_line"],
            "borderwidth": 1,
        },
        rangeselector={
            "buttons": [
                {"count": 3, "label": "3M", "step": "month", "stepmode": "backward"},
                {"count": 6, "label": "6M", "step": "month", "stepmode": "backward"},
                {"count": 1, "label": "1Y", "step": "year", "stepmode": "backward"},
                {"count": 3, "label": "3Y", "step": "year", "stepmode": "backward"},
                {"step": "all", "label": "ALL"},
            ],
            "bgcolor": theme["legend_bg"],
            "activecolor": theme["chart_font"],
            "font": {"color": theme["annotation_font"]},
            "x": 0,
            "y": 1.12,
        },
        row=2,
        col=1,
    )
    figure.update_yaxes(
        title_text="IVIX",
        showgrid=True,
        gridcolor=theme["grid"],
        zeroline=False,
        row=1,
        col=1,
        secondary_y=False,
    )
    figure.update_yaxes(
        title_text="上证指数",
        showgrid=False,
        zeroline=False,
        row=1,
        col=1,
        secondary_y=True,
    )
    figure.update_yaxes(
        title_text="IVIX 近252日分位 (%)",
        range=[0, 100],
        ticksuffix="%",
        showgrid=True,
        gridcolor=theme["grid"],
        zeroline=False,
        row=2,
        col=1,
    )

    add_ivix_gap_annotation(figure, frame, theme)
    return figure


def build_regime_figure(frame: pd.DataFrame, theme_name: str) -> go.Figure:
    theme = THEMES[theme_name]
    stats_frame = frame.dropna(subset=["ivix_rank_252", "sse_ret_20d_fwd"]).copy()
    bucket_edges = [i / 10 for i in range(11)]
    bucket_labels = [f"{i * 10:02d}-{(i + 1) * 10:02d}%" for i in range(10)]
    stats_frame["bucket"] = pd.cut(
        stats_frame["ivix_rank_252"],
        bins=bucket_edges,
        labels=bucket_labels,
        include_lowest=True,
    )
    grouped = stats_frame.groupby("bucket", observed=False).agg(
        mean_20d_fwd=("sse_ret_20d_fwd", "mean"),
        up_20d=("sse_ret_20d_fwd", lambda series: (series > 0).mean()),
    )
    grouped = grouped.reset_index()

    bar_colors = []
    for idx, value in enumerate(grouped["mean_20d_fwd"]):
        if idx <= 1:
            bar_colors.append(theme["bar_low"])
        elif idx >= 8:
            bar_colors.append(theme["bar_high"])
        else:
            bar_colors.append(theme["bar_neg"] if pd.notna(value) and value < 0 else theme["bar_pos"])

    figure = make_subplots(specs=[[{"secondary_y": True}]])
    figure.add_trace(
        go.Bar(
            x=grouped["bucket"],
            y=grouped["mean_20d_fwd"] * 100,
            name="未来20日平均收益",
            marker={"color": bar_colors, "line": {"color": theme["axis_line"], "width": 1}},
            text=[f"{value:.2f}%" for value in grouped["mean_20d_fwd"].fillna(0) * 100],
            textposition="outside",
            hovertemplate="IVIX 分位=%{x}<br>未来20日平均收益=%{y:.2f}%<extra></extra>",
        ),
        secondary_y=False,
    )
    figure.add_trace(
        go.Scatter(
            x=grouped["bucket"],
            y=grouped["up_20d"] * 100,
            mode="lines+markers",
            name="未来20日上涨概率",
            line={"color": theme["rank_line"], "width": 2.4},
            marker={"size": 8, "color": theme["rank_line"]},
            hovertemplate="IVIX 分位=%{x}<br>未来20日上涨概率=%{y:.1f}%<extra></extra>",
        ),
        secondary_y=True,
    )
    figure.add_hline(y=0, line_dash="dot", line_color=theme["mid_line"], secondary_y=False)
    figure.update_layout(
        template="none",
        height=360,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor=theme["chart_plot_bg"],
        margin={"l": 56, "r": 56, "t": 24, "b": 36},
        legend={"orientation": "h", "y": 1.08, "x": 0},
        font={
            "family": '"Avenir Next", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif',
            "size": 12,
            "color": theme["chart_font"],
        },
        hoverlabel={
            "bgcolor": theme["hover_bg"],
            "bordercolor": theme["axis_line"],
            "font": {"color": theme["hover_font"], "size": 12},
        },
    )
    figure.update_xaxes(title_text="IVIX 近252日分位桶", showgrid=False)
    figure.update_yaxes(title_text="未来20日平均收益", ticksuffix="%", secondary_y=False)
    figure.update_yaxes(title_text="未来20日上涨概率", ticksuffix="%", range=[0, 100], secondary_y=True)
    return figure


def build_dashboard_context(frame: pd.DataFrame) -> dict[str, object]:
    usable = frame.dropna(subset=["IVIX"]).copy()
    latest = usable.iloc[-1]
    daily_corr = usable[["ivix_ret_1d", "sse_ret_1d"]].dropna().corr().iloc[0, 1]
    median_roll_corr = usable["corr_60"].dropna().median()

    buy_stats = calculate_signal_stats(usable, usable["buy_candidate"])
    sell_stats = calculate_signal_stats(usable, usable["sell_candidate"])
    current_regime = classify_current_regime(latest)
    signal_summary_rows = build_signal_summary_rows(usable)
    recent_signal_rows = build_recent_signal_rows(usable)

    metrics = [
        {
            "label": "最新 IVIX",
            "value": format_value(latest["IVIX"]),
            "detail": latest["Date"].strftime("%Y/%m/%d"),
        },
        {
            "label": "年内分位",
            "value": format_percent(latest["ivix_rank_252"], digits=1, signed=False),
            "detail": "近 252 个交易日位置",
        },
        {
            "label": "上证近20日",
            "value": format_percent(latest["sse_ret_20d_back"], digits=2),
            "detail": "回看 20 个交易日",
        },
        {
            "label": "60日联动",
            "value": format_value(latest["corr_60"], digits=3),
            "detail": "IVIX 日变化 vs 上证日收益",
        },
        {
            "label": "当前状态",
            "value": current_regime["title"],
            "detail": current_regime["detail"],
        },
    ]

    insight_lines = [
        f"全样本里，IVIX 日变化和上证日收益的线性相关只有 {daily_corr:.3f}，它更像极端情绪过滤器，而不是单独的日常择时器。",
        f"滚动 60 日相关性的中位数约为 {median_roll_corr:.3f}，说明在局部风险释放阶段，IVIX 和指数的反向联动会更明显。",
        f"买点候选规则样本 {buy_stats['count']} 次：未来 5/10/20 日上证平均分别为 {format_percent(buy_stats['mean_5d'])}、{format_percent(buy_stats['mean_10d'])}、{format_percent(buy_stats['mean_20d'])}。",
        f"卖点候选规则样本 {sell_stats['count']} 次：未来 5/10/20 日上证平均分别为 {format_percent(sell_stats['mean_5d'])}、{format_percent(sell_stats['mean_10d'])}、{format_percent(sell_stats['mean_20d'])}。",
    ]

    signal_cards = [
        {
            "title": "买点候选",
            "condition": "IVIX >= 近252日 85% 分位，20日 Z 分数 >= 1，上证 5 日跌幅 <= -3%，且 IVIX 当日回落。",
            "count": buy_stats["count"],
            "summary": f"后 20 日均值 {format_percent(buy_stats['mean_20d'])}，上涨概率 {format_percent(buy_stats['up_20d'], digits=1, signed=False)}。",
            "accent": "signal-good",
        },
        {
            "title": "卖点候选",
            "condition": "IVIX <= 近252日 25% 分位，IVIX 压在 20 日均值下方，上证 5 日涨幅 >= 3%。",
            "count": sell_stats["count"],
            "summary": f"后 20 日均值 {format_percent(sell_stats['mean_20d'])}，下跌概率 {format_percent(sell_stats['down_20d'], digits=1, signed=False)}。",
            "accent": "signal-warn",
        },
    ]

    footer = (
        "图表支持滚轮缩放、拖拽框选局部放大、双击重置视图；"
        "2018 年后的 IVIX 历史来自 QVIX 50ETF 日线回填，当前仍有 8 个交易日缺口保留为断线。"
    )

    return {
        "metrics": metrics,
        "insight_lines": insight_lines,
        "signal_cards": signal_cards,
        "signal_summary_rows": signal_summary_rows,
        "recent_signal_rows": recent_signal_rows,
        "footer": footer,
    }


def render_metric_cards(metrics: list[dict[str, str]]) -> str:
    card_html = []
    for metric in metrics:
        card_html.append(
            f"""
            <article class="metric-card">
              <div class="metric-label">{html.escape(metric["label"])}</div>
              <div class="metric-value">{html.escape(metric["value"])}</div>
              <div class="metric-detail">{html.escape(metric["detail"])}</div>
            </article>
            """
        )
    return "".join(card_html)


def render_signal_cards(signal_cards: list[dict[str, str]]) -> str:
    card_html = []
    for item in signal_cards:
        card_html.append(
            f"""
            <article class="signal-card {html.escape(item["accent"])}">
              <div class="signal-title">{html.escape(item["title"])}</div>
              <div class="signal-condition">{html.escape(item["condition"])}</div>
              <div class="signal-sample">样本数：{item["count"]}</div>
              <div class="signal-summary">{html.escape(item["summary"])}</div>
            </article>
            """
        )
    return "".join(card_html)


def render_insights(insight_lines: list[str]) -> str:
    items = "".join(f"<li>{html.escape(line)}</li>" for line in insight_lines)
    return f"<ul class=\"insight-list\">{items}</ul>"


def render_signal_summary_table(rows: list[dict[str, str]]) -> str:
    body = []
    for row in rows:
        body.append(
            f"""
            <tr>
              <td><span class="badge badge-{html.escape(row["tone"])}">{html.escape(row["label"])}</span></td>
              <td>{html.escape(row["rule"])}</td>
              <td>{html.escape(row["count"])}</td>
              <td>{html.escape(row["mean_5d"])}</td>
              <td>{html.escape(row["mean_10d"])}</td>
              <td>{html.escape(row["mean_20d"])}</td>
              <td>{html.escape(row["up_20d"])}</td>
              <td>{html.escape(row["down_20d"])}</td>
              <td>{html.escape(row["last_date"])}</td>
              <td><span class="status-chip {html.escape(row["status_class"])}">{html.escape(row["status"])}</span></td>
            </tr>
            """
        )
    rows_html = "".join(body)
    return f"""
    <div class="table-wrap">
      <table class="data-table">
        <thead>
          <tr>
            <th>信号</th>
            <th>规则摘要</th>
            <th>样本</th>
            <th>5日均值</th>
            <th>10日均值</th>
            <th>20日均值</th>
            <th>20日上涨率</th>
            <th>20日下跌率</th>
            <th>最近一次</th>
            <th>当前状态</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """


def render_recent_signal_table(rows: list[dict[str, str]]) -> str:
    if not rows:
        return '<div class="empty-state">当前没有可展示的买卖点候选记录。</div>'

    body = []
    for row in rows:
        body.append(
            f"""
            <tr>
              <td>{html.escape(row["date"])}</td>
              <td><span class="badge badge-{html.escape(row["tone"])}">{html.escape(row["label"])}</span></td>
              <td>{html.escape(row["sse"])}</td>
              <td>{html.escape(row["ivix"])}</td>
              <td>{html.escape(row["rank"])}</td>
              <td>{html.escape(row["z20"])}</td>
              <td>{html.escape(row["back_5d"])}</td>
              <td>{html.escape(row["fwd_20d"])}</td>
            </tr>
            """
        )
    rows_html = "".join(body)
    return f"""
    <div class="table-wrap">
      <table class="data-table compact-table">
        <thead>
          <tr>
            <th>日期</th>
            <th>类型</th>
            <th>上证</th>
            <th>IVIX</th>
            <th>分位</th>
            <th>20日Z</th>
            <th>近5日涨跌</th>
            <th>后20日结果</th>
          </tr>
        </thead>
        <tbody>{rows_html}</tbody>
      </table>
    </div>
    """


def render_dashboard_html(
    light_main_chart_html: str,
    dark_main_chart_html: str,
    light_regime_chart_html: str,
    dark_regime_chart_html: str,
    context: dict[str, object],
) -> str:
    metrics_html = render_metric_cards(context["metrics"])
    signal_cards_html = render_signal_cards(context["signal_cards"])
    insights_html = render_insights(context["insight_lines"])
    signal_summary_html = render_signal_summary_table(context["signal_summary_rows"])
    recent_signal_html = render_recent_signal_table(context["recent_signal_rows"])
    footer_text = html.escape(str(context["footer"]))

    return f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>IVIX 与上证指数分析面板</title>
  <style>
    :root {{
      --bg: #07111d;
      --bg2: #101b2b;
      --bg3: #13233a;
      --panel: rgba(9, 19, 32, 0.82);
      --panel-strong: rgba(12, 24, 40, 0.94);
      --ink: #e8eef7;
      --muted: #9baac0;
      --border: rgba(232, 238, 247, 0.10);
      --shadow: 0 24px 60px rgba(3, 8, 15, 0.38);
      --hero-accent: #ff8a5b;
      --hero-secondary: #6bb8ff;
      --table-stripe: rgba(255, 255, 255, 0.02);
      --status-bg: rgba(255, 255, 255, 0.05);
      --buy-bg: rgba(43, 212, 164, 0.14);
      --buy-ink: #71f3ca;
      --sell-bg: rgba(255, 191, 92, 0.14);
      --sell-ink: #ffcf7b;
      --button-bg: rgba(255, 255, 255, 0.04);
      --button-active: rgba(255, 138, 91, 0.16);
      --button-border: rgba(255, 255, 255, 0.10);
      --glow-a: rgba(255, 138, 91, 0.18);
      --glow-b: rgba(107, 184, 255, 0.16);
      --table-shell: rgba(13, 24, 38, 0.88);
      --footer-bg: rgba(255, 255, 255, 0.03);
    }}
    body[data-theme="light"] {{
      --bg: #efe7dd;
      --bg2: #f8f3ea;
      --bg3: #fffdfa;
      --panel: rgba(255, 250, 244, 0.82);
      --panel-strong: rgba(255, 250, 244, 0.94);
      --ink: #13263d;
      --muted: #5e6e83;
      --border: rgba(19, 38, 61, 0.10);
      --shadow: 0 20px 50px rgba(19, 38, 61, 0.10);
      --hero-accent: #c35a3a;
      --hero-secondary: #1c5d87;
      --table-stripe: rgba(19, 38, 61, 0.03);
      --status-bg: rgba(19, 38, 61, 0.05);
      --buy-bg: rgba(14, 159, 110, 0.10);
      --buy-ink: #0e9f6e;
      --sell-bg: rgba(216, 154, 36, 0.12);
      --sell-ink: #c27f09;
      --button-bg: rgba(19, 38, 61, 0.04);
      --button-active: rgba(195, 90, 58, 0.12);
      --button-border: rgba(19, 38, 61, 0.08);
      --glow-a: rgba(195, 90, 58, 0.12);
      --glow-b: rgba(28, 93, 135, 0.15);
      --table-shell: rgba(255, 250, 244, 0.88);
      --footer-bg: rgba(19, 38, 61, 0.04);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      color: var(--ink);
      background:
        radial-gradient(circle at top left, var(--glow-a) 0%, transparent 28%),
        radial-gradient(circle at top right, var(--glow-b) 0%, transparent 34%),
        linear-gradient(180deg, var(--bg3) 0%, var(--bg2) 36%, var(--bg) 100%);
      font-family: "Avenir Next", "Aptos", "Segoe UI", "PingFang SC", "Microsoft YaHei", sans-serif;
      transition: background 180ms ease, color 180ms ease;
    }}
    .page {{
      max-width: 1480px;
      margin: 0 auto;
      padding: 32px 24px 48px;
    }}
    .hero {{
      display: flex;
      justify-content: space-between;
      align-items: end;
      gap: 20px;
      flex-wrap: wrap;
      margin-bottom: 24px;
    }}
    .eyebrow {{
      color: var(--hero-accent);
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.22em;
      text-transform: uppercase;
      margin-bottom: 12px;
    }}
    h1 {{
      margin: 0;
      font-size: clamp(32px, 5vw, 56px);
      line-height: 0.98;
      letter-spacing: -0.03em;
      max-width: 860px;
    }}
    .subtitle {{
      margin-top: 14px;
      max-width: 860px;
      font-size: 16px;
      line-height: 1.7;
      color: var(--muted);
    }}
    .hero-side {{
      display: grid;
      gap: 12px;
      min-width: 300px;
    }}
    .theme-switch {{
      display: inline-flex;
      align-self: end;
      gap: 6px;
      padding: 6px;
      border-radius: 16px;
      border: 1px solid var(--button-border);
      background: var(--panel-strong);
      box-shadow: var(--shadow);
    }}
    .theme-btn {{
      border: 0;
      background: var(--button-bg);
      color: var(--muted);
      padding: 10px 18px;
      border-radius: 12px;
      font-size: 13px;
      font-weight: 700;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      cursor: pointer;
      transition: background 140ms ease, color 140ms ease, transform 140ms ease;
    }}
    .theme-btn.active {{
      background: var(--button-active);
      color: var(--ink);
      transform: translateY(-1px);
    }}
    .hint {{
      padding: 14px 18px;
      border: 1px solid var(--border);
      border-radius: 18px;
      background: var(--panel-strong);
      box-shadow: var(--shadow);
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .metrics {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 16px;
      margin-bottom: 18px;
    }}
    .metric-card, .panel {{
      background: var(--panel);
      border: 1px solid var(--border);
      border-radius: 26px;
      box-shadow: var(--shadow);
      backdrop-filter: blur(12px);
    }}
    .metric-card {{
      padding: 20px 22px;
      min-height: 150px;
    }}
    .metric-label {{
      font-size: 12px;
      font-weight: 700;
      color: var(--muted);
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: 18px;
    }}
    .metric-value {{
      font-size: clamp(28px, 4vw, 42px);
      font-weight: 700;
      line-height: 1.05;
      letter-spacing: -0.04em;
      margin-bottom: 12px;
    }}
    .metric-detail {{
      color: var(--muted);
      font-size: 14px;
      line-height: 1.55;
    }}
    .panel {{
      padding: 18px 18px 12px;
    }}
    .panel-title {{
      margin: 6px 6px 14px;
      font-size: 15px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--muted);
      font-weight: 700;
    }}
    .panel-subtitle {{
      margin: -4px 6px 12px;
      color: var(--muted);
      font-size: 13px;
      line-height: 1.6;
    }}
    .main-panel {{
      padding-top: 12px;
    }}
    .bottom-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.2fr) minmax(320px, 0.8fr);
      gap: 18px;
      margin-top: 18px;
    }}
    .tables-grid {{
      display: grid;
      grid-template-columns: minmax(0, 1.35fr) minmax(0, 1fr);
      gap: 18px;
      margin-top: 18px;
    }}
    .signal-stack {{
      display: grid;
      gap: 14px;
      margin-bottom: 18px;
    }}
    .signal-card {{
      border-radius: 20px;
      padding: 18px 18px 16px;
      border: 1px solid var(--border);
      background: rgba(255, 255, 255, 0.55);
    }}
    .signal-good {{
      background: linear-gradient(180deg, rgba(14, 159, 110, 0.10), rgba(255,255,255,0.55));
    }}
    .signal-warn {{
      background: linear-gradient(180deg, rgba(216, 154, 36, 0.14), rgba(255,255,255,0.55));
    }}
    .signal-title {{
      font-size: 18px;
      font-weight: 700;
      margin-bottom: 10px;
    }}
    .signal-condition, .signal-sample, .signal-summary {{
      font-size: 14px;
      line-height: 1.65;
      color: var(--muted);
    }}
    .signal-sample {{
      margin-top: 8px;
    }}
    .signal-summary {{
      margin-top: 4px;
      color: var(--ink);
      font-weight: 600;
    }}
    .table-wrap {{
      width: 100%;
      overflow-x: auto;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: var(--table-shell);
    }}
    .data-table {{
      width: 100%;
      min-width: 880px;
      border-collapse: collapse;
      font-size: 13px;
    }}
    .compact-table {{
      min-width: 720px;
    }}
    .data-table thead th {{
      padding: 14px 16px;
      text-align: left;
      font-size: 12px;
      letter-spacing: 0.08em;
      text-transform: uppercase;
      color: var(--muted);
      background: color-mix(in srgb, var(--panel-strong) 88%, transparent);
      border-bottom: 1px solid var(--border);
      white-space: nowrap;
    }}
    .data-table tbody td {{
      padding: 13px 16px;
      border-top: 1px solid var(--border);
      white-space: nowrap;
      vertical-align: middle;
    }}
    .data-table tbody tr:nth-child(even) {{
      background: var(--table-stripe);
    }}
    .badge {{
      display: inline-flex;
      align-items: center;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      letter-spacing: 0.04em;
    }}
    .badge-buy {{
      background: var(--buy-bg);
      color: var(--buy-ink);
    }}
    .badge-sell {{
      background: var(--sell-bg);
      color: var(--sell-ink);
    }}
    .status-chip {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      min-width: 68px;
      padding: 5px 10px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 700;
      background: var(--status-bg);
    }}
    .status-live {{
      color: var(--buy-ink);
      background: var(--buy-bg);
    }}
    .status-idle {{
      color: var(--muted);
    }}
    .empty-state {{
      padding: 22px 18px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.6;
    }}
    .insight-list {{
      margin: 0;
      padding-left: 22px;
      color: var(--muted);
      font-size: 14px;
      line-height: 1.85;
    }}
    .footer {{
      margin-top: 18px;
      padding: 16px 20px;
      border-radius: 18px;
      border: 1px solid var(--border);
      background: var(--footer-bg);
      color: var(--muted);
      font-size: 13px;
      line-height: 1.7;
    }}
    .plotly-wrapper > div {{
      width: 100% !important;
    }}
    .theme-chart {{
      display: none;
    }}
    body[data-theme="light"] .theme-chart[data-chart-theme="light"],
    body[data-theme="dark"] .theme-chart[data-chart-theme="dark"] {{
      display: block;
    }}
    @media (max-width: 1100px) {{
      .bottom-grid,
      .tables-grid {{
        grid-template-columns: 1fr;
      }}
    }}
    @media (max-width: 720px) {{
      .page {{ padding: 20px 14px 32px; }}
      .metric-card {{ min-height: unset; }}
      .theme-switch {{
        width: 100%;
        justify-content: space-between;
      }}
      .theme-btn {{
        flex: 1;
      }}
    }}
  </style>
</head>
<body data-theme="dark">
  <main class="page">
    <section class="hero">
      <div>
        <div class="eyebrow">IVIX Market Dashboard</div>
        <h1>把“情绪极值”翻译成更清楚的买卖点候选，而不是一条只会起伏的波动率曲线。</h1>
        <div class="subtitle">
          主图直接标出买点候选与卖点候选，副图统计不同 IVIX 分位下的未来 20 日收益表现，下面再用样本表把规则、命中次数和最近触发记录展开，让这个指标更接近交易终端里的信号面板。
        </div>
      </div>
      <div class="hero-side">
        <div class="theme-switch" role="group" aria-label="Theme Switch">
          <button class="theme-btn" type="button" data-theme-option="dark">Dark</button>
          <button class="theme-btn" type="button" data-theme-option="light">Light</button>
        </div>
        <div class="hint">
          交互提示：拖拽框选可局部放大，鼠标滚轮可连续缩放，双击图表可重置视图，右上角工具栏可导出 PNG。
        </div>
      </div>
    </section>

    <section class="metrics">
      {metrics_html}
    </section>

    <section class="panel main-panel">
      <div class="panel-title">Price, Volatility & Signal Marks</div>
      <div class="panel-subtitle">`B` 表示买点候选，`S` 表示卖点候选。买卖点都只是候选，不是脱离价格结构和仓位管理的机械信号。</div>
      <div class="plotly-wrapper">
        <div class="theme-chart" data-chart-theme="dark">{dark_main_chart_html}</div>
        <div class="theme-chart" data-chart-theme="light">{light_main_chart_html}</div>
      </div>
    </section>

    <section class="bottom-grid">
      <section class="panel">
        <div class="panel-title">Future Return By IVIX Percentile</div>
        <div class="panel-subtitle">横轴是 IVIX 在近 252 个交易日中的分位区间，柱子是未来 20 日平均收益，折线是未来 20 日上涨概率。</div>
        <div class="plotly-wrapper">
          <div class="theme-chart" data-chart-theme="dark">{dark_regime_chart_html}</div>
          <div class="theme-chart" data-chart-theme="light">{light_regime_chart_html}</div>
        </div>
      </section>
      <section class="panel">
        <div class="panel-title">Rules & Reading</div>
        <div class="signal-stack">{signal_cards_html}</div>
        {insights_html}
      </section>
    </section>

    <section class="tables-grid">
      <section class="panel">
        <div class="panel-title">Signal Stats Table</div>
        <div class="panel-subtitle">把两类候选信号放到同一张表里，方便直接比较样本数、未来收益和当前是否处于触发状态。</div>
        {signal_summary_html}
      </section>
      <section class="panel">
        <div class="panel-title">Recent Candidate Log</div>
        <div class="panel-subtitle">最近触发的买卖点候选。`后20日结果` 仍在观察窗内的会显示为 `观测中`。</div>
        {recent_signal_html}
      </section>
    </section>

    <section class="footer">{footer_text}</section>
  </main>
  <script>
    (function() {{
      const body = document.body;
      const buttons = Array.from(document.querySelectorAll('[data-theme-option]'));
      const saved = window.localStorage.getItem('ivix-theme');
      const preferred = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
      const initialTheme = saved || preferred || 'dark';

      function setTheme(theme) {{
        body.dataset.theme = theme;
        buttons.forEach((button) => {{
          const active = button.dataset.themeOption === theme;
          button.classList.toggle('active', active);
          button.setAttribute('aria-pressed', active ? 'true' : 'false');
        }});
        window.localStorage.setItem('ivix-theme', theme);
        window.requestAnimationFrame(() => {{
          window.dispatchEvent(new Event('resize'));
        }});
      }}

      buttons.forEach((button) => {{
        button.addEventListener('click', () => setTheme(button.dataset.themeOption));
      }});

      setTheme(initialTheme);
    }})();
  </script>
</body>
</html>
"""


def main() -> None:
    ivix_df = load_ivix_history()
    sse_df = load_sse_history(ivix_df["Date"].min(), ivix_df["Date"].max())
    frame = prepare_analysis_frame(ivix_df, sse_df)
    context = build_dashboard_context(frame)

    light_main_chart_html = pio.to_html(
        build_main_figure(frame, "light"),
        include_plotlyjs="cdn",
        full_html=False,
        config=PLOTLY_CONFIG,
    )
    dark_main_chart_html = pio.to_html(
        build_main_figure(frame, "dark"),
        include_plotlyjs=False,
        full_html=False,
        config=PLOTLY_CONFIG,
    )
    light_regime_chart_html = pio.to_html(
        build_regime_figure(frame, "light"),
        include_plotlyjs=False,
        full_html=False,
        config=PLOTLY_CONFIG,
    )
    dark_regime_chart_html = pio.to_html(
        build_regime_figure(frame, "dark"),
        include_plotlyjs=False,
        full_html=False,
        config=PLOTLY_CONFIG,
    )
    dashboard_html = render_dashboard_html(
        light_main_chart_html,
        dark_main_chart_html,
        light_regime_chart_html,
        dark_regime_chart_html,
        context,
    )
    OUTPUT_PATH.write_text(dashboard_html, encoding="utf-8")

    print(f"generated chart: {OUTPUT_PATH}")
    print(f"ivix rows: {int(frame['IVIX'].notna().sum())}")
    print(f"sse rows: {len(sse_df)}")


if __name__ == "__main__":
    main()
