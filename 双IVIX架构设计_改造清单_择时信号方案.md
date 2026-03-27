# 双 IVIX 架构设计 + Python 改造清单

## 1. 目标说明

本方案用于将现有 `ivix` 仓库从“单一 50ETF IVIX 计算脚本”，改造成一套可扩展的 **双 IVIX 研究与生产框架**：

- 保留 `IVIX_50ETF`：作为系统性风险锚
- 新增 `IVIX_1000INDEX`：作为中小盘风险偏好放大器
- 统一输出标准化因子面板
- 提供 3 个可直接回测的择时信号定义
- 支持后续继续扩展到 `300INDEX`、`500ETF` 等其他波动率指数标的

---

## 2. 为什么不建议“替换”，而建议“双轨制”

直接把上证50替换成中证1000，并不是最优方案。

更合理的方式是：

- **50ETF IVIX** 用来观测全市场系统性风险
- **1000INDEX IVIX** 用来观测小盘风格和风险偏好变化
- **Spread(IVIX_1000 - IVIX_50)** 用来识别风格切换和情绪拐点

### 核心原因

1. 当前仓库的数据抓取链路本身是围绕 `50ETF` 构建的
2. 中证1000期权与50ETF期权的交易所、字段结构、数据接口都不同
3. 中证1000股指期权上市时间较晚，无法完全替代 50ETF 的长历史序列
4. 做成双 IVIX 后，系统性风险与风格风险可以同时观测，信息量更高

---

## 3. 当前仓库需要改造的关键位置

现有仓库中，IVIX 数学公式层基本是可复用的。真正写死在 50ETF 上的，主要是以下四层：

### 3.1 标的配置层
当前代码把以下内容写死到了 50ETF：

- QVIX 历史 URL
- Referer
- 默认标的名称
- 默认合约规则

### 3.2 实时抓取层
当前 `fetch_latest_option_data()` 默认抓取的是：

- 上交所 ETF 期权板
- 50ETF 对应的新浪接口
- `510050` 作为底层 ETF

这套逻辑不适合原样用于中证1000股指期权。

### 3.3 历史回填层
当前仓库只支持：

- 50ETF 的历史 IVIX 回补
- 单文件 `ivix.csv` 输出

这不适合做多标的并行输出。

### 3.4 字段适配层
当前 `_normalize_board_to_option_rows()` 默认输入是“宽表结构”，即一行同时带 call / put。

但中证1000股指期权更可能返回“长表结构”，即一行一个合约，因此需要额外适配器。

---

## 4. 改造目标架构

建议将仓库重构为以下结构：

```text
ivix/
├─ app.py
├─ config/
│  └─ instruments.py
├─ core/
│  ├─ schema.py
│  ├─ ivix_formula.py
│  ├─ normalize.py
│  └─ history_merge.py
├─ providers/
│  ├─ base.py
│  ├─ qvix_provider.py
│  ├─ sse_etf_option_provider.py
│  ├─ cffex_index_option_provider.py
│  └─ shibor_provider.py
├─ signals/
│  ├─ spread.py
│  ├─ zscore.py
│  └─ regime.py
├─ storage/
│  ├─ raw/
│  ├─ normalized/
│  └─ factors/
└─ tests/
```

---

## 5. 分层职责说明

### 5.1 `core/ivix_formula.py`
职责：

- 保留原仓库中的 IVIX 数学核心
- 输入统一后的标准化期权行情
- 输出某日 IVIX 值

该层只关心：

- 近月 / 次近月合约
- 到期时间
- 无风险利率
- 行权价
- 看涨 / 看跌价格

不应关心数据来自 SSE、CFFEX、AKShare 还是其他来源。

---

### 5.2 `providers/qvix_provider.py`
职责：

- 拉取历史 QVIX 数据
- 供历史回填和研究使用
- 支持 50ETF 与 1000INDEX

建议统一从 AKShare 获取，而不是继续手工维护 URL + Referer。

---

### 5.3 `providers/sse_etf_option_provider.py`
职责：

- 保留现有 50ETF 实时期权板抓取逻辑
- 支持按月份抓取不同到期合约
- 输出标准化前的原始板数据

