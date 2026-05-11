/* ── 交易仪表盘 SPA ────────────────────────────────────── */

const API = { base: '' };

// ── utils ──────────────────────────────────────────────────

async function api(path) {
  const r = await fetch(API.base + path);
  const j = await r.json();
  if (j.code !== 0) throw new Error(j.msg || 'API error');
  return j.data;
}

function qs(sel) { return document.querySelector(sel); }
function qsa(sel) { return document.querySelectorAll(sel); }

function fmtTime(t) {
  if (!t) return '-';
  const d = new Date(t);
  const pad = n => String(n).padStart(2, '0');
  return `${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

function fmtFullTime(t) {
  if (!t) return '-';
  const d = new Date(t);
  const pad = n => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())} ${pad(d.getHours())}:${pad(d.getMinutes())}:${pad(d.getSeconds())}`;
}

function pnlClass(v) {
  const n = Number(v);
  if (isNaN(n)) return 'pnl-zero';
  if (n > 0) return 'pnl-pos';
  if (n < 0) return 'pnl-neg';
  return 'pnl-zero';
}

function pnlStr(v) {
  const n = Number(v);
  if (isNaN(n)) return '-';
  return (n > 0 ? '+' : '') + n.toFixed(2);
}

function numStr(v, decimals = 2) {
  const n = Number(v);
  return isNaN(n) ? '-' : n.toFixed(decimals);
}

function statusBadge(s) {
  const map = { FILLED:'green', NEW:'blue', PARTIALLY_FILLED:'yellow', CANCELED:'red', EXPIRED:'gray', REJECTED:'red' };
  const cls = map[s] || 'gray';
  return `<span class="badge badge-${cls}">${s}</span>`;
}

function sideBadge(s) {
  return s === 'BUY'
    ? '<span class="badge badge-green">买入</span>'
    : '<span class="badge badge-red">卖出</span>';
}

// ── nav highlight ──────────────────────────────────────────

function setActiveNav(page) {
  qsa('.nav-link').forEach(el => {
    el.classList.toggle('active', el.dataset.page === page);
  });
}

// ── pages ──────────────────────────────────────────────────

