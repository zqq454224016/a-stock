# A股全景 · a-stock-panorama

自动采集 A 股市场数据，生成可视化 HTML 报表，支持 GitHub Pages 静态部署。

## 目录结构

```
a-stock/
├── quant_system/           # 量化数据采集核心（重构后）
│   ├── config/             # 配置中心
│   ├── data_source/        # 数据源层（爬虫/API）
│   ├── pipeline/           # 清洗/校验/标准化/复权/巡检
│   ├── factors/            # 技术因子计算
│   ├── strategy/           # 策略（MA 金叉等）
│   ├── backtest/           # 回测引擎与绩效
│   ├── prediction/         # 可验证走势预测
│   ├── replay/             # 历史视角滚动推演
│   ├── selector/           # 上涨候选池筛选与排名
│   ├── decision/           # 单股操作建议
│   ├── impact/             # 实际影响数据提取（业绩/估值/解禁/材料价格）
│   ├── risk/               # 风控规则
│   ├── trading/            # 模拟交易
│   ├── storage/            # MySQL/Redis/JSON 存储
│   ├── models/             # 数据模型
│   ├── tasks/              # 任务层
│   ├── scheduler/          # 调度器
│   ├── utils/
│   ├── tests/
│   └── main.py             # 启动入口
├── index.html              # 站点首页
├── reports/                # HTML 报表输出
├── assets/data/            # JSON 数据
└── script/                 # 兼容入口 + 报表生成
```

## 本地运行（macOS）

使用 **Homebrew Python + 虚拟环境（venv）**，全程用 `python` / `pip`，避免 `externally-managed-environment` 报错。

### 0. 配置 PATH（只需一次）

Homebrew 安装的 `python` 在 libexec 目录，加入 `~/.zshrc`：

```bash
echo 'export PATH="/opt/homebrew/opt/python@3.12/libexec/bin:$PATH"' >> ~/.zshrc
source ~/.zshrc
```

验证：`python --version` 应显示 Python 3.12.x

### 一键初始化

```bash
cd a-stock
chmod +x setup.sh
./setup.sh
```

### 推荐启动方式（避免 zsh `python` alias 问题）

若 `~/.zshrc` 里有 `alias python=...`，激活 venv 后 `python` 仍可能指向 Homebrew，导致 `No module named 'pandas'`。**请用项目脚本：**

```bash
cd a-stock
chmod +x run.sh setup.sh
./run.sh mvp              # MVP 闭环（推荐）：750日补录→行情→因子→增强→回测→预测→看板
./run.sh all              # 同上，可 --skip-backtest / --skip-predict / --skip-enhance
./run.sh stock
./run.sh enhance          # 数据增强（P1-3）
./run.sh agent            # Agent 看板（P4-1）
./run.sh impact           # 实际影响数据（业绩/估值/解禁/材料价格）
./run.sh selector         # 上涨候选池排名
./run.sh decision         # 单股操作建议（指导性优先）
./run.sh simtrade         # 模拟交易（P3-1）
./run.sh predict
./run.sh replay           # 十日前视角滚动推演
```

或显式使用 venv 解释器：

```bash
.venv/bin/python quant_system/main.py all
```

若坚持用 `source .venv/bin/activate`，当前终端需先取消 alias：

```bash
unalias python 2>/dev/null
source .venv/bin/activate
python quant_system/main.py all
```

### 手动步骤