---

### 5.4 `providers/cffex_index_option_provider.py`
职责：

- 新增中证1000股指期权板抓取器
- 使用 `ak.option_finance_board(symbol="中证1000股指期权", end_month="YYMM")`
- 输出标准化前的原始板数据

---

### 5.5 `core/normalize.py`
职责：

- 将不同来源的数据统一映射到 Canonical Schema
- 再从 Canonical Schema 转为 Legacy IVIX Schema
- 供原公式层无缝复用

---

### 5.6 `signals/`
职责：

- 基于双 IVIX 面板生成研究与交易信号
- 输出日频因子与状态变量
- 直接供 pandas / qlib / 自建回测系统读取

---

## 6. 标的配置设计

建议建立统一配置表：

```python
INSTRUMENTS = {
    "50ETF": {
        "kind": "etf_option",
        "exchange": "SSE",
        "provider_realtime": "sse_etf_option",
        "provider_history": "qvix",
        "qvix_symbol": "50ETF",
        "ak_qvix_func": "index_option_50etf_qvix",
        "ak_qvix_min_func": "index_option_50etf_min_qvix",
        "sina_underlying": "510050",
        "valid_start": "2015-02-09",
    },
    "1000INDEX": {
        "kind": "index_option",
        "exchange": "CFFEX",
        "provider_realtime": "cffex_index_option",
        "provider_history": "qvix",
        "qvix_symbol": "Index1000",
        "ak_qvix_func": "index_option_1000index_qvix",
        "ak_qvix_min_func": "index_option_1000index_min_qvix",
        "ak_board_symbol": "中证1000股指期权",
        "valid_start": "2022-07-22",
    },
}
```

### 说明

- `50ETF` 可作为长历史主序列
- `1000INDEX` 真实有效历史起点建议设为股指期权上市日
- 后续扩展时只需新增配置，而无需重写公式层

---

## 7. 数据抓取层设计

## 7.1 50ETF 实时抓取

沿用现有 SSE ETF 期权抓取逻辑：

- 获取可用到期月份
- 逐月抓取 option board
- 转成统一格式

伪代码：

```python
def fetch_latest_option_data(instrument_id: str, trade_date: str, months_ahead: int = 4):
    provider = get_provider(INSTRUMENTS[instrument_id]["provider_realtime"])
    ...
```

---

## 7.2 中证1000 实时抓取

新增 `cffex_index_option_provider.py`：

```python
import akshare as ak

def fetch_cffex_option_board(symbol: str, end_month: str):
    return ak.option_finance_board(symbol=symbol, end_month=end_month)
```

建议：

- 默认抓近月、次近月、季月
- 与 50ETF 一样统一输出原始板数据
- 后续进入标准化层再做字段适配

---

## 7.3 历史 QVIX 抓取

统一使用 AKShare：

```python
def fetch_qvix_history(instrument_id: str):
    if instrument_id == "50ETF":
        df = ak.index_option_50etf_qvix()
    elif instrument_id == "1000INDEX":
        df = ak.index_option_1000index_qvix()
    return df
```

优点：

- 不再依赖手工 URL
- 不再需要手写 Referer
- 更适合后续扩展
- 与研究层接口一致

---

## 8. 字段适配层设计

这是整个改造中最关键的一层。

现有公式层期望接收到的字段为：

```python
["trade_date", "SEC_NAME", "EXE_MODE", "EXE_PRICE", "EXE_ENDDATE", "CLOSE"]
```

但不同来源的数据结构不同，因此建议先建立 **Canonical Schema**：

```python
CANONICAL_OPTION_SCHEMA = [
    "trade_date",
    "underlying_id",
    "contract_code",
    "contract_name",
    "option_type",   # C / P
    "strike",
    "expiry_date",
    "last_price",
]
```

然后统一投影为 Legacy IVIX Schema：

