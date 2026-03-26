中国市场波动指数（IVIX）计算。  
核心公式遵循 CBOE VIX 思路（30 天方差插值），与文中推导一致，按近月/次近月期权合成方差后换算成年化波动率。

## 功能

- `ivvx.py`：
  - 保留历史 IVIX 的核心计算函数；
  - 新增 `refresh_latest_ivix()`，可每日拉取最新 50ETF 期权行情并计算当日 IVIX；
  - 结果会追加/更新到 `ivix.csv`（列：`DateTime,value`）。

## 运行方式

```bash
python ivvx.py
```

成功后输出类似：

```text
latest ivix(2026/03/26)=18.2345
```

## 数据说明

- 本地文件：
  - `options.csv`：历史期权样本；
  - `shibor.csv`：Shibor 曲线；
  - `ivix.csv`：输出文件（含历史与最新值）。
- 在线数据：
  - 通过 AKShare `option_finance_board` 获取当日近月/次近月（及更多月份）50ETF 期权报价；
  - 若当天非交易日或接口无返回，会抛出异常提示。
