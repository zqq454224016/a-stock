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
      label: {
        show: true,
        position: 'right',
        formatter: p => formatPct(p.value),
        color: '#e8edf4'
      }
    }]
  });

  window.addEventListener('resize', () => chart.resize());
}
