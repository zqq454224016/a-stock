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
│   ├── risk/               # 风控规则
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
./run.sh all              # 等价于 .venv/bin/python quant_system/main.py all
./run.sh stock
./run.sh predict
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
python quant_system/main.py all             # watchlist 全量：巡检→行情→个股→回测→预测→报表

> **watchlist 约定**：`assets/data/watchlist.json` 中的股票为默认执行范围。新增代码后运行 `stock` / `all` / `gen_stock_report` 会自动补采集缺失数据，无需手动传代码参数。

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

# 7. 技术因子 & 数据巡检（Phase 0 下一阶段）
python quant_system/main.py factor            # 计算 RSI/MACD/ATR 等因子 + 初级走势信号
python quant_system/main.py inspect           # K 线质量巡检（含东财/新浪跨源 diff）
python quant_system/main.py inspect --fix     # 巡检 + 自动 backfill

# 8. 回测（MA 金叉策略 MVP）
python quant_system/main.py backtest              # 自选股回测 ~3 年
python quant_system/main.py backtest 600378 --allow-warn
# 报告：reports/backtest/{code}_ma_cross.html

# 9. 走势预测（5d 可验证预测，需回测证据）
python quant_system/main.py predict
python quant_system/main.py predict 600378 --horizon 5d
# 汇总页：reports/predict/index.html

# 10. 定时调度（可选）
python quant_system/main.py scheduler

# 11. 预览
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