async function renderDashboard() {
  setActiveNav('dashboard');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [d, market, account] = await Promise.all([
      api('/api/dashboard'),
      api('/api/market'),
      api('/api/account'),
    ]);
    const o = d.orders;
    const s = d.strategies;

    const a = o.all_time || {};
    const t = o.today || {};

    // 行情数据
    const ind = market.indicators || {};
    const pos = market.position || {};
    const hasPos = pos.side && pos.size > 0;

    app.innerHTML = `
      <div class="section">
        <div class="section-title">📈 实时行情 <span class="count">BTC/USDT</span></div>
        <div class="row">
          <div class="col-4"><div class="stat-card">
            <div class="label">现货价格</div>
            <div class="value">$${fmtPrice(market.price)}</div>
            <div class="sub ${market.change_24h >= 0 ? 'green' : 'red'}">24h ${market.change_24h >= 0 ? '+' : ''}${market.change_24h}%</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">合约价格</div>
            <div class="value">$${fmtPrice(market.contract_price)}</div>
            <div class="sub">信号: ${renderSignal(market.signal)}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">账户权益 (USDT)</div>
            <div class="value ${pnlClass(account.total_equity - account.total_wallet)}">${fmtNum(account.total_equity)}</div>
            <div class="sub">可用 ${fmtNum(account.total_wallet)} | 未实现盈亏 ${pnlStr(account.unrealized_pnl)}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">持仓</div>
            <div class="value" style="font-size:1rem">${hasPos ? renderSide(pos.side) + ' ' + pos.size.toFixed(3) : '无持仓'}</div>
            <div class="sub">${hasPos ? '入场 ' + fmtPrice(pos.entry_price) + ' | 浮盈 ' + pnlStr(pos.unrealized_pnl) : '-'}</div>
          </div></div>
        </div>
      </div>

      ${ind.price ? `
      <div class="row" style="margin-top:8px">
        <div class="col-4"><div class="stat-card" style="padding:12px 16px">
          <div class="label">ADX</div>
          <div class="value" style="font-size:1.2rem">${ind.adx || '-'}</div>
        </div></div>
        <div class="col-4"><div class="stat-card" style="padding:12px 16px">
          <div class="label">BB位置</div>
          <div class="value" style="font-size:1.2rem">${ind.bb_position || '-'}</div>
        </div></div>
        <div class="col-4"><div class="stat-card" style="padding:12px 16px">
          <div class="label">趋势EMA</div>
          <div class="value" style="font-size:1.2rem">${ind['趋势ema'] || '-'}</div>
        </div></div>
        <div class="col-4"><div class="stat-card" style="padding:12px 16px">
          <div class="label">持仓限制</div>
          <div class="value" style="font-size:1.2rem">${ind.uptrend_block === '1' ? '🔴 限制开多' : ind.uptrend_block === '0' ? '🟢 正常' : '-'}</div>
        </div></div>
      </div>` : ''}

      ${account.positions && account.positions.length ? `
      <div class="section">
        <div class="section-title">📋 当前持仓</div>
        <div class="table-wrap">${renderPositionTable(account.positions)}</div>
      </div>` : ''}

      <div class="row" style="margin-top:16px">
        <div class="col-4"><div class="stat-card">
          <div class="label">总交易次数</div>
          <div class="value">${a.total_trades || 0}</div>
          <div class="sub">今日 ${t.total_trades || 0} 笔</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">总盈亏 (USDT)</div>
          <div class="value ${pnlClass(a.total_pnl)}">${pnlStr(a.total_pnl)}</div>
          <div class="sub">今日 ${pnlStr(t.total_pnl)}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">胜率</div>
          <div class="value blue">${a.win_rate || 0}%</div>
          <div class="sub">${a.wins || 0}胜 / ${a.losses || 0}负</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">活跃策略</div>
          <div class="value">${s.total_enabled || 0}</div>
          <div class="sub">总成交额 ${(a.total_volume || 0).toFixed(2)} USDT</div>
        </div></div>
      </div>

      <div class="row" style="margin-top:8px">
        <div class="col-4"><div class="stat-card">
          <div class="label">最大单笔盈利</div>
          <div class="value green">${pnlStr(a.max_win)}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">最大单笔亏损</div>
          <div class="value red">${pnlStr(a.max_loss)}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">平均盈亏</div>
          <div class="value ${pnlClass(a.avg_pnl)}">${pnlStr(a.avg_pnl)}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">运行时间</div>
          <div class="value" style="font-size:1rem">${d.time ? fmtFullTime(d.time) : '-'}</div>
        </div></div>
      </div>

      <div class="section">
        <div class="section-title">📋 活跃策略 <span class="count">(${s.list.length})</span></div>
        <div class="table-wrap">${renderStrategyTable(s.list)}</div>
      </div>

      <div class="section">
        <div class="section-title">📄 近期订单 <span class="count">(${(o.recent || []).length})</span></div>
        <div class="table-wrap">${renderOrderTable(o.recent || [])}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function fmtPrice(v) {
  if (!v) return '-';
  return Number(v).toLocaleString('en', {minimumFractionDigits: 0, maximumFractionDigits: 0});
}

function fmtNum(v) {
  if (v === null || v === undefined) return '-';
  return Number(v).toFixed(2);
}

function renderSignal(s) {
  if (!s) return '<span class="badge badge-gray">未知</span>';
  if (s.includes('开多')) return '<span class="badge badge-green">🟢 开多</span>';
  if (s.includes('开空')) return '<span class="badge badge-red">🔴 开空</span>';
  if (s.includes('观望')) return '<span class="badge badge-gray">⚪ 观望</span>';
  return `<span class="badge badge-gray">${s}</span>`;
}

function renderSide(s) {
  if (!s) return '-';
  return s === 'LONG' ? '<span class="badge badge-green">多</span>' : '<span class="badge badge-red">空</span>';
}

function renderPositionTable(positions) {
  let html = `<table><thead><tr>
    <th>交易对</th><th>方向</th><th>数量</th><th>入场价</th><th>标记价</th>
    <th>未实现盈亏</th><th>盈亏%</th>
  </tr></thead><tbody>`;
  for (const p of positions) {
    html += `<tr>
      <td>${p.symbol || '-'}</td>
      <td>${renderSide(p.side)}</td>
      <td>${p.size.toFixed(3)}</td>
      <td>${fmtPrice(p.entry_price)}</td>
      <td>${fmtPrice(p.mark_price)}</td>
      <td class="${pnlClass(p.unrealized_pnl)}">${pnlStr(p.unrealized_pnl)}</td>
      <td class="${pnlClass(p.pnl_pct)}">${p.pnl_pct >= 0 ? '+' : ''}${p.pnl_pct}%</td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}

