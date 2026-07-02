/**
 * 盘中看板（自选股汇总，自动刷新 live JSON）
 */

const DASH_REFRESH_MS = 15000;

function pctClass(v) {
  return v >= 0 ? 'text-up' : 'text-down';
}

function formatPct(v) {
  if (v == null || Number.isNaN(v)) return '--';
  const n = Number(v);
  const sign = n >= 0 ? '+' : '';
  return sign + n.toFixed(2) + '%';
}

async function fetchJson(url) {
  const res = await fetch(`${url}?t=${Date.now()}`);
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json();
}

function sessionLabel(session) {
  const map = {
    pre_market: '盘前',
    morning: '上午盘',
    lunch_break: '午休',
    afternoon: '下午盘',
    after_hours: '已收盘',
    closed_holiday: '休市',
  };
  return map[session] || session || '--';
}

function renderCards(stocks) {
  const grid = document.getElementById('live-grid');
  if (!grid) return;
  if (!stocks.length) {
    grid.innerHTML = '<p class="empty-hint">暂无数据，请运行 ./run.sh live 或 ./run.sh mvp</p>';
    return;
  }

  grid.innerHTML = stocks.map(s => {
    const q = s.quote || {};
    const intra = s.intraday || {};
    const chg = q.change_pct != null ? q.change_pct : s.change_pct;
    const close = q.close != null ? q.close : s.close;
    const stale = s.minute_stale ? ' · 分钟线延时' : '';
    const chartId = `chart-${s.code}`;
    return `
    <article class="live-card" data-code="${s.code}">
      <header class="live-card-header">
        <div>
          <a href="../stock/${s.code}.html" class="live-card-title">${s.name || s.code}</a>
          <span class="stock-code">${s.code}</span>
        </div>
        <span class="live-badge">${intra.signal || s.signal || '--'}</span>
      </header>
      <div class="live-card-price ${pctClass(chg)}">${close != null ? Number(close).toFixed(2) : '--'}</div>
      <div class="live-card-change ${pctClass(chg)}">${formatPct(chg)}</div>
      <dl class="live-card-meta">
        <div><dt>量比</dt><dd>${intra.volume_ratio != null ? intra.volume_ratio.toFixed(2) : '--'}</dd></div>
        <div><dt>5分/15分</dt><dd>${formatPct(intra.change_5m)} / ${formatPct(intra.change_15m)}</dd></div>
        <div><dt>MA5/MA20</dt><dd>${intra.ma5_1m != null ? intra.ma5_1m.toFixed(2) : '--'} / ${intra.ma20_1m != null ? intra.ma20_1m.toFixed(2) : '--'}</dd></div>
      </dl>
      <div id="${chartId}" class="live-card-chart"></div>
      <footer class="live-card-foot">更新 ${s.updated_at || '--'}${stale}</footer>
    </article>`;
  }).join('');

  stocks.forEach(s => {
    const bars = (s.minute_bars || []).slice(-60);
    const el = document.getElementById(`chart-${s.code}`);
    if (!el || !bars.length || typeof echarts === 'undefined') return;
    const chart = echarts.init(el, 'dark');
    chart.setOption({
      backgroundColor: 'transparent',
      grid: { left: 4, right: 4, top: 4, bottom: 4 },
      xAxis: { type: 'category', show: false, data: bars.map(b => b.time) },
      yAxis: { type: 'value', show: false, scale: true },
      series: [{
        type: 'line',
        data: bars.map(b => b.close),
        smooth: true,
        showSymbol: false,
        lineStyle: { width: 1.2, color: s.minute_stale ? '#6b7280' : '#3b82f6' },
        areaStyle: { color: 'rgba(59,130,246,0.08)' },
      }],
    });
  });
}

async function loadDashboard() {
  const statusEl = document.getElementById('dash-status');
  try {
    const index = await fetchJson('../../assets/data/stocks/live/index.json');
    const codes = (index.stocks || []).map(s => s.code);
    const details = await Promise.all(
      codes.map(async code => {
        try {
          return await fetchJson(`../../assets/data/stocks/live/${code}.json`);
        } catch {
          const row = (index.stocks || []).find(s => s.code === code);
          return row ? { ...row, quote: { close: row.close, change_pct: row.change_pct } } : null;
        }
      }),
    );
    const stocks = details.filter(Boolean);
    renderCards(stocks);

    const session = stocks[0]?.market_session;
    if (statusEl) {
      statusEl.textContent = `● ${sessionLabel(session)} · 索引更新 ${index.updated_at || '--'}`;
      statusEl.className = 'live-status live-ok';
    }
  } catch (e) {
    if (statusEl) {
      statusEl.textContent = '○ 等待 live 数据（请运行 ./run.sh live --loop）';
      statusEl.className = 'live-status live-wait';
    }
    renderCards([]);
  }
}

function startLiveDashboard(intervalMs = DASH_REFRESH_MS) {
  loadDashboard();
  return setInterval(loadDashboard, intervalMs);
}

if (typeof window !== 'undefined') {
  window.startLiveDashboard = startLiveDashboard;
}
