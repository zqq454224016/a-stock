# A股全景 · a-stock-panorama

自动采集 A 股市场数据，生成可视化 HTML 报表，支持 GitHub Pages 静态部署。

## 目录结构

```
a-stock/
├── index.html              # 站点首页
├── css/                    # 全局样式
├── js/                     # 前端脚本（ECharts 图表、导航筛选）
├── reports/                # 生成的 HTML 报表
│   ├── index.html          # 报表列表
│   ├── daily/              # 每日行情
│   ├── industry/           # 板块行业
│   ├── fund_flow/          # 资金流向
│   └── stock_rank/         # 个股排行
├── assets/data/            # JSON 原始数据
└── script/                 # 数据抓取与报表生成脚本
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

### 手动步骤

```bash
cd a-stock

# 1. 创建并激活虚拟环境
python -m venv .venv
source .venv/bin/activate    # 激活后终端提示符前会出现 (.venv)

# 2. 安装依赖（必须在 venv 内，不要全局 pip install）
python -m pip install --upgrade pip
pip install -r script/requirements.txt

# 3. 抓取数据
python script/fetch_data.py --mock   # 演示模式
# python script/fetch_data.py        # 在线模式（需要 akshare + 网络）

# 4. 生成报表
python script/gen_report.py

# 5. 预览
python -m http.server 8080
```

浏览器访问 `http://localhost:8080`

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