async function renderOrders() {
  setActiveNav('orders');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const params = new URLSearchParams(window.location.search);
    const limit = params.get('limit') || 100;
    const status = params.get('status') || '';
    const side = params.get('side') || '';

    let path = `/api/orders?limit=${limit}`;
    if (status) path += `&status=${status}`;
    if (side) path += `&side=${side}`;

    const [orders, stats] = await Promise.all([
      api(path),
      api('/api/orders/stats'),
    ]);

    app.innerHTML = `
      <div class="row">
        <div class="col-4"><div class="stat-card">
          <div class="label">订单总数</div>
          <div class="value">${stats.total_trades}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">总盈亏</div>
          <div class="value ${pnlClass(stats.total_pnl)}">${pnlStr(stats.total_pnl)}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">胜率</div>
          <div class="value blue">${stats.win_rate}%</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">成交额</div>
          <div class="value">${(stats.total_volume || 0).toFixed(2)}</div>
        </div></div>
      </div>

      <div class="section">
        <div class="section-title">
          📄 订单列表
          <span class="count">(${orders.length})</span>
        </div>
        <div class="filters">
          <select id="filterStatus" onchange="applyOrderFilter()">
            <option value="">全部状态</option>
            <option value="FILLED" ${status==='FILLED'?'selected':''}>成交</option>
            <option value="NEW" ${status==='NEW'?'selected':''}>新单</option>
            <option value="PARTIALLY_FILLED" ${status==='PARTIALLY_FILLED'?'selected':''}>部分成交</option>
            <option value="CANCELED" ${status==='CANCELED'?'selected':''}>已撤销</option>
          </select>
          <select id="filterSide" onchange="applyOrderFilter()">
            <option value="">全部方向</option>
            <option value="BUY" ${side==='BUY'?'selected':''}>买入</option>
            <option value="SELL" ${side==='SELL'?'selected':''}>卖出</option>
          </select>
          <span style="color:#8b949e;font-size:.85rem;align-self:center">最近 ${limit} 条</span>
        </div>
        <div class="table-wrap">${renderOrderTable(orders)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function applyOrderFilter() {
  const status = qs('#filterStatus').value;
  const side = qs('#filterSide').value;
  const params = new URLSearchParams();
  if (status) params.set('status', status);
  if (side) params.set('side', side);
  const q = params.toString();
  const url = '/orders' + (q ? '?' + q : '');
  history.pushState({}, '', url);
  renderOrders();
}

async function renderSimOrders() {
  setActiveNav('sim-orders');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const params = new URLSearchParams(window.location.search);
    const limit = params.get('limit') || 100;
    const signalType = params.get('signal_type') || '';

    let path = `/api/sim-orders?limit=${limit}`;
    if (signalType) path += `&signal_type=${signalType}`;

    const rows = await api(path);

    // 按信号类型分组统计
    const stats = { strategy_signal: 0, buy_alert: 0 };
    rows.forEach(r => { if (stats[r.signal_type] !== undefined) stats[r.signal_type]++; });

    app.innerHTML = `
      <div class="row">
        <div class="col-6"><div class="stat-card">
          <div class="label">策略信号</div>
          <div class="value blue">${stats.strategy_signal}</div>
        </div></div>
        <div class="col-6"><div class="stat-card">
          <div class="label">买入预警</div>
          <div class="value green">${stats.buy_alert}</div>
        </div></div>
      </div>

      <div class="section">
        <div class="section-title">
          📋 模拟交易记录
          <span class="count">(${rows.length})</span>
        </div>
        <div class="filters">
          <select id="filterSignalType" onchange="applySimFilter()">
            <option value="">全部类型</option>
            <option value="strategy_signal" ${signalType==='strategy_signal'?'selected':''}>策略信号</option>
            <option value="buy_alert" ${signalType==='buy_alert'?'selected':''}>买入预警</option>
          </select>
          <span style="color:#8b949e;font-size:.85rem;align-self:center">最近 ${limit} 条</span>
        </div>
        <div class="table-wrap">${renderSimTable(rows)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function applySimFilter() {
  const t = qs('#filterSignalType').value;
  const params = new URLSearchParams();
  if (t) params.set('signal_type', t);
  const q = params.toString();
  history.pushState({}, '', '/sim-orders' + (q ? '?' + q : ''));
  renderSimOrders();
}

function renderSimTable(rows) {
  if (!rows || !rows.length) return '<div class="empty">暂无记录</div>';
  const h = (s) => s ? s.replace(/</g,'&lt;').replace(/>/g,'&gt;') : '-';
  return `<table class="table"><thead><tr>
    <th>#</th><th>时间</th><th>类型</th><th>方向</th><th>价格</th><th>策略</th><th>备注</th>
  </tr></thead><tbody>
    ${rows.map(r => `<tr>
      <td>${r.id}</td>
      <td>${fmtFullTime(r.created_at)}</td>
      <td><span class="badge ${r.signal_type === 'buy_alert' ? 'badge-green' : 'badge-blue'}">${r.signal_type === 'buy_alert' ? '预警' : '策略'}</span></td>
      <td>${sideBadge(r.side)} ${r.position_side || ''}</td>
      <td>${r.price ? parseFloat(r.price).toFixed(2) : '-'}</td>
      <td>${h(r.strategy_name)}</td>
      <td style="max-width:300px;overflow:hidden;text-overflow:ellipsis">${h(r.msg)}</td>
    </tr>`).join('')}
  </tbody></table>`;
}

async function renderStrategies() {
  setActiveNav('strategies');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const strats = await api('/api/strategies?enabled=false');
    app.innerHTML = `
      <div class="section">
        <div class="section-title">📋 策略列表 <span class="count">(${strats.length})</span></div>
        <div class="table-wrap">${renderStrategyTable(strats, true)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

// ── table renderers ────────────────────────────────────────

function renderOrderTable(orders) {
  if (!orders || !orders.length) return '<div class="empty">暂无订单记录</div>';
  let html = `<table>
    <thead><tr>
      <th>ID</th><th>时间</th><th>交易对</th><th>方向</th><th>状态</th>
      <th>数量</th><th>成交均价</th><th>金额(U)</th><th>盈亏</th><th>策略</th><th>模式</th>
    </tr></thead><tbody>`;
  for (const o of orders) {
    const qty = o.executed_qty || o.orig_qty || 0;
    const avgP = o.avg_price || o.price || 0;
    const vol = o.cum_quote || 0;
    html += `<tr class="clickable" onclick="showOrder(${o.id})">
      <td>${o.id}</td>
      <td>${fmtTime(o.created_at)}</td>
      <td>${o.symbol || '-'}</td>
      <td>${sideBadge(o.side)}</td>
      <td>${statusBadge(o.status)}</td>
      <td>${typeof qty === 'number' ? qty.toFixed(6) : qty}</td>
      <td>${typeof avgP === 'number' ? avgP.toFixed(2) : avgP}</td>
      <td>${typeof vol === 'number' ? vol.toFixed(2) : vol}</td>
      <td class="${pnlClass(o.pnl)}">${pnlStr(o.pnl)}</td>
      <td>${o.strategy_name || '-'}</td>
      <td>${o.paper_trading ? '模拟' : '实盘'}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}

function renderStrategyTable(strats) {
  if (!strats || !strats.length) return '<div class="empty">暂无策略</div>';
  let html = `<table>
    <thead><tr>
      <th>ID</th><th>名称</th><th>类型</th><th>交易对</th><th>周期</th>
      <th>杠杆</th><th>仓位(U)</th><th>止盈</th><th>止损</th>
      <th>模式</th><th>状态</th>
    </tr></thead><tbody>`;
  for (const s of strats) {
    const tp = ((s.min_profit_rate || 0) * 100).toFixed(1) + '%';
    const sl = ((s.max_loss_rate || 0) * 100).toFixed(1) + '%';
    html += `<tr class="clickable" onclick="navigate('/strategy/${s.id}')">
      <td>${s.id}</td>
      <td><strong>${s.name || '-'}</strong></td>
      <td><span class="badge badge-blue">${s.strategy_type}</span></td>
      <td>${s.symbol || '-'}</td>
      <td>${s.timeframe || '-'}</td>
      <td>${s.leverage || '-'}x</td>
      <td>${s.max_position_usdt || 0}</td>
      <td>${tp}</td>
      <td>${sl}</td>
      <td>${s.paper_trading ? '<span class="badge badge-yellow">模拟</span>' : '<span class="badge badge-green">实盘</span>'}</td>
      <td>${s.enabled ? '<span class="badge badge-green">启用</span>' : '<span class="badge badge-gray">禁用</span>'}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}

// ── modal ──────────────────────────────────────────────────

async function showOrder(orderId) {
  const overlay = qs('#modalOverlay');
  const title = qs('#modalTitle');
  const body = qs('#modalBody');
  title.textContent = '订单 #' + orderId;
  body.innerHTML = '<div class="loading" style="padding:20px">加载中...</div>';
  overlay.classList.add('show');

  try {
    const o = await api(`/api/orders/${orderId}`);
    body.innerHTML = `
      <div class="detail-grid">
        <span class="key">订单ID</span><span class="val">${o.id}</span>
        <span class="key">币安单号</span><span class="val">${o.binance_order_id}</span>
        <span class="key">交易对</span><span class="val">${o.symbol || '-'}</span>
        <span class="key">方向</span><span class="val">${sideBadge(o.side)} ${o.position_side || ''}</span>
        <span class="key">类型</span><span class="val">${o.order_type || '-'}</span>
        <span class="key">状态</span><span class="val">${statusBadge(o.status)}</span>
        <span class="key">价格</span><span class="val">${o.price || '-'}</span>
        <span class="key">成交均价</span><span class="val">${o.avg_price || '-'}</span>
        <span class="key">原始数量</span><span class="val">${o.orig_qty || '-'}</span>
        <span class="key">成交数量</span><span class="val">${o.executed_qty || '-'}</span>
        <span class="key">成交金额</span><span class="val">${o.cum_quote || '-'} USDT</span>
        <span class="key">杠杆</span><span class="val">${o.leverage || '-'}x</span>
        <span class="key">策略</span><span class="val">${o.strategy_name || '-'}</span>
        <span class="key">模式</span><span class="val">${o.paper_trading ? '模拟' : '实盘'}</span>
        <span class="key">盈亏</span><span class="val ${pnlClass(o.pnl)}"><strong>${pnlStr(o.pnl)} USDT</strong></span>
        <span class="key">创建时间</span><span class="val">${fmtFullTime(o.created_at)}</span>
        <span class="key">更新时间</span><span class="val">${fmtFullTime(o.updated_at)}</span>
      </div>
    `;
  } catch (e) {
    body.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function closeModal() {
  qs('#modalOverlay').classList.remove('show');
}

// ── strategy description renderer ───────────────────────────

function renderStrategyDesc(desc) {
  if (!desc || !desc.title) return '';
  let html = `
    <div class="section">
      <div class="section-title">📖 ${desc.title}</div>
      <div class="desc-card">
        <div class="desc-summary">${desc.summary || ''}</div>
        ${(desc.conditions || []).map(c => `
          <div class="desc-group">
            <div class="desc-group-title">▸ ${c.group}</div>
            <ul class="desc-list">
              ${c.items.map(i => `<li>${i}</li>`).join('')}
            </ul>
          </div>
        `).join('')}
        ${desc.params_desc ? `
          <div class="desc-group">
            <div class="desc-group-title">▸ 当前参数</div>
            <div class="params-wrap">
              ${Object.entries(desc.params_desc).map(([k, v]) => `<span><strong>${k}</strong>: ${v}</span>`).join('')}
            </div>
          </div>
        ` : ''}
      </div>
    </div>`;
  return html;
}

// ── strategy detail ───────────────────────────────────────

async function renderStrategyDetail(strategyId) {
  setActiveNav('strategies');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [strat, analysis] = await Promise.all([
      api(`/api/strategies/${strategyId}`),
      api(`/api/analysis/${strategyId}`),
    ]);

    const sum = analysis.summary || {};
    const daily = analysis.daily || [];

    const tp = ((strat.min_profit_rate || 0) * 100).toFixed(1);
    const sl = ((strat.max_loss_rate || 0) * 100).toFixed(1);

    app.innerHTML = `
      <div style="margin-bottom:16px">
        <a href="/strategies" onclick="event.preventDefault();navigate('/strategies')" style="color:#8b949e;font-size:.9rem">&larr; 返回策略列表</a>
      </div>

      <div class="section-title" style="font-size:1.15rem">📋 ${strat.name || '策略'} <span class="badge badge-blue" style="font-size:.8rem;vertical-align:middle">${strat.strategy_type}</span></div>

      <div class="row">
        <div class="col-4"><div class="stat-card">
          <div class="label">交易对</div>
          <div class="value" style="font-size:1.1rem">${strat.symbol || '-'}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">周期 / 杠杆</div>
          <div class="value" style="font-size:1.1rem">${strat.timeframe || '-'} / ${strat.leverage || '-'}x</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">仓位 / 止盈止损</div>
          <div class="value" style="font-size:1rem">${strat.max_position_usdt || 0}U / ${tp}% / ${sl}%</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">模式</div>
          <div class="value" style="font-size:1rem">${strat.paper_trading ? '<span class="badge badge-yellow">模拟</span>' : '<span class="badge badge-green">实盘</span>'}</div>
        </div></div>
      </div>

      ${strat.description ? renderStrategyDesc(strat.description) : ''}

      <div class="section">
        <div class="section-title">📊 实盘分析</div>
        <div class="row">
          <div class="col-4"><div class="stat-card">
            <div class="label">累计交易</div>
            <div class="value">${sum.total_trades || 0}</div>
            <div class="sub">活跃 ${sum.days_active || 0} 天</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">累计盈亏 (USDT)</div>
            <div class="value ${pnlClass(sum.total_pnl)}">${pnlStr(sum.total_pnl)}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">胜率</div>
            <div class="value blue">${sum.win_rate || 0}%</div>
            <div class="sub">${sum.total_wins || 0}胜 / ${sum.total_losses || 0}负</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">累计成交额</div>
            <div class="value" style="font-size:1.15rem">${(sum.total_volume || 0).toFixed(2)}</div>
          </div></div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">📈 逐日分析 <span class="count">(${daily.length} 天)</span></div>
        ${daily.length ? renderAnalysisTable(daily) : '<div class="empty">暂无分析数据（有成交订单后自动生成）</div>'}
      </div>

      <div class="section">
        <div class="section-title">📄 订单记录</div>
        <div id="strategyOrders">加载中...</div>
      </div>
    `;

    // 异步加载该策略的订单
    try {
      const odata = await api(`/api/orders?limit=100&paper_trading=0`);
      const filtered = odata.filter(o => o.strategy_name === strat.strategy_type || o.strategy_name === strat.name);
      qs('#strategyOrders').innerHTML = filtered.length
        ? '<div class="table-wrap">' + renderOrderTable(filtered) + '</div>'
        : '<div class="empty">暂无实盘订单</div>';
    } catch (e) {
      qs('#strategyOrders').innerHTML = '<div class="empty">加载失败</div>';
    }

  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function renderAnalysisTable(daily) {
  let html = `<div class="table-wrap"><table>
    <thead><tr>
      <th>日期</th><th>交易次数</th><th>胜</th><th>负</th><th>胜率</th>
      <th>总盈亏</th><th>平均盈亏</th><th>最大盈利</th><th>最大亏损</th><th>成交额</th>
    </tr></thead><tbody>`;
  for (const r of daily) {
    html += `<tr>
      <td>${r.period_start || '-'}</td>
      <td>${r.total_trades}</td>
      <td class="green">${r.wins}</td>
      <td class="red">${r.losses}</td>
      <td class="blue">${r.win_rate}%</td>
      <td class="${pnlClass(r.total_pnl)}">${pnlStr(r.total_pnl)}</td>
      <td class="${pnlClass(r.avg_pnl)}">${pnlStr(r.avg_pnl)}</td>
      <td class="green">${pnlStr(r.max_win)}</td>
      <td class="red">${pnlStr(r.max_loss)}</td>
      <td>${(r.total_volume || 0).toFixed(2)}</td>
    </tr>`;
  }
  html += '</tbody></table></div>';
  return html;
}

// ── router ─────────────────────────────────────────────────

function navigate(path) {
  history.pushState({}, '', path);
  route();
}

function route() {
  const path = window.location.pathname;
  if (path === '/' || path === '') renderDashboard();
  else if (path === '/orders') renderOrders();
  else if (path === '/strategies') renderStrategies();
  else if (path === '/sim-orders') renderSimOrders();
  else if (/^\/strategy\/(\d+)$/.test(path)) {
    const id = path.match(/^\/strategy\/(\d+)$/)[1];
    renderStrategyDetail(id);
  } else renderDashboard();
}

// ── init ───────────────────────────────────────────────────

window.addEventListener('popstate', route);
document.addEventListener('DOMContentLoaded', route);
