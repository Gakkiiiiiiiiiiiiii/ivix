中国市场波动指数（IVIX）计算。  
核心公式遵循 CBOE VIX 思路（30 天方差插值），与文中推导一致，按近月/次近月期权合成方差后换算成年化波动率。

## 功能

- `ivvx.py`：
  - 保留历史 IVIX 的核心计算函数；
  - 新增 `backfill_ivix_history()`，会自动从 QVIX 50ETF 日线补齐 `2018/07/06` 之后缺失的历史区间；
  - 启动入口改为 `sync_and_refresh_ivix()`，会先回填历史，再拉取最新 50ETF 期权行情并计算当日 IVIX；
  - 若同一日期同时存在本地历史值和在线回填值，优先保留本地已计算值；
  - 结果会追加/更新到 `ivix.csv`（列：`DateTime,value`）。

## 运行方式

```bash
python ivvx.py
```

Windows PowerShell 5.1 默认会把无 BOM 的 UTF-8 文件按系统 ANSI/GBK 读取，`Get-Content README.md`、`Get-Content ivvx.py` 这类命令会直接出现中文乱码。

- 项目内修复：
  - `activate_ivix.ps1` 和 `run_ivix.ps1` 现在都会先加载 `powershell_utf8.ps1`，显式把控制台、PowerShell 文件读写和 Python 输出都切到 UTF-8。
  - 如果当前 PowerShell 执行策略禁止 `.ps1`，可直接使用 `activate_ivix.cmd`、`run_ivix.cmd` 和 `codex_utf8.cmd`，这些入口会自动附带 `-ExecutionPolicy Bypass`。
- 全局修复：
  - 建议优先使用 PowerShell 7 (`pwsh`)；
  - 如果仍使用 Windows PowerShell 5.1，至少要在读取文件时显式使用 `-Encoding UTF8`；
  - 若要给 Codex 单独启动一个兼容 UTF-8 的 PowerShell，可用 `powershell.exe -ExecutionPolicy Bypass` 启动后再运行 `codex`，或在允许本地脚本的前提下把 `powershell_utf8.ps1` 的内容写入 `$PROFILE`。

成功后输出类似：

```text
backfilled ivix history rows=2694
latest ivix(2026/03/26)=18.1551
```

## 数据说明

- 本地文件：
  - `options.csv`：历史期权样本；
  - `shibor.csv`：Shibor 曲线；
  - `ivix.csv`：输出文件（含历史与最新值）。
- 在线数据：
  - 通过 QVIX 50ETF 日线补齐历史缺失区间；
  - 通过新浪期权行情获取当日近月/次近月（及更多月份）50ETF 期权报价；
  - 若当天非交易日或在线接口无返回，最新值刷新会抛出异常提示。
