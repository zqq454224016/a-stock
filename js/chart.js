/**
 * 图表渲染（ECharts）
 */

function formatPct(value) {
  const sign = value >= 0 ? '+' : '';
  return sign + value.toFixed(2) + '%';
}

function pctClass(value) {
  return value >= 0 ? 'text-up' : 'text-down';
}

/** 渲染指数统计卡片 */
function renderIndexStats(indices, containerId) {
  const container = document.getElementById(containerId);
  if (!container || !indices) return;

  container.innerHTML = indices.map(idx => `
    <div class="stat-card">
      <div class="name">${idx.name}</div>
      <div class="value">${idx.close.toFixed(2)}</div>
      <div class="change ${pctClass(idx.change_pct)}">
        ${formatPct(idx.change_pct)} (${idx.change >= 0 ? '+' : ''}${idx.change.toFixed(2)})
      </div>
    </div>
  `).join('');
}

/** 主要指数柱状图 */
function renderIndexChart(containerId, indices) {
  const el = document.getElementById(containerId);
  if (!el || !indices || typeof echarts === 'undefined') return;

  const chart = echarts.init(el, 'dark');
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 30, top: 30, bottom: 40 },
    xAxis: {
      type: 'category',
      data: indices.map(i => i.name),
      axisLabel: { color: '#8b9cb3' }
    },
    yAxis: {
      type: 'value',
      name: '涨跌幅 %',
      axisLabel: { color: '#8b9cb3', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#2d3a4f' } }
    },
    series: [{
      type: 'bar',
      data: indices.map(i => ({
        value: i.change_pct,
        itemStyle: { color: i.change_pct >= 0 ? '#ef4444' : '#22c55e' }
      })),
      barMaxWidth: 48,
      label: {
        show: true,
        position: 'top',
        formatter: p => formatPct(p.value),
        color: '#e8edf4'
      }
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

/** 涨跌分布饼图 */
function renderDistributionChart(containerId, distribution) {
  const el = document.getElementById(containerId);
  if (!el || !distribution || typeof echarts === 'undefined') return;

  const chart = echarts.init(el, 'dark');
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'item', formatter: '{b}: {c} 家 ({d}%)' },
    legend: { bottom: 10, textStyle: { color: '#8b9cb3' } },
    series: [{
      type: 'pie',
      radius: ['40%', '65%'],
      center: ['50%', '45%'],
      data: distribution.map(d => ({
        name: d.label,
        value: d.count,
        itemStyle: { color: d.color }
      })),
      label: { color: '#e8edf4' }
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

/** 个股排行表格 */
function renderStockTable(tableId, stocks, isGainers) {
  const table = document.getElementById(tableId);
  if (!table || !stocks) return;

  const tbody = table.querySelector('tbody');
  tbody.innerHTML = stocks.map(s => `
    <tr>
      <td>${s.code}</td>
      <td>${s.name}</td>
      <td class="${pctClass(s.change_pct)}">${formatPct(s.change_pct)}</td>
      <td>${s.close.toFixed(2)}</td>
      <td>${s.amount.toFixed(2)}</td>
    </tr>
  `).join('');
}

/** 行业板块横向条形图（供行业报表复用） */
function renderIndustryChart(containerId, industries) {
  const el = document.getElementById(containerId);
  if (!el || !industries || typeof echarts === 'undefined') return;

  const sorted = [...industries].sort((a, b) => a.change_pct - b.change_pct);
  const chart = echarts.init(el, 'dark');
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 100, right: 40, top: 20, bottom: 20 },
    xAxis: {
      type: 'value',
      axisLabel: { color: '#8b9cb3', formatter: '{value}%' },
      splitLine: { lineStyle: { color: '#2d3a4f' } }
    },
    yAxis: {
      type: 'category',
      data: sorted.map(i => i.name),
      axisLabel: { color: '#8b9cb3' }
    },
    series: [{
      type: 'bar',
      data: sorted.map(i => ({
        value: i.change_pct,
        itemStyle: { color: i.change_pct >= 0 ? '#ef4444' : '#22c55e' }
      })),
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

/** 个股日 K 线 + 均线 */
function renderStockKlineChart(containerId, kline) {
  const el = document.getElementById(containerId);
  if (!el || !kline || !kline.length || typeof echarts === 'undefined') return;

  const dates = kline.map(k => k.date);
  const ohlc = kline.map(k => [k.open, k.close, k.low, k.high]);
  const ma5 = kline.map(k => k.ma5);
  const ma20 = kline.map(k => k.ma20);

  const chart = echarts.init(el, 'dark');
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis', axisPointer: { type: 'cross' } },
    legend: { data: ['K线', 'MA5', 'MA20'], textStyle: { color: '#8b9cb3' }, top: 0 },
    grid: { left: 60, right: 20, top: 40, bottom: 60 },
    xAxis: {
      type: 'category',
      data: dates,
      axisLabel: { color: '#8b9cb3', rotate: 45, fontSize: 10 }
    },
    yAxis: {
      scale: true,
      axisLabel: { color: '#8b9cb3' },
      splitLine: { lineStyle: { color: '#2d3a4f' } }
    },
    dataZoom: [
      { type: 'inside', start: 60, end: 100 },
      { type: 'slider', start: 60, end: 100, bottom: 10, height: 20 }
    ],
    series: [
      {
        name: 'K线',
        type: 'candlestick',
        data: ohlc,
        itemStyle: {
          color: '#ef4444',
          color0: '#22c55e',
          borderColor: '#ef4444',
          borderColor0: '#22c55e'
        }
      },
      { name: 'MA5', type: 'line', data: ma5, smooth: true, lineStyle: { width: 1.5, color: '#fbbf24' }, showSymbol: false },
      { name: 'MA20', type: 'line', data: ma20, smooth: true, lineStyle: { width: 1.5, color: '#3b82f6' }, showSymbol: false }
    ]
  });

  window.addEventListener('resize', () => chart.resize());
}

/** 个股成交量柱状图 */
function renderStockVolumeChart(containerId, kline) {
  const el = document.getElementById(containerId);
  if (!el || !kline || !kline.length || typeof echarts === 'undefined') return;

  const chart = echarts.init(el, 'dark');
  chart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 60, right: 20, top: 20, bottom: 40 },
    xAxis: {
      type: 'category',
      data: kline.map(k => k.date),
      axisLabel: { color: '#8b9cb3', show: false }
    },
    yAxis: {
      axisLabel: { color: '#8b9cb3' },
      splitLine: { lineStyle: { color: '#2d3a4f' } }
    },
    series: [{
      type: 'bar',
      data: kline.map(k => ({
        value: k.volume,
        itemStyle: { color: k.close >= k.open ? '#ef4444' : '#22c55e' }
      })),
      barMaxWidth: 8
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}

/** 个股近期行情表格 */
function renderStockRecentTable(tableId, rows) {
  const table = document.getElementById(tableId);
  if (!table || !rows) return;

  const tbody = table.querySelector('tbody');
  tbody.innerHTML = [...rows].reverse().map(r => `
    <tr>
      <td>${r.date}</td>
      <td>${r.open.toFixed(2)}</td>
      <td>${r.high.toFixed(2)}</td>
      <td>${r.low.toFixed(2)}</td>
      <td>${r.close.toFixed(2)}</td>
      <td>${r.ma5.toFixed(2)}</td>
      <td>${r.ma20.toFixed(2)}</td>
      <td>${(r.volume / 10000).toFixed(0)}万</td>
    </tr>
  `).join('');
}
