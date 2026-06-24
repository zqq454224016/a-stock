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

## 本地运行

### 1. 安装依赖

```bash
cd a-stock/script
pip install -r requirements.txt
```

### 2. 抓取数据

```bash
# 在线模式（需要 akshare）
python fetch_data.py

# 离线演示模式
python fetch_data.py --mock
```

### 3. 生成报表

```bash
python gen_report.py
```

### 4. 预览

用任意静态服务器打开项目根目录，例如：

```bash
cd a-stock
python -m http.server 8080
```

浏览器访问 `http://localhost:8080`

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
