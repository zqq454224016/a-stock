/**
 * 盘中实时刷新（轮询 live JSON）
 */

const LIVE_REFRESH_MS = 30000;

function pctClass(v) {
  return v >= 0 ? 'text-up' : 'text-down';
}

function formatPct(v) {
  if (v == null) return '--';
  const sign = v >= 0 ? '+' : '';
  return sign + Number(v).toFixed(2) + '%';
}

function updateLiveStats(live) {
  const q = live.quote;
  const intra = live.intraday;

  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  setText('live-price', q.close.toFixed(2));
  const changeEl = document.getElementById('live-change');
  if (changeEl) {
    changeEl.textContent = `${formatPct(q.change_pct)} (${q.change >= 0 ? '+' : ''}${q.change.toFixed(2)})`;
    changeEl.className = 'change ' + pctClass(q.change_pct);
  }
  setText('live-signal', intra.signal);
  setText('live-volume-ratio', intra.volume_ratio != null ? intra.volume_ratio.toFixed(2) : '--');
  setText('live-change-5m', formatPct(intra.change_5m));
  setText('live-change-15m', formatPct(intra.change_15m));
  setText('live-ma5', intra.ma5_1m != null ? intra.ma5_1m.toFixed(2) : '--');
  setText('live-ma20', intra.ma20_1m != null ? intra.ma20_1m.toFixed(2) : '--');
  setText('live-updated', '盘中更新：' + live.updated_at);

  const badge = document.getElementById('live-badge');
  if (badge) badge.classList.add('live-pulse');
}

let minuteChart = null;

function renderMinuteChart(containerId, bars) {
  const el = document.getElementById(containerId);
  if (!el || !bars || !bars.length || typeof echarts === 'undefined') return;

  if (!minuteChart) minuteChart = echarts.init(el, 'dark');
  minuteChart.setOption({
    backgroundColor: 'transparent',
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: 20, bottom: 30 },
    xAxis: {
      type: 'category',
      data: bars.map(b => b.time),
      axisLabel: { color: '#8b9cb3', fontSize: 10, interval: Math.floor(bars.length / 8) }
    },
    yAxis: {
      scale: true,
      axisLabel: { color: '#8b9cb3' },
      splitLine: { lineStyle: { color: '#2d3a4f' } }
    },
    series: [{
      type: 'line',
      data: bars.map(b => b.close),
      smooth: true,
      lineStyle: { color: '#3b82f6', width: 1.5 },
      areaStyle: { color: 'rgba(59,130,246,0.12)' },
      showSymbol: false
    }]
  });
}

async function fetchLiveData(code) {
  const url = `../../assets/data/stocks/live/${code}.json?t=${Date.now()}`;
  const res = await fetch(url);
  if (!res.ok) throw new Error('live 数据未就绪');
  return res.json();
}

function startLiveRefresh(code, intervalMs = LIVE_REFRESH_MS) {
  const statusEl = document.getElementById('live-status');
  const tick = async () => {
    try {
      const live = await fetchLiveData(code);
      updateLiveStats(live);
      renderMinuteChart('minute-chart', live.minute_bars);
      if (statusEl) {
        statusEl.textContent = '● 实时';
        statusEl.className = 'live-status live-ok';
      }
    } catch (e) {
      if (statusEl) {
        statusEl.textContent = '○ 等待数据（请运行 python quant_system/main.py live）';
        statusEl.className = 'live-status live-wait';
      }
    }
  };

  tick();
  return setInterval(tick, intervalMs);
}
