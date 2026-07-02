/**
 * 盘中实时刷新（轮询 live JSON，过期时回退 stocks JSON 现价）
 */

const LIVE_REFRESH_MS = 30000;
const LIVE_REFRESH_OPEN_MS = 15000;
const STALE_SEC = 120;

function pctClass(v) {
  return v >= 0 ? 'text-up' : 'text-down';
}

function formatPct(v) {
  if (v == null) return '--';
  const sign = v >= 0 ? '+' : '';
  return sign + Number(v).toFixed(2) + '%';
}

function parseUpdatedAt(s) {
  if (!s) return null;
  const d = new Date(String(s).replace(' ', 'T'));
  return isNaN(d.getTime()) ? null : d;
}

function ageSeconds(updatedAt) {
  const d = parseUpdatedAt(updatedAt);
  if (!d) return Infinity;
  return (Date.now() - d.getTime()) / 1000;
}

function isSessionOpen(session) {
  return session === 'morning' || session === 'afternoon';
}

function updateLiveStats(live) {
  const q = live.quote || {};
  const intra = live.intraday || {};

  const setText = (id, text) => {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  };

  if (q.close != null) setText('live-price', Number(q.close).toFixed(2));
  const changeEl = document.getElementById('live-change');
  if (changeEl && q.close != null) {
    changeEl.textContent = `${formatPct(q.change_pct)} (${q.change >= 0 ? '+' : ''}${Number(q.change).toFixed(2)})`;
    changeEl.className = 'change ' + pctClass(q.change_pct);
  }
  setText('live-signal', intra.signal || '--');
  setText('live-volume-ratio', intra.volume_ratio != null ? intra.volume_ratio.toFixed(2) : '--');
  setText('live-change-5m', formatPct(intra.change_5m));
  setText('live-change-15m', formatPct(intra.change_15m));
  setText('live-ma5', intra.ma5_1m != null ? intra.ma5_1m.toFixed(2) : '--');
  setText('live-ma20', intra.ma20_1m != null ? intra.ma20_1m.toFixed(2) : '--');

  let note = '更新：' + (live.updated_at || '--');
  if (live.minute_stale) {
    note += ` · 分钟线截至 ${live.minute_trade_date || '未知'}`;
  }
  setText('live-updated', note);

  const badge = document.getElementById('live-badge');
  if (badge) {
    badge.textContent = live.minute_stale ? '延时' : 'LIVE';
    badge.classList.add('live-pulse');
  }
}

let minuteChart = null;

function renderMinuteChart(containerId, bars, minuteStale) {
  const el = document.getElementById(containerId);
  if (!el || typeof echarts === 'undefined') return;
  if (!bars || !bars.length) {
    if (minuteChart) minuteChart.clear();
    return;
  }

  if (!minuteChart) minuteChart = echarts.init(el, 'dark');
  minuteChart.setOption({
    backgroundColor: 'transparent',
    title: minuteStale ? {
      text: '分钟线非当日（仅供参考）',
      left: 'center',
      top: 0,
      textStyle: { color: '#fbbf24', fontSize: 11 }
    } : undefined,
    tooltip: { trigger: 'axis' },
    grid: { left: 50, right: 20, top: minuteStale ? 28 : 20, bottom: 30 },
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
      lineStyle: { color: minuteStale ? '#6b7280' : '#3b82f6', width: 1.5 },
      areaStyle: { color: minuteStale ? 'rgba(107,114,128,0.1)' : 'rgba(59,130,246,0.12)' },
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

async function fetchStockSpotFallback(code) {
  const url = `../../assets/data/stocks/${code}.json?t=${Date.now()}`;
  const res = await fetch(url);
  if (!res.ok) return null;
  const data = await res.json();
  if (!data.quote) return null;
  return data;
}

function mergeSpotFallback(live, stock) {
  if (!stock || !stock.quote) return live;
  const merged = { ...live, quote: { ...live.quote, ...stock.quote } };
  merged.quote_source = stock.quote_source || 'spot_fallback';
  merged.updated_at = stock.updated_at || live.updated_at;
  merged._spot_fallback = true;
  return merged;
}

function setLiveStatus(statusEl, live, stale) {
  if (!statusEl) return;
  if (stale) {
    statusEl.textContent = '○ 数据滞后（请运行 ./run.sh live --loop）';
    statusEl.className = 'live-status live-wait';
    return;
  }
  if (live.minute_stale) {
    statusEl.textContent = '◐ 现价实时 · 分钟线延时';
    statusEl.className = 'live-status live-wait';
    return;
  }
  if (live._spot_fallback) {
    statusEl.textContent = '◐ 现价来自个股缓存';
    statusEl.className = 'live-status live-wait';
    return;
  }
  statusEl.textContent = '● 实时';
  statusEl.className = 'live-status live-ok';
}

function startLiveRefresh(code, intervalMs = LIVE_REFRESH_MS) {
  const statusEl = document.getElementById('live-status');

  const tick = async () => {
    try {
      let live = await fetchLiveData(code);
      const age = ageSeconds(live.updated_at);
      const open = isSessionOpen(live.market_session);
      const stale = open && age > STALE_SEC;

      if (stale || (live.minute_stale && open)) {
        const stock = await fetchStockSpotFallback(code);
        if (stock) live = mergeSpotFallback(live, stock);
      }

      updateLiveStats(live);
      renderMinuteChart('minute-chart', live.minute_bars, live.minute_stale);
      setLiveStatus(statusEl, live, stale && !live._spot_fallback);
    } catch (e) {
      try {
        const stock = await fetchStockSpotFallback(code);
        if (stock) {
          const live = mergeSpotFallback({ quote: {}, intraday: {}, minute_bars: [], minute_stale: true }, stock);
          updateLiveStats(live);
          setLiveStatus(statusEl, live, false);
          return;
        }
      } catch (_) { /* ignore */ }
      if (statusEl) {
        statusEl.textContent = '○ 等待数据（请运行 ./run.sh live --loop）';
        statusEl.className = 'live-status live-wait';
      }
    }
  };

  tick();
  return setInterval(tick, intervalMs);
}