```python
def to_legacy_ivix_schema(df):
    return pd.DataFrame({
        "trade_date": df["trade_date"],
        "SEC_NAME": df["contract_name"],
        "EXE_MODE": df["option_type"].map({"C": "认购", "P": "认沽"}),
        "EXE_PRICE": df["strike"],
        "EXE_ENDDATE": df["expiry_date"].dt.strftime("%Y/%m/%d 0:00"),
        "CLOSE": df["last_price"],
        "UNDERLYING_ID": df["underlying_id"],
    })
```

---

## 9. 两类标准化适配器

### 9.1 宽表适配器（适合 50ETF）

输入特点：

- 一行一个 strike
- 同时带 call / put 字段

输出方式：

- 拆成两行
- 分别映射为 `认购` / `认沽`

---

### 9.2 长表适配器（适合中证1000）

输入特点：

- 一行一个合约
- 包含 instrument / lastprice / volume 等字段

输出方式：

- 逐行映射为标准化结构
- 从合约名中解析：
  - 期权方向
  - 行权价
  - 到期日

---

## 10. 历史回补方案

### 10.1 历史文件存储建议

```text
storage/factors/
├─ ivix_50etf.csv
├─ ivix_1000index.csv
├─ ivix_dual_panel.csv
└─ ivix_signals.csv
```

---

### 10.2 单标的历史回补输出格式

建议统一为：

```python
["date", "instrument_id", "ivix_close", "ivix_open", "ivix_high", "ivix_low", "source"]
```

如果历史源只有收盘值，则 open/high/low 可先与 close 保持一致，或留空。

---

### 10.3 双 IVIX 合并面板字段

```python
[
    "date",
    "ivix_50",
    "ivix_1000",
    "spread_1000_50",
    "ratio_1000_50",
    "z_20_spread",
    "z_60_ivix_1000",
    "d1_ivix_1000",
    "d3_ivix_1000"
]
```

---

### 10.4 历史回填伪代码

```python
def backfill_history(instrument_id: str) -> pd.DataFrame:
    df = fetch_qvix_history(instrument_id)
    df["DateTime"] = pd.to_datetime(df["DateTime"], errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df = df.dropna(subset=["DateTime", "value"]).sort_values("DateTime")
    valid_start = pd.to_datetime(INSTRUMENTS[instrument_id]["valid_start"])
    df = df[df["DateTime"] >= valid_start]
    return df
```

---

### 10.5 回测区间建议

#### 单独验证 `IVIX_50ETF`
- 可从长历史起点开始

#### 双 IVIX 联合回测
- 建议从 `2022-07-22` 开始
- 更稳妥的主回测段可设为 `2023-01-01` 之后
- 2022 下半年可作为 warm-up 或适配期

---

## 11. Python 改造清单（按执行顺序）

## 第 1 步：抽出标的配置
从原脚本中移除：

- 50ETF 专属 URL
- Referer
- 50ETF 默认命名
- 默认底层 ETF 标识

集中放到 `config/instruments.py`

---

## 第 2 步：新增 Provider 基类

```python
class OptionProvider(Protocol):
    def fetch_board(self, instrument_id: str, trade_date: str, month_code: str) -> pd.DataFrame:
        ...
```

---

## 第 3 步：重写 `fetch_latest_option_data()`
改为按配置自动分派：

```python
def fetch_latest_option_data(instrument_id: str, trade_date: str, months_ahead: int = 4):
    provider = get_provider(INSTRUMENTS[instrument_id]["provider_realtime"])
    ...
```

---

## 第 4 步：拆分标准化逻辑
将现有 `_normalize_board_to_option_rows()` 拆成：

```python
normalize_sse_pair_board(...)
normalize_cffex_long_board(...)
```

---

## 第 5 步：改单文件输出为多文件输出
原先：

```python
ivix.csv
```

改成：

```python
storage/factors/ivix_50etf.csv
storage/factors/ivix_1000index.csv
```

---

## 第 6 步：新增双 IVIX 合并器

```python
def build_dual_ivix_panel(ivix50_path, ivix1000_path):
    ...
```

输出：

- spread
- ratio
- zscore
- rolling delta
- regime 变量

---

## 第 7 步：新增信号生成层
生成：

```python
date, signal_panic_reversal, signal_spread_revert, regime_state
```

并写出：

```python
storage/factors/ivix_signals.csv
```