```bash
cd a-stock

# 1. 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate    # 激活后终端提示符前会出现 (.venv)

# 2. 安装依赖（必须在 venv 内，不要全局 pip install）
python -m pip install --upgrade pip
pip install -r quant_system/requirements.txt

# 3. 采集数据（推荐 quant_system 入口）
python quant_system/main.py market          # 大盘行情
python quant_system/main.py stock           # 自选股分析
python quant_system/main.py all             # watchlist 全量：巡检→行情→个股→回测→预测→看板→报表

> **MVP 闭环**：`./run.sh mvp` 或 `./run.sh all` 按 Quantification.md §1.3 执行完整链路（含 750 日历史补录、跨源校验、因子、回测、可验证预测、盘中看板）。

> **watchlist 约定**：`assets/data/watchlist.json` 中的股票为默认执行范围。新增代码后运行 `stock` / `all` / `gen_stock_report` 会自动补采集缺失数据，无需手动传代码参数。

> **科创板参考模式**：`688xxx` / `689xxx` 个股默认只作为参考，不进入补录、增强、因子、回测、预测、selector、decision、模拟交易、Agent 等重型链路；显式传入代码可手动分析。关闭该策略：`STAR_BOARD_REFERENCE_ONLY=0 ./run.sh all`。

# 或使用兼容脚本
python script/fetch_data.py
python script/fetch_stock.py

# 4. 生成报表
python script/gen_report.py

# 5. 个股分析
python quant_system/main.py stock 600519 300308

# 6. 盘中实时（交易时段轮询分钟线 + 前端自动刷新）
python quant_system/main.py live              # 单次采集
python quant_system/main.py live --loop       # 循环采集（默认 60s）
python quant_system/main.py live --loop --interval 30
# 盘中看板：reports/live/index.html（mvp/all/stock 后自动生成）

# 7. 技术因子 & 数据巡检（Phase 0 下一阶段）
python quant_system/main.py factor            # 计算 RSI/MACD/ATR 等因子 + 初级走势信号
python quant_system/main.py inspect           # K 线质量巡检（含东财/新浪跨源 diff）
python quant_system/main.py inspect --fix     # 巡检 + 自动 backfill

# 8. 回测（MA 金叉 / 多因子策略，含 P2-4 容量约束 + 收益归因 + 滚动验证）
python quant_system/main.py backtest              # 自选股回测 ~3 年
python quant_system/main.py backtest --strategy multi_factor --allow-warn
python quant_system/main.py backtest --no-rolling # 跳过滚动 OOS 验证
# 报告：reports/backtest/{code}_ma_cross.html

# 9. 多因子排名（技术 + 情绪 + 基本面 + 资金）
python script/gen_factor_report.py
# 页面：reports/factors/index.html

# 9. 走势预测（5d 可验证预测，需回测证据）
python quant_system/main.py predict
python quant_system/main.py predict 600378 --horizon 5d
# 汇总页：reports/predict/index.html

# 10. 历史视角滚动推演（默认最近 10 个交易日）
python quant_system/main.py replay
python quant_system/main.py replay --days 10
python quant_system/main.py replay 600378 --days 10
# 汇总页：reports/replay/index.html · 数据：assets/data/replay/{code}.json

# 11. 舆情采集（东财评论 + 雪球热榜，P1-2）
python quant_system/main.py sentiment

# 12. 数据增强（估值/分红解禁/北向两融/指数，P1-3）
python quant_system/main.py enhance
# 汇总页：reports/enhance/index.html · 数据：assets/data/enhance/{code}.json

# 13. Agent 分析与统一看板（P4-1）
python quant_system/main.py agent
# 看板：reports/agent/index.html · 报表列表自动收录 Agent 入口

# 14. 单股操作建议（Decision Engine，指导性优先）
python quant_system/main.py decision
python quant_system/main.py decision 600378 --strategy ma_cross
# 看板：reports/decision/index.html · 数据：assets/data/decisions/{code}.json

# 15. 上涨候选池筛选（预测 + 因子 + 趋势 + 回测 + 实际影响）
python quant_system/main.py selector
python quant_system/main.py selector 600378 000988
# 看板：reports/selector/index.html · 数据：assets/data/selector/{code}.json

# 16. 实际影响数据（业绩预告/估值/解禁/生产材料或产品价格）
python quant_system/main.py impact
python quant_system/main.py impact 603629 600378
python script/gen_impact_report.py
# 看板：reports/impact/index.html · 数据：assets/data/impact/{code}.json
# decision 默认自动补齐 impact，可用 --no-impact 关闭。

# 17. 模拟交易（P3-1，基于决策/预测虚拟调仓）
python quant_system/main.py simtrade
python quant_system/main.py simtrade --reset --cash 100000
# 看板：reports/trading/index.html · 数据：assets/data/trading/account.json

# 18. 报表列表同步（Agent / 因子 / 预测 / 推演 / 候选 / 决策 / 影响 / 增强 / 回测 / 模拟交易）
python script/report_index_utils.py

# 19. 定时调度（可选）
python quant_system/main.py scheduler

# 20. 预览
python -m http.server 8080
```

浏览器访问 `http://localhost:8080`

盘中实时数据写入 `assets/data/stocks/live/{code}.json`。`stock` / `all` 会自动刷新一次现价；**交易时段真正连续更新**需另开终端：

```bash
./run.sh live --loop --interval 15
```

> 每次新开终端都需要先 `source .venv/bin/activate` 再运行脚本。退出虚拟环境：`deactivate`

### 未安装 Python？

```bash
brew install python@3.12
```

## GitHub Pages 部署

1. 将仓库推送到 GitHub
2. 在 **Settings → Pages** 中选择 **GitHub Actions** 作为 Source
3. `.github/workflows/auto-build.yml` 会在每个工作日自动：
   - 拉取 A 股数据
   - 生成 HTML 报表
   - 部署到 GitHub Pages

也可在 Actions 页面手动触发 **workflow_dispatch**。

## 技术栈

- 前端：原生 HTML / CSS / JavaScript + [ECharts](https://echarts.apache.org/)
- 数据：[akshare](https://github.com/akfamily/akshare)
- 部署：GitHub Actions + GitHub Pages

## 免责声明

本项目数据仅供参考，不构成任何投资建议。股市有风险，投资需谨慎。
