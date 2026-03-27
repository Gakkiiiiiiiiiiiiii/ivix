# 双 IVIX 实盘规则卡

## 1. 策略定位

这套规则不是用来预测明天涨跌，而是用来做两件事：

- 用 `Regime` 决定总风险预算和仓位档位
- 用 `Confirmed Spread` 决定何时从观察状态切换到执行状态

适用标的：

- `CSI1000` 指数增强
- 中证 1000 ETF
- IM 股指期货
- 小盘成长 / 小票修复风格组合

默认执行口径：

- 指标在收盘后确认
- 信号于下一交易日执行
- 回测交易成本按单边 `0.05%`

## 2. 核心指标

### Regime

`Regime` 用来分配仓位，不用来单独给方向。

- `S0`：防守区，允许试仓，但不允许重仓
- `S1`：过渡区，可以做标准仓位
- `S2`：进攻区，可以加到策略上限

当前回测里的仓位上限映射：

- `S0 = 20%`
- `S1 = 50%`
- `S2 = 80%`

### Confirmed Spread

`Confirmed Spread` 对应信号列 `signal_spread_revert_confirmed`。

它的含义是：

- 小盘恐慌溢价已经抬升
- 溢价开始回落
- 价格本身出现确认，不是纯情绪尖峰

这类信号适合做恐慌释放后的修复入场。

## 3. 执行规则

### 开仓

满足以下条件时，下一交易日开仓：

- 当日 `signal_spread_revert_confirmed = 1`
- 当前空仓

开仓仓位按当日 `Regime` 决定：

- `S0`：开 `20%`
- `S1`：开 `50%`
- `S2`：开 `80%`

解释：

- `S0` 不再作为硬性禁止入场条件，只做轻仓试单
- 这样可以保留 `Confirmed Spread` 的正期望，同时避免过早重仓

### 加仓

持仓后，满足以下条件时，下一交易日加仓：

- 已有持仓
- `Regime` 升档到更高仓位级别
- `CSI1000` 收盘价高于或等于 `MA10`

加仓规则：

- 若升到 `S1`，仓位允许提升到 `50%`
- 若升到 `S2`，仓位允许提升到 `80%`

### 减仓

持仓后，满足以下任一条件时，下一交易日减仓：

- `Regime` 从高档降到低档
- 持仓已满 `5` 个交易日，且 `CSI1000` 收盘跌破 `MA10`

减仓目标：

- 降到对应 `Regime` 档位
- 若价格走弱但未到清仓条件，至少降到 `20%`

### 清仓

持仓后，满足以下任一条件时，下一交易日清仓：

- 持仓满 `15` 个交易日
- 持仓满 `5` 个交易日，且 `z_60_spread < 0`
- 持仓满 `5` 个交易日，且 `CSI1000` 连续 `2` 天收在 `MA10` 下方

解释：

- 这套规则不是追求拿到整段主升，而是抓恐慌修复后的第一段
- 因此 `15` 个交易日是硬上限，避免情绪修复结束后还继续硬扛

## 4. 盘后检查清单

每天收盘后只看 4 件事：

1. `signal_spread_revert_confirmed` 今天是否触发
2. 当前 `Regime` 是 `S0 / S1 / S2` 哪一档
3. `CSI1000` 是否站在 `MA10` 上方
4. `z_60_spread` 是否已经回到 `0` 以下

简单执行表：

- 空仓 + 出现 `Confirmed Spread`：按 `Regime` 开仓
- 持仓 + `Regime` 升档且价格在 `MA10` 上方：加仓
- 持仓 + `Regime` 降档或价格跌破 `MA10`：减仓
- 持仓 + `Spread` 修复结束或价格连续走弱或超过持有上限：清仓

## 5. 回测口径

回测标的：

- `CSI1000` 收盘价序列

样本区间：

- `2022-10-21` 到 `2026-03-27`

策略口径：

- 入场信号仅使用 `Confirmed Spread`
- `Regime` 只用于仓位控制，不做硬过滤
- 最短持有 `5` 天
- 最长持有 `15` 天

## 6. 回测结果

本地最新回测结果如下：

- 策略累计收益：`10.52%`
- 策略年化收益：`3.10%`
- 策略最大回撤：`-2.59%`
- 策略 Sharpe：`0.99`
- 基准累计收益：`20.43%`
- 基准年化收益：`5.85%`
- 基准最大回撤：`-39.22%`
- 基准 Sharpe：`0.35`
- 交易次数：`7`
- 胜率：`57.14%`
- 平均持有天数：`10.29`
- 单笔平均收益：`2.93%`

这说明：

- 策略累计收益低于直接持有指数
- 但回撤控制和风险调整后收益明显优于直接持有
- 更适合做“低回撤择时覆盖层”，而不是单独替代满仓趋势系统

## 7. 使用建议

- 如果你要做保守版实盘，就按这份规则直接执行
- 如果你要做进攻版实盘，可以把 `signal_panic_reversal` 作为第二入场信号并行观察
- 如果你要做更高频的择时，这套规则不够快，应该另配趋势或成交量因子

## 8. 相关文件

- 回测脚本：[backtest_ivix_strategy.py](D:\project\ivix\backtest_ivix_strategy.py)
- 回测净值：[ivix_strategy_backtest_nav.csv](D:\project\ivix\storage\factors\ivix_strategy_backtest_nav.csv)
- 交易明细：[ivix_strategy_backtest_trades.csv](D:\project\ivix\storage\factors\ivix_strategy_backtest_trades.csv)
- 回测摘要：[ivix_strategy_backtest_summary.csv](D:\project\ivix\storage\factors\ivix_strategy_backtest_summary.csv)

## 9. 增强版回测对比

增强版做法：

- 在原有 `Confirmed Spread` 入场条件基础上
- 额外允许 `signal_panic_reversal` 作为第二入场信号
- 其它仓位控制、减仓和清仓规则不变

对比结果如下：

- 基线版 `Confirmed Spread`：
  累计收益 `10.52%`，最大回撤 `-2.59%`，Sharpe `0.99`，交易 `7` 笔，胜率 `57.14%`
- 增强版 `Confirmed Spread + Panic Reversal`：
  累计收益 `15.14%`，最大回撤 `-2.59%`，Sharpe `1.21`，交易 `9` 笔，胜率 `66.67%`

增强版相对基线版的变化：

- 多了 `2` 笔交易
- 累计收益提升约 `4.62` 个百分点
- 胜率提升约 `9.52` 个百分点
- Sharpe 提升明显
- 最大回撤基本没有变差

增强版新增的两笔交易主要是：

- `2024-10-14` 开仓，`2024-10-28` 平仓，单笔收益约 `8.30%`
- `2025-08-25` 开仓，`2025-09-01` 平仓，单笔收益约 `0.31%`

这说明：

- `panic_reversal` 作为第二入场信号在当前样本里是增益项
- 它没有明显抬高回撤，却提高了样本利用率和整体收益
- 如果你要做进攻版执行，增强版更值得优先跟踪

新增对比文件：

- 对比净值：[ivix_strategy_compare_nav.csv](D:\project\ivix\storage\factors\ivix_strategy_compare_nav.csv)
- 对比交易清单：[ivix_strategy_compare_trades.csv](D:\project\ivix\storage\factors\ivix_strategy_compare_trades.csv)
- 对比摘要：[ivix_strategy_compare_summary.csv](D:\project\ivix\storage\factors\ivix_strategy_compare_summary.csv)