---

## 第 8 步：将入口脚本改成 CLI

```bash
python app.py sync --instrument 50ETF
python app.py sync --instrument 1000INDEX
python app.py sync-all
python app.py build-panel
python app.py build-signals
```

---

## 12. 三个可直接回测的择时信号定义

## 信号 1：恐慌冲顶回落信号

### 目标
捕捉中证1000风格中“恐慌极值释放后的短中期修复”。

### 定义

```text
panic_z_1000 = zscore(IVIX_1000, 60)

entry_long =
    panic_z_1000 > 1.5
    and delta_3d(IVIX_1000) < -8%
```

### 含义
先出现中证1000恐慌快速抬升，再在 3 天内快速回落，视为恐慌释放。

### 退出
```text
exit =
    IVIX_1000 < ma20(IVIX_1000)
    or holding_days >= 15
```

### 用法
适合：

- 中小盘修复启动
- 情绪杀跌后的反抽
- 风险偏好快速回暖阶段

---

## 信号 2：双 IVIX Spread 收敛信号

### 目标
捕捉“小票相对恐慌溢价见顶后”的风格切换。

### 定义

```text
spread = IVIX_1000 - IVIX_50
spread_z = zscore(spread, 60)

entry_long =
    spread_z_{t-1} > 1.2
    and spread_t < spread_{t-1}
    and spread_{t-1} < spread_{t-2}
```

### 更强版本
加入价格确认：

```text
entry_long =
    spread_z_{t-1} > 1.2
    and spread 连续2天下降
    and 中证1000指数 close > ma5(close)
```

### 退出
```text
exit =
    spread_z < 0
    or 中证1000 close < ma10(close)
```

### 用法
这是最推荐的信号，适合：

- 小票风格启动
- 风格恐慌从极端回归
- 题材修复阶段提前识别

---

## 信号 3：风险偏好修复 Regime 信号

### 目标
做成总仓位环境过滤器，而非单一买卖点。

### 三状态定义

#### S0 防守
```text
IVIX_1000 > ma20(IVIX_1000)
and spread_1000_50 > 0
and spread_z > 0.8
```

#### S1 过渡
```text
IVIX_1000 开始回落
but spread_1000_50 仍大于 0
```

#### S2 进攻
```text
IVIX_1000 < ma20(IVIX_1000)
and spread_1000_50 < ma20(spread_1000_50)
and 中证1000 close > ma20(close)
```

### 仓位映射建议

```text
S0: 股票仓 20%，防守仓 80%
S1: 股票仓 50%
S2: 股票仓 80%~100%
```

### 用法
适合与你现有的：

- B1 策略
- 中小盘趋势策略
- 板块轮动策略
- 小票择时框架

直接进行环境门控组合。

---

## 13. 最小可行实现顺序（MVP）

## Phase 1：先跑通双历史面板
目标：

- `ivix_50etf.csv`
- `ivix_1000index.csv`
- `ivix_dual_panel.csv`

说明：

- 只使用 QVIX 历史接口
- 暂不碰实时期权板抓取
- 开发风险最低
- 先解决研究和回测问题

---

## Phase 2：再跑通信号层
目标：

- 计算 spread / ratio / zscore
- 输出 3 个交易信号
- 生成 `ivix_signals.csv`

---

## Phase 3：最后接实时板抓取
目标：

- 50ETF 实时更新
- 中证1000实时报价接入
- 同步更新双 IVIX 因子面板

这样可以保证：

- 历史研究先落地
- 回测逻辑先验证
- 实时系统后补齐

---

## 14. 最终建议

最优落地方式不是：

> 把上证50换成中证1000

而是：

> 保留 50ETF 作为系统性风险锚，新增 1000INDEX 作为中小盘风险偏好放大器，再用 spread 做风格转折检测。

### 结论摘要

- **50ETF IVIX**：适合识别系统性风险
- **1000INDEX IVIX**：适合识别小盘风格和风险偏好变化
- **Spread(1000 - 50)**：最有信息量，最适合作为转折识别核心变量
- **Regime 状态机**：最适合接到你现有交易系统上，做总仓位门控

