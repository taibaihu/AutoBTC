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

function buildBtcAnalysis(market, trend, kdjData) {
  var price = market ? market.price : 0;
  var chg = market ? (market.change_24h || 0) : 0;
  var sentiment = "--", sentimentColor = "var(--text-muted)";
  var summaryLines = [];
  var tfScores = [];
  var totalScore = 0, scoreCount = 0;

  if (trend && trend.timeframes) {
    var tfList = Object.entries(trend.timeframes);
    for (var ti = 0; ti < tfList.length; ti++) {
      var pair = tfList[ti];
      var tf = pair[0], data = pair[1];
      var d = data.detail || {};
      tfScores.push(tf + ": " + data.score + "分");
      totalScore += data.score;
      scoreCount++;
    }
    if (scoreCount > 0) {
      var avgScore = Math.round(totalScore / scoreCount);
      if (avgScore >= 65) { sentiment = "🟢 偏乐观"; sentimentColor = "var(--green)"; }
      else if (avgScore >= 40) { sentiment = "🟡 中性震荡"; sentimentColor = "#d29922"; }
      else { sentiment = "🔴 偏悲观"; sentimentColor = "var(--red)"; }

      // 生成详细总结
      if (scoreCount >= 3) {
        var p5 = trend.timeframes["5m"], p15 = trend.timeframes["15m"], p1h = trend.timeframes["1h"];
        summaryLines.push("多周期趋势评分 — 5m:" + p5.score + "/15m:" + p15.score + "/1h:" + p1h.score);
        // 趋势一致性
        var bullCount = (p5.score >= 50 ? 1 : 0) + (p15.score >= 50 ? 1 : 0) + (p1h.score >= 50 ? 1 : 0);
        var bearCount = (p5.score < 40 ? 1 : 0) + (p15.score < 40 ? 1 : 0) + (p1h.score < 40 ? 1 : 0);
        if (bullCount >= 2) summaryLines.push("趋势方向: 多头占优，均线" + (avgScore >= 60 ? "多头排列" : "震荡偏多"));
        else if (bearCount >= 2) summaryLines.push("趋势方向: 空头占优，注意回调风险");
        else summaryLines.push("趋势方向: 多空博弈，方向不明");

        // 细项分析
        var ema1h = p1h.detail.s_ema || 50;
        var mom1h = p1h.detail.s_mom || 50;
        var macd1h = p1h.detail.macd_hist || 0;
        summaryLines.push("EMA趋势力度" + (ema1h >= 70 ? "强劲(↑" + ema1h + ")" : ema1h >= 50 ? "温和(" + ema1h + ")" : "偏弱(" + ema1h + ")"));
        summaryLines.push("动量" + (mom1h >= 60 ? "偏强(↑" + mom1h + ") 有上攻动能" : mom1h >= 40 ? "中性(" + mom1h + ") 观望" : "减弱(↓" + mom1h + ") 需警惕"));
        summaryLines.push("MACD柱" + (macd1h > 0 ? "正值(↑" + macd1h.toFixed(1) + ") 多头发散" : "负值(↓" + Math.abs(macd1h).toFixed(1) + ") 空头压力"));

        // BB位置
        var bb5 = p5.detail.bb_pos || 0.5;
        var bbPosText = bb5 >= 0.8 ? "上轨附近 ⚠️偏高" : bb5 >= 0.3 ? "中轨区域" : "下轨附近 偏低";
        summaryLines.push("布林位置: " + bbPosText + " (5m: " + (bb5 * 100).toFixed(0) + "%)");

        // RSI
        var rsi5 = p5.detail.rsi || 50;
        var rsi1h = p1h.detail.rsi || 50;
        summaryLines.push("RSI: 5m=" + rsi5.toFixed(1) + " 1h=" + rsi1h.toFixed(1) + (rsi1h > 70 ? " ⚠️超买区" : rsi1h < 30 ? " ⚠️超卖区" : " 正常区间"));
      }
    }
  }

  if (kdjData) {
    summaryLines.push("KDJ: K=" + kdjData.k.toFixed(1) + " D=" + kdjData.d.toFixed(1) + " J=" + kdjData.j.toFixed(1) +
      (kdjData.golden_cross ? " 🟢金叉信号" : kdjData.death_cross ? " 🔴死叉信号" : ""));
  }

  var chgStr = (chg >= 0 ? "+" : "") + chg + "%";
  var chgColor = chg >= 0 ? "var(--green)" : "var(--red)";
  summaryLines.unshift('24h涨跌: <span style="color:' + chgColor + '">' + chgStr + '</span> | 当前 $' + (price ? fmtPrice(price) : '-'));

  if (summaryLines.length === 0) summaryLines.push("等待行情数据更新...");

  // 转为平铺描述，用分隔符连接
  var flatText = "";
  if (summaryLines.length > 0) {
    for (var si = 0; si < summaryLines.length; si++) {
      if (si > 0 && si % 2 === 0) flatText += '<span class="btc-sep">|</span>';
      flatText += '<span>' + summaryLines[si] + '</span>';
    }
  } else {
    flatText = '<span>等待行情数据更新...</span>';
  }

  return {
    sentiment: sentiment,
    sentimentColor: sentimentColor,
    scoreText: tfScores.length ? tfScores.join(" | ") : "---",
    text: flatText
  };
}

async function renderDashboard() {
  setActiveNav('dashboard');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [market, account, baOrders, trend, kdjData, bbExec, bbStats, prExec, prScan, prBal] = await Promise.all([
      api('/api/market'),
      api('/api/account'),
      api('/api/binance-ai/orders').catch(() => null),
      api('/api/trend-score').catch(() => null),
      api('/api/kdj-monitor').catch(() => null),
      api('/api/bb-ride-execution'),
      api('/api/bb-ride-execution/stats'),
      api('/api/bb-ride-execution/push-retest'),
      api('/api/bb-ride/push-retest').catch(() => null),
      api('/api/push-retest/balance').catch(() => null),
    ]);

    // BB Ride 数据
    const bbPositions = Object.values((bbExec && bbExec.positions) || {});
    const bbOrders = Object.values((bbExec && bbExec.orders) || {});
    const bbClosed = (bbExec && bbExec.closed_positions) || [];
    const bbStatsData = (bbExec && bbExec.total_stats) || {};
    const bbTotalPnl = bbStatsData.pnl || 0;
    const bbTotalTrades = (bbStats && bbStats.total_closed) || bbStatsData.trades || bbClosed.length;
    const bbTotalWins = (bbStats && bbStats.total_wins) || bbStatsData.wins || 0;
    const bbWinRate = bbTotalTrades > 0 ? (bbTotalWins / bbTotalTrades * 100).toFixed(1) : '-';

    // 推土机数据
    const prPositions = Object.values((prExec && prExec.positions) || {});
    const prOrders = Object.values((prExec && prExec.orders) || {});
    const prClosed = (prExec && prExec.closed_positions) || [];
    const prStats = (prExec && prExec.total_stats) || {};
    const prTotalPnl = prStats.pnl || 0;
    const prTotalTrades = prStats.trades || prClosed.length;
    const prTotalWins = prStats.wins || 0;
    const prWinRate = prTotalTrades > 0 ? (prTotalWins / prTotalTrades * 100).toFixed(1) : '-';

    const ind = market.indicators || {};
    const pos = market.position || {};
    const hasPos = pos.side && pos.size > 0;

    // ── BTC 行情分析总结 ──
    // ── BTC 行情分析总结 ──
    var btcSummary = buildBtcAnalysis(market, trend, kdjData);

    app.innerHTML = [
      '<div class="section">',
      '  <div class="section-title">📈 BTC/USDT 实时行情 + AI 分析 <span class="count">24h ' + (market.change_24h >= 0 ? '+' : '') + market.change_24h + '%</span></div>',
      '  <div class="row">',
      '    <div class="col-6"><div class="stat-card"><div class="label">现货价格</div><div class="value">$' + fmtPrice(market.price) + '</div><div class="sub ' + (market.change_24h >= 0 ? 'green' : 'red') + '">24h ' + (market.change_24h >= 0 ? '+' : '') + market.change_24h + '%</div></div></div>',
      '    <div class="col-6"><div class="stat-card"><div class="label">合约价格</div><div class="value">$' + fmtPrice(market.contract_price) + '</div><div class="sub">信号: ' + renderSignal(market.signal) + '</div></div></div>',
      '  </div>',
      '  <div class="btc-analysis-box">',
      '    <div class="btc-analysis-summary">' + btcSummary.text + '</div>',
      '  </div>',
      '</div>'].join('\n');



    // 当前持仓（已合并到行情卡片）

    // 趋势打分
    if (trend && trend.timeframes) {
      window._trendScores = true;
      var tfHtml = '<div class="row">';
      for (var ti = 0; ti < Object.entries(trend.timeframes).length; ti++) {
        var pair = Object.entries(trend.timeframes)[ti];
        var tf = pair[0], data = pair[1];
        var s = data.score || 50;
        var d = data.detail || {};
        var cls = s >= 70 ? "green" : s >= 40 ? "" : "red";
        var label = {"5m":"5分钟","15m":"15分钟","1h":"1小时"}[tf] || tf;
        var clr = cls === "green" ? "#3fb950" : cls === "red" ? "#f85149" : "#d29922";
        tfHtml += '<div class="col-4"><div class="stat-card" style="text-align:center">' +
          '<div class="label">' + label + '</div>' +
          '<div class="value" style="font-size:2rem;font-weight:700;color:' + clr + '">' + s + '</div>' +
          '<div class="sub">' + (s >= 70 ? "🟢 乐观" : s >= 40 ? "🟡 中性" : "🔴 悲观") + '</div>' +
          '<div style="font-size:.75rem;color:#8b949e;margin-top:6px">' +
          "EMA" + d.s_ema + " 动量" + d.s_mom + " RSI" + d.s_rsi + " BB" + d.s_bb + " MACD" + d.s_macd + " 量" + d.s_vol +
          "</div></div></div>";
      }
      tfHtml += "</div>";
      app.innerHTML += '<div class="section"><div class="section-title">📊 趋势打分 <span class="count">5m / 15m / 1h</span>' +
        '<a href="/trend-score-page" style="float:right;font-size:.8rem;color:#58a6ff;text-decoration:none;line-height:1.8rem">📈 趋势打分</a></div>' + tfHtml + "</div>";
    }

    // 骑行 & 推土机 统计卡片
    app.innerHTML += [
      '<div class="row" style="margin-top:8px">',
      '  <div class="col-6"><div class="section-title" style="font-size:1rem;margin-bottom:8px">🏍️ 骑行策略 (币安)</div>',
      '    <div class="row">',
      '      <div class="col-3"><div class="stat-card"><div class="label">持仓</div><div class="value" style="font-size:1.2rem">' + bbPositions.length + '</div><div class="sub">多' + bbPositions.filter(function(p){return p.direction==="LONG"}).length + ' / 空' + bbPositions.filter(function(p){return p.direction==="SHORT"}).length + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">挂单</div><div class="value blue" style="font-size:1.2rem">' + bbOrders.length + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">总盈亏</div><div class="value ' + pnlClass(bbTotalPnl) + '" style="font-size:1.2rem">' + pnlStr(bbTotalPnl) + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">胜率</div><div class="value" style="font-size:1.2rem;color:' + (bbWinRate !== "-" && Number(bbWinRate) >= 50 ? "var(--green)" : "var(--red)") + '">' + bbWinRate + '%</div><div class="sub">' + bbTotalWins + '胜 / ' + bbTotalTrades + '单</div></div></div>',
      '    </div>',
      '  </div>',
      '  <div class="col-6"><div class="section-title" style="font-size:1rem;margin-bottom:8px">🚜 推土机策略 (OKX)</div>',
      '    <div class="row">',
      '      <div class="col-3"><div class="stat-card"><div class="label">持仓</div><div class="value" style="font-size:1.2rem">' + prPositions.length + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">挂单</div><div class="value blue" style="font-size:1.2rem">' + prOrders.length + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">总盈亏</div><div class="value ' + pnlClass(prTotalPnl) + '" style="font-size:1.2rem">' + pnlStr(prTotalPnl) + '</div></div></div>',
      '      <div class="col-3"><div class="stat-card"><div class="label">胜率</div><div class="value" style="font-size:1.2rem;color:' + (prWinRate !== "-" && Number(prWinRate) >= 50 ? "var(--green)" : "var(--red)") + '">' + prWinRate + '%</div><div class="sub">' + prTotalWins + '胜 / ' + prTotalTrades + '单</div></div></div>',
      '    </div>',
      '  </div>',
      '</div>'
    ].join("\n");

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function fmtPrice(v) {
  if (!v) return '-';
  return Number(v).toLocaleString('en', {minimumFractionDigits: 0, maximumFractionDigits: 0});
}

function fmtCryptoPrice(v) {
  if (!v || isNaN(v)) return '-';
  const n = Number(v);
  if (n >= 1) return n.toFixed(4);
  if (n >= 0.01) return n.toFixed(4);
  if (n >= 0.0001) return n.toFixed(6);
  return n.toFixed(8);
}

function fmtNum(v, d) {
  if (v === null || v === undefined) return '-';
  return Number(v).toFixed(d === undefined ? 2 : d);
}

function fmtDuration(seconds) {
  if (seconds === undefined || seconds === null || isNaN(seconds)) return '-';
  const h = Math.floor(seconds / 3600);
  const m = Math.floor((seconds % 3600) / 60);
  if (h > 0) return h + 'h' + m + 'm';
  return m + 'm';
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









async function renderStrategies() {
  setActiveNav('strategies');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const data = await api('/api/strategy-status');
    var running = data.filter(function(s) { return s.running; });
    var idle = data.filter(function(s) { return !s.running; });

    function statCard(n, cls, lbl, sub) {
      return '<div class="col-3"><div class="stat-card"><div class="label">' + lbl + '</div><div class="value ' + (cls||'') + '" style="font-size:1.4rem">' + n + '</div><div class="sub">' + (sub||'') + '</div></div></div>';
    }

    app.innerHTML = '<div class="row">' +
      statCard(data.length, 'blue', '策略总数', '代码注册库') +
      statCard(running.length, 'green', '运行中', '进程存活') +
      statCard(idle.length, 'red', '未运行', '需手动启动') +
      statCard(data.filter(function(s){return s.enabled;}).length, '', 'DB已启用', '配置中启用') +
    '</div>' +
    (running.length ? '<div class="section"><div class="section-title">🟢 运行中 <span class="count">(' + running.length + ')</span></div>' + running.map(renderStrategyCard).join('') + '</div>' : '') +
    (idle.length ? '<div class="section"><div class="section-title">⚪ 未运行 <span class="count">(' + idle.length + ')</span></div>' + idle.map(renderStrategyCard).join('') + '</div>' : '') +
    '<div style="text-align:center;padding:8px;color:#484f58;font-size:.82rem">每15秒自动刷新</div>';

    if (window._stratTimer) clearTimeout(window._stratTimer);
    window._stratTimer = setTimeout(renderStrategies, 15000);
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function renderStrategyCard(s) {
  var statusColor, statusIcon;
  if (s.running) { statusColor = '#3fb950'; statusIcon = '🟢'; }
  else if (s.enabled) { statusColor = '#d29922'; statusIcon = '🟡'; }
  else { statusColor = '#484f58'; statusIcon = '⚪'; }

  var logStr = '';
  if (s.log) {
    var mtime = new Date(s.log.mtime * 1000);
    var now = Date.now();
    var ageMin = Math.round((now - mtime.getTime()) / 60000);
    var ageStr = ageMin < 1 ? '刚刚' : ageMin < 60 ? ageMin + '分钟前' : Math.round(ageMin/60) + '小时前';
    var lastLine = s.log.last_line || '';
    if (lastLine.length > 15 && lastLine.indexOf(',') > 0) {
      lastLine = lastLine.substring(lastLine.indexOf(',') + 2);
    }
    var sizeStr = s.log.size >= 1048576 ? (s.log.size/1048576).toFixed(1) + 'MB' : (s.log.size/1024).toFixed(1) + 'KB';
    logStr = '<div class="strategy-log" style="margin-top:8px;padding-top:8px;border-top:1px solid #21262d">' +
      '<div style="display:flex;justify-content:space-between;align-items:center">' +
        '<span style="color:#8b949e;font-size:.75rem">📄 ' + s.log.file + ' (' + sizeStr + ')</span>' +
        '<span style="color:' + statusColor + ';font-size:.75rem">' + ageStr + '</span>' +
      '</div>' +
      (lastLine ? '<div style="color:#484f58;font-size:.75rem;margin-top:3px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis" title="' + escHtml(s.log.last_line) + '">' + escHtml(lastLine) + '</div>' : '') +
    '</div>';
  }

  var dbInfo = '';
  if (s.symbol || s.timeframe || s.leverage) {
    dbInfo = '<div style="display:flex;gap:12px;margin-top:6px;flex-wrap:wrap">' +
      (s.symbol ? '<span class="u-meta-sm">📊 ' + s.symbol + '</span>' : '') +
      (s.timeframe ? '<span class="u-meta-sm">⏱ ' + s.timeframe + '</span>' : '') +
      (s.leverage ? '<span class="u-meta-sm">⚡ ' + s.leverage + 'x</span>' : '') +
      '<span class="u-meta-sm">' + (s.paper_trading ? '📝 模拟' : '💵 实盘') + '</span>' +
    '</div>';
  }

  var runInfo = '';
  if (s.running && s.pid) {
    runInfo = '<div style="display:flex;gap:16px;margin-top:4px;font-size:.82rem;color:#8b949e">' +
      '<span>🆔 PID ' + s.pid + '</span>' +
      (s.start_time ? '<span>🚀 启动 ' + s.start_time + '</span>' : '') +
    '</div>';
  }

  return '<div style="background:#161b22;border:1px solid #30363d;border-radius:10px;margin-bottom:10px;padding:14px 18px">' +
    '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">' +
      '<div style="display:flex;align-items:center;gap:10px">' +
        '<span style="width:10px;height:10px;border-radius:50%;background:' + statusColor + ';display:inline-block;flex-shrink:0"></span>' +
        '<div><strong style="color:#e6edf3;font-size:.95rem">' + escHtml(s.name || s.key) + '</strong>' +
        '<span style="color:#8b949e;font-size:.75rem;margin-left:8px">' + s.key + '</span></div>' +
      '</div>' +
      '<span style="font-size:.78rem;color:' + statusColor + '">' + statusIcon + ' ' + (s.running ? '运行中' : (s.enabled ? '已启用·未运行' : '已禁用')) + '</span>' +
    '</div>' +
    (s.description ? '<div style="color:#8b949e;font-size:.82rem;margin-top:4px">' + escHtml(s.description) + '</div>' : '') +
    dbInfo +
    runInfo +
    logStr +
  '</div>';
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

// ── AI 策略卡片（仪表盘用） ──────────────────────────────
function renderAiStrategyCards(aiStrats) {
  return aiStrats.map(a => {
    const statusDot = a.running ? '🟢' : '⚪';
    const runningStr = a.running
      ? '<span class="green">● 运行中</span>'
      : '<span class="u-faint">○ 已停止</span>';
    const ordersHtml = a.orders_count > 0
      ? '<span class="u-meta-sm">📦 ' + a.orders_count + ' 笔挂单</span>'
      : '';
    const posHtml = a.positions_count > 0
      ? '<span style="font-size:.82rem;color:#d29922">💼 ' + a.positions_count + ' 笔持仓</span>'
      : '';
    const pnlHtml = a.closed_count > 0
      ? '<span style="font-size:.82rem;color:' + (a.pnl >= 0 ? '#3fb950' : '#f85149') + '">📊 ' + (a.pnl >= 0 ? '+' : '') + a.pnl + ' USDT (' + a.closed_count + ' 笔已平)</span>'
      : '';
    const links = a.key === 'binance_ai'
      ? '<a href="/binance-ai" style="color:#58a6ff;text-decoration:none;font-size:.82rem">查看详情 →</a>'
      : a.key === 'okx_ai'
        ? '<a href="/okx-ai" style="color:#58a6ff;text-decoration:none;font-size:.82rem">查看详情 →</a>'
        : '';

    return '<div style="background:#161b22;border:1px solid #30363d;border-radius:10px;margin-top:10px;padding:14px 18px">' +
      '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:6px">' +
        '<div style="display:flex;align-items:center;gap:10px">' +
          '<span class="u-fs11">' + statusDot + '</span>' +
          '<div><strong style="color:#e6edf3;font-size:.95rem">🤖 ' + escHtml(a.name) + '</strong>' +
          '<span style="color:#8b949e;font-size:.75rem;margin-left:8px">' + a.key + '</span></div>' +
        '</div>' +
        runningStr +
      '</div>' +
      (a.description ? '<div style="color:#8b949e;font-size:.82rem;margin-top:4px">' + escHtml(a.description) + '</div>' : '') +
      '<div style="display:flex;gap:16px;margin-top:8px;flex-wrap:wrap">' + ordersHtml + posHtml + pnlHtml + '</div>' +
      '<div style="margin-top:6px">' + links + '</div>' +
    '</div>';
  }).join('');
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

      <div class="section-title u-fs115">📋 ${strat.name || '策略'} <span class="badge badge-blue" style="font-size:.8rem;vertical-align:middle">${strat.strategy_type}</span></div>

      <div class="row">
        <div class="col-4"><div class="stat-card">
          <div class="label">交易对</div>
          <div class="value u-fs11">${strat.symbol || '-'}</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">周期 / 杠杆</div>
          <div class="value u-fs11">${strat.timeframe || '-'} / ${strat.leverage || '-'}x</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">仓位 / 止盈止损</div>
          <div class="value u-fs1">${strat.max_position_usdt || 0}U / ${tp}% / ${sl}%</div>
        </div></div>
        <div class="col-4"><div class="stat-card">
          <div class="label">模式</div>
          <div class="value u-fs1">${strat.paper_trading ? '<span class="badge badge-yellow">模拟</span>' : '<span class="badge badge-green">实盘</span>'}</div>
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
            <div class="value u-fs115">${(sum.total_volume || 0).toFixed(2)}</div>
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

// ── AI 仪表盘订单表格 ─────────────────────────────────────
function renderAiDashboardOrders(orders) {
  if (!orders || !orders.length) return '<div class="empty">暂无</div>';
  let html = `<table>
    <thead><tr>
      <th>策略</th><th>币种</th><th>类型</th><th>价格</th><th>数量</th><th>金额</th><th>状态</th>
    </tr></thead><tbody>`;
  for (const o of orders) {
    const typeStr = o._type === 'ai_pos' ? '<span class="badge badge-green">持仓</span>' : '<span class="badge badge-blue">挂单</span>';
    const price = o.price || o.entry_price || 0;
    const qty = o.quantity || 0;
    const amt = (price * qty).toFixed(2);
    const statusStr = o._type === 'ai_pos'
      ? (o.unrealized_pnl != null
        ? '<span class="' + (o.unrealized_pnl >= 0 ? 'green' : 'red') + '">' + (o.unrealized_pnl >= 0 ? '+' : '') + o.unrealized_pnl.toFixed(2) + '</span>'
        : '<span class="badge badge-green">持仓中</span>')
      : o.status === 'open' ? '<span class="badge badge-blue">挂单中</span>' : '<span class="badge badge-gray">' + escHtml(o.status) + '</span>';

    html += '<tr>' +
      '<td>' + escHtml(o.strategy || '-') + '</td>' +
      '<td><strong>' + escHtml(o.coin || o.symbol || '-') + '</strong></td>' +
      '<td>' + typeStr + '</td>' +
      '<td class="mono">$' + Number(price).toFixed(4) + '</td>' +
      '<td class="mono">' + Number(qty).toFixed(2) + '</td>' +
      '<td class="mono">' + amt + '</td>' +
      '<td>' + statusStr + '</td>' +
    '</tr>';
  }
  html += '</tbody></table>';
  return html;
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


function renderLocalTradeTable(trades) {
  if (!trades || !trades.length) return '<div class="empty">暂无记录</div>';
  let html = `<table>
    <thead><tr>
      <th>#</th><th>方向</th><th>开仓时间</th><th>开仓价</th>
      <th>平仓时间</th><th>平仓价</th><th>数量</th><th>已实现</th><th>浮盈</th><th>状态</th><th>策略</th>
    </tr></thead><tbody>`;
  for (const t of trades) {
    const statusBadge = t.status === '持仓中'
      ? '<span class="badge badge-blue">持仓中</span>'
      : t.status === '已平仓'
        ? '<span class="badge badge-gray">已平仓</span>'
        : '<span class="badge badge-yellow">部分平仓</span>';
    const isOpen = t.status === '持仓中';
    const upnl = t.unrealized_pnl;
    html += `<tr>
      <td>${t.id}</td>
      <td>${renderSide(t.direction)}</td>
      <td>${fmtTime(t.open_time)}</td>
      <td>${t.open_price ? Number(t.open_price).toFixed(1) : '-'}</td>
      <td>${t.close_time ? fmtTime(t.close_time) : '-'}</td>
      <td>${t.close_price ? Number(t.close_price).toFixed(1) : '-'}</td>
      <td>${t.quantity ? Number(t.quantity).toFixed(4) : '-'}</td>
      <td class="${pnlClass(t.pnl)}">${t.pnl !== null ? pnlStr(t.pnl) : '-'}</td>
      <td class="${isOpen && upnl !== undefined ? pnlClass(upnl) : 'pnl-zero'}">${isOpen && upnl !== undefined ? pnlStr(upnl) : '-'}</td>
      <td>${statusBadge}</td>
      <td>${t.strategy_name || '-'}</td>
    </tr>`;
  }
  html += '</tbody></table>';
  return html;
}

// ── USDC 策略页面 ────────────────────────────────────────────

async function renderUsdc() {
  setActiveNav('usdc');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const data = await api('/api/usdc');
    const state = data.state || {};
    const trades = data.trades || [];
    const stats = data.stats || {};
    const trend = state.trend || 'NONE';
    const pos = state.position || 'NONE';
    const hasPos = pos !== 'NONE';

    app.innerHTML = `
      <div class="section">
        <div class="section-title">📊 USDC 永续策略 <span class="count">BTC/USDC:USDC</span></div>
        <div class="row">
          <div class="col-3"><div class="stat-card">
            <div class="label">1H 趋势方向</div>
            <div class="value" style="font-size:1.2rem">
              ${trend === 'DOWN' ? '<span class="red">▼ DOWN</span>' :
                trend === 'UP' ? '<span class="green">▲ UP</span>' :
                '<span class="u-muted">— NONE</span>'}
            </div>
            <div class="sub">↓${state.down_votes||0} / ↑${state.up_votes||0} 票</div>
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">ADX / DI±</div>
            <div class="value u-fs11">${state.adx || '-'}</div>
            <div class="sub">+DI ${state.pdi||'-'} / -DI ${state.mdi||'-'}</div>
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">持仓</div>
            <div class="value u-fs11">
              ${hasPos ? renderSide(pos) + ' ' + (state.entry_price ? numStr(state.entry_price,0) : '') : '无持仓'}
            </div>
            <div class="sub">${data.last_update ? fmtTime(data.last_update) : '-'}</div>
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">累计交易</div>
            <div class="value blue">${stats.total_trades || 0}</div>
            <div class="sub">持仓中 ${stats.open_trades || 0} 笔</div>
          </div></div>
        </div>
        <div class="row">
          <div class="col-3"><div class="stat-card">
            <div class="label">总盈亏</div>
            <div class="value ${pnlClass(stats.total_pnl)}">${pnlStr(stats.total_pnl)}</div>
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">胜率</div>
            <div class="value blue">${stats.win_rate || 0}%</div>
            <div class="sub">${stats.wins || 0}胜 / ${stats.losses || 0}负</div>
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">浮动盈亏</div>
            ${(() => { const ot = trades.find(t => !t.exit_reason); const fp = ot && ot.unrealized_pnl; const fpp = ot && ot.unrealized_pnl_pct; return `<div class="value ${fp != null ? pnlClass(fp) : ''}">${fp != null ? pnlStr(fp) : '-'}</div><div class="sub">${fpp != null ? (fpp > 0 ? '+' : '') + fpp + '%' : ''}</div>`; })()}
          </div></div>
          <div class="col-3"><div class="stat-card">
            <div class="label">止损</div>
            <div class="value" style="color:#f85149;font-size:1rem">${state.entry_price ? numStr(state.entry_price * (pos === 'LONG' ? 0.985 : 1.015), 1) : '-'}</div>
          </div></div>
        </div>
      </div>

      <div class="section">
        <div class="section-title">📄 USDC 交易记录 <span class="count">(${trades.length})</span></div>
        <div class="table-wrap">${renderUsdcTradeTable(trades)}</div>
      </div>
    `;

    if (window._usdcTimer) clearTimeout(window._usdcTimer);
    window._usdcTimer = setTimeout(renderUsdc, 15000);
  } catch (e) {
    app.innerHTML = `<div class="empty">加载失败: ${e.message}</div>`;
  }
}

function renderUsdcTradeTable(trades) {
  if (!trades || !trades.length) return '<div class="empty">暂无交易记录</div>';
  let html = '<table><thead><tr><th>#</th><th>方向</th><th>开仓时间</th><th>开仓价</th><th>平仓时间</th><th>平仓价</th><th>数量</th><th>盈亏 (USDC)</th><th>盈亏%</th><th>状态</th></tr></thead><tbody>';
  for (let i = trades.length - 1; i >= 0; i--) {
    const t = trades[i];
    const isOpen = !t.exit_reason;
    const statusB = isOpen ? '<span class="badge badge-blue">持仓中</span>' : t.exit_reason === 'stop_loss' ? '<span class="badge badge-red">止损</span>' : '<span class="badge badge-gray">已平仓</span>';
    html += '<tr><td>' + (t.id || (i+1)) + '</td><td>' + renderSide(t.side) + '</td><td>' + (t.entry_time ? fmtTime(t.entry_time) : '-') + '</td><td>' + (t.entry_price ? numStr(t.entry_price, 1) : '-') + '</td><td>' + (t.exit_time ? fmtTime(t.exit_time) : '-') + '</td><td>' + (t.exit_price ? numStr(t.exit_price, 1) : '-') + '</td><td>' + (t.quantity ? Number(t.quantity).toFixed(4) : '-') + '</td><td class="' + (isOpen ? (t.unrealized_pnl !== undefined ? pnlClass(t.unrealized_pnl) : 'pnl-zero') : (t.pnl !== undefined ? pnlClass(t.pnl) : 'pnl-zero')) + '">' + (isOpen ? (t.unrealized_pnl !== undefined ? pnlStr(t.unrealized_pnl) + ' (浮)' : '-') : (t.pnl !== undefined ? pnlStr(t.pnl) : '-')) + '</td><td class="' + (isOpen ? (t.unrealized_pnl_pct !== undefined ? pnlClass(t.unrealized_pnl_pct) : 'pnl-zero') : (t.pnl_pct !== undefined ? pnlClass(t.pnl_pct) : 'pnl-zero')) + '">' + (isOpen ? (t.unrealized_pnl_pct !== undefined ? (t.unrealized_pnl_pct > 0 ? '+' : '') + t.unrealized_pnl_pct + '% (浮)' : '-') : (t.pnl_pct !== undefined ? (t.pnl_pct > 0 ? '+' : '') + t.pnl_pct + '%' : '-')) + '</td><td>' + statusB + '</td></tr>';
  }
  return html + '</tbody></table>';
}

// ── 趋势收敛策略页面 ─────────────────────────────────────────

function renderTcPosition(posData, mode) {
  if (!posData || !posData.position) return '<div style="color:#8b949e;padding:12px;text-align:center">无持仓</div>';
  const label = mode === 'LONG' ? '🟢 做多' : '🔴 做空';
  const col = mode === 'LONG' ? '#3fb950' : '#f85149';
  return '<table class="data-table"><thead><tr><th>方向</th><th>入场价</th><th>止盈</th><th>止损</th><th>浮动盈亏</th></tr></thead><tbody><tr>' +
    '<td style="color:' + col + ';font-weight:600">' + label + '</td>' +
    '<td>' + (posData.entry_price ? '$' + Number(posData.entry_price).toLocaleString('en') : '-') + '</td>' +
    '<td class="green">' + (posData.tp_price ? '$' + Number(posData.tp_price).toLocaleString('en') : '-') + '</td>' +
    '<td class="red">' + (posData.sl_price ? '$' + Number(posData.sl_price).toLocaleString('en') : '-') + '</td>' +
    '<td>-</td>' +
    '</tr></tbody></table>';
}

function renderTcTrades(trades) {
  if (!trades || !trades.length) return '<div style="color:#8b949e;padding:12px;text-align:center">暂无平仓记录</div>';
  const rows = trades.slice().reverse().slice(0, 50).map(function(t) {
    const pnl = t.pnl || 0;
    const pnlCl = pnl >= 0 ? '#3fb950' : '#f85149';
    return '<tr><td>' + (t.time || '-') + '</td><td>' + (t.exit_reason || '-') + '</td><td>$' + Number(t.entry || t.entry_price || 0).toLocaleString('en') + '</td><td style="color:' + pnlCl + ';font-weight:600">' + (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + '</td></tr>';
  }).join('');
  return '<table class="data-table"><thead><tr><th>时间</th><th>退出原因</th><th>入场价</th><th>盈亏(USDT)</th></tr></thead><tbody>' + rows + '</tbody></table>';
}

async function renderTrendConv() {
  setActiveNav('trend-conv');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const d = await api('/api/trend-convergence');
    const p = d.params || {};
    const kdj = d.kdj || {};
    const kdjStd = d.kdj_standard || {};
    const orders = Object.values(d.orders || {});
    const positions = Object.values(d.positions || {});
    const closed = d.closed_positions || [];
    const posSide = d.position_side;  // 'long','short', or null

    function dirLabel(side) {
      if (side === 'long') return '<span class="green">🟢 做多</span>';
      if (side === 'short') return '<span class="red">🔴 做空</span>';
      return '<span class="u-muted">⚪ 等待</span>';
    }

    const orderRows = orders.map(function(o) {
      const side = o.side || 'long';
      const sideLabel = side === 'long' ? '<span class="green">买入开多</span>' : '<span class="red">卖出开空</span>';
      return '<tr><td>' + (o.coin || '-') + '</td><td>' + sideLabel + '</td><td>$' + Number(o.price || 0).toLocaleString('en') + '</td><td>' + (o.quantity || '-') + '</td><td class="yellow">挂单中</td><td>' + (o.age_hours ? o.age_hours.toFixed(1) + 'h' : '-') + '</td><td class="u-meta-xs">' + ((o.order_id||'').slice(-8)||'-') + '</td></tr>';
    }).join('') || '<tr><td colspan="7" style="color:#8b949e;text-align:center;padding:20px">无挂单</td></tr>';

    const posRows = positions.map(function(pos) {
      const side = pos.side || 'long';
      const sideLabel = side === 'long' ? '<span class="green">LONG</span>' : '<span class="red">SHORT</span>';
      const upnl = pos.unrealized_pnl || 0;
      const upnlCl = upnl >= 0 ? '#3fb950' : '#f85149';
      return '<tr><td>' + (pos.coin || '-') + '</td><td>' + sideLabel + '</td><td>$' + Number(pos.entry_price || 0).toLocaleString('en') + '</td><td>' + (pos.quantity || '-') + '</td><td>$' + Number(pos.tp_price || 0).toLocaleString('en') + '</td><td>$' + Number(pos.sl_price || 0).toLocaleString('en') + '</td><td style="color:' + upnlCl + '">' + (upnl >= 0 ? '+' : '') + upnl.toFixed(2) + '</td><td>' + (pos.filled_at_str || '-') + '</td><td class="u-meta-xs">' + ((pos.order_id||'').slice(-8)||'-') + '</td></tr>';
    }).join('') || '<tr><td colspan="9" style="color:#8b949e;text-align:center;padding:20px">无持仓</td></tr>';

    const closedRows = closed.slice().reverse().slice(0, 50).map(function(t) {
      const pnl = t.pnl || 0;
      const pnlCl = pnl >= 0 ? '#3fb950' : '#f85149';
      const side = t.side || 'long';
      const sideIcon = side === 'long' ? '🟢' : '🔴';
      return '<tr><td>' + sideIcon + ' <a href="' + getCoinLink(t.coin) + '" target="_blank" rel="noopener" class="u-link">' + (t.coin || '-') + ' ↗</a></td><td>$' + Number(t.entry_price || 0).toLocaleString('en') + '</td><td>$' + Number(t.close_price || 0).toLocaleString('en') + '</td><td style="color:' + pnlCl + ';font-weight:600">' + (pnl >= 0 ? '+' : '') + pnl.toFixed(2) + '</td><td>' + (t.pnl_pct ? (t.pnl_pct >= 0 ? '+' : '') + t.pnl_pct.toFixed(2) + '%' : '-') + '</td><td>' + (t.reason || '-') + '</td><td>' + (t.filled_at_str || '-') + ' ~ ' + (t.close_time_str || '-') + '</td><td class="u-meta-xs">' + ((t.order_id||'').slice(-8)||'-') + '</td></tr>';
    }).join('') || '<tr><td colspan="8" style="color:#8b949e;text-align:center;padding:20px">暂无平仓记录</td></tr>';

    function condHtml(arr, color) {
      return (arr || []).map(function(c, i) {
        return '<div style="display:flex;align-items:center;gap:6px;border-bottom:1px solid #21262d;padding:2px 0">' +
          '<span style="color:' + color + ';font-weight:600;min-width:18px">' + (i + 1) + '.</span>' +
          '<span style="color:#c9d1d9;font-size:.78rem">' + c.label + '</span>' +
          '<span style="color:#8b949e;font-size:.72rem;margin-left:auto">' + c.check + '</span></div>';
      }).join('');
    }

    const updateTime = new Date().toLocaleTimeString('zh-CN', {hour12:false});

    // 当前状态面板 - 多空条件检查
    let statusHtml = '';
    if (kdj.K !== null) {
      const golden = kdj.K > kdj.D;
      const death = kdj.K < kdj.D;
      const oversold = kdj.K < (p.oversold_k || 25);
      const overbought = kdj.K > 70;
      statusHtml += '<div style="display:flex;gap:16px;justify-content:center;margin-top:4px">';

      // 多头条件
      const longOk = golden && oversold;
      statusHtml += '<div style="flex:1;border:1px solid ' + (longOk ? '#3fb950' : '#30363d') + ';border-radius:6px;padding:6px 8px">';
      statusHtml += '<div style="color:#3fb950;font-size:.8rem;font-weight:600;margin-bottom:4px">🟢 做多条件</div>';
      statusHtml += '<div style="font-size:.74rem;line-height:1.6">';
      statusHtml += '<span class="u-muted">金叉:</span> ' + (golden ? '<span class="green">✅ K>' + kdj.K.toFixed(1) + '</span>' : '<span class="red">❌ K≤D</span>') + '<br>';
      statusHtml += '<span class="u-muted">K&lt;' + (p.oversold_k || 25) + ':</span> ' + (oversold ? '<span class="green">✅ ' + kdj.K.toFixed(1) + '</span>' : '<span class="red">❌ ' + (kdj.K !== null ? kdj.K.toFixed(1) : '?') + '</span>') + '<br>';
      statusHtml += '<span class="u-muted">冷却:</span> <span class="u-muted">' + (p.cooldown_bars || 2) + '根(30分)</span>';
      statusHtml += '</div></div>';

      // 空头条件
      const shortOk = death && overbought;
      statusHtml += '<div style="flex:1;border:1px solid ' + (shortOk ? '#f85149' : '#30363d') + ';border-radius:6px;padding:6px 8px">';
      statusHtml += '<div style="color:#f85149;font-size:.8rem;font-weight:600;margin-bottom:4px">🔴 做空条件</div>';
      statusHtml += '<div style="font-size:.74rem;line-height:1.6">';
      statusHtml += '<span class="u-muted">死叉:</span> ' + (death ? '<span class="green">✅ K&lt;' + kdj.K.toFixed(1) + '</span>' : '<span class="red">❌ K≥D</span>') + '<br>';
      statusHtml += '<span class="u-muted">K&gt;70:</span> ' + (overbought ? '<span class="green">✅ ' + kdj.K.toFixed(1) + '</span>' : '<span class="red">❌ ' + (kdj.K !== null ? kdj.K.toFixed(1) : '?') + '</span>') + '<br>';
      statusHtml += '<span class="u-muted">冷却:</span> <span class="u-muted">' + (p.cooldown_bars || 2) + '根(30分)</span>';
      statusHtml += '</div></div></div>';
    }

    app.innerHTML = `
      <div class="compact-section">
        <div class="section-title" style="margin-bottom:4px">📊 KDJ 多空对称策略 <span class="count">${p.symbol || 'BTC/USDC:USDC'} · ${(p.leverage || 1)}x</span>
          <span style="float:right;font-size:.75rem;color:#484f58;font-weight:400">⏱ ${updateTime}</span>
        </div>

        <div style="display:flex;gap:6px;flex-wrap:nowrap">
          <div style="flex:1;min-width:0;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;text-align:center">
            <div style="font-size:.7rem;color:#8b949e;margin-bottom:2px">KDJ <span class="u-muted">(${p.k_period||7},${p.d_period||2})</span></div>
            <div style="display:flex;gap:12px;justify-content:center">
<div><span class="u-meta-xs">K</span><br><span style="font-weight:700;font-size:1.1rem;color:${kdj.K !== null && kdj.K < 30 ? '#3fb950' : kdj.K !== null && kdj.K < 70 ? '#d29922' : '#f85149'}">${kdj.K !== null ? kdj.K.toFixed(1) : '-'}</span></div>
              <div><span class="u-meta-xs">D</span><br><span style="font-weight:700;font-size:1.1rem">${kdj.D !== null ? kdj.D.toFixed(1) : '-'}</span></div>
              <div><span class="u-meta-xs">J</span><br><span style="font-weight:700;font-size:1.1rem;color:${kdj.J !== null && kdj.J > 100 ? '#f85149' : '#d29922'}">${kdj.J !== null ? kdj.J.toFixed(1) : '-'}</span></div>
            </div>
          </div>
          <div style="flex:1;min-width:0;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;text-align:center">
            <div style="font-size:.7rem;color:#8b949e;margin-bottom:2px">标准KDJ <span class="u-muted">(9,3)</span></div>
            <div style="display:flex;gap:12px;justify-content:center">
              <div><span class="u-meta-xs">K</span><br><span style="font-weight:700;font-size:1.1rem;color:${kdjStd.K !== null && kdjStd.K < 30 ? '#3fb950' : kdjStd.K !== null && kdjStd.K < 70 ? '#d29922' : '#f85149'}">${kdjStd.K !== null ? kdjStd.K : '-'}</span></div>
              <div><span class="u-meta-xs">D</span><br><span style="font-weight:700;font-size:1.1rem">${kdjStd.D !== null ? kdjStd.D : '-'}</span></div>
              <div><span class="u-meta-xs">J</span><br><span style="font-weight:700;font-size:1.1rem;color:${kdjStd.J !== null && kdjStd.J > 100 ? '#f85149' : '#d29922'}">${kdjStd.J !== null ? kdjStd.J : '-'}</span></div>
            </div>
          </div>
          <div style="flex:1;min-width:0;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px;text-align:center">
            <div style="font-size:.7rem;color:#8b949e;margin-bottom:2px">策略参数</div>
            <div style="font-size:.7rem;color:#8b949e;line-height:1.5">
              KDJ(7,2) · 多K&lt;${p.oversold_k||25} -$${Math.abs(p.entry_offset||50)} · 空K&gt;${p.overbought_k||70} +$${Math.abs(p.entry_offset||50)}<br>
              TP${p.take_profit_pct||0.3}% SL${p.stop_loss_pct||0.8}% · 挂单30分 · 最长${p.max_hold_candles||8}根(${((p.max_hold_candles||8)*15/60)}h)
            </div>
          </div>
          <div style="flex:1;min-width:0;background:#161b22;border:1px solid #30363d;border-radius:8px;padding:8px 10px">
            <div style="font-size:.7rem;color:#8b949e;margin-bottom:2px;display:flex;justify-content:space-between">
              <span>当前持仓</span><span class="u-fw6">${dirLabel(posSide)}</span>
            </div>
            ${statusHtml || '<div style="font-size:.68rem;color:#8b949e;text-align:center;padding:2px 0">等待KDJ数据...</div>'}
          </div>
        </div>

        <div style="display:flex;gap:8px;margin-top:6px">
          <div style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:4px 10px;min-width:0">
            <div style="color:#3fb950;font-size:.78rem;font-weight:600;padding:3px 0">🟢 做多入场流程</div>
            ${condHtml(d.conditions_long, '#3fb950')}
          </div>
          <div style="flex:1;background:#0d1117;border:1px solid #30363d;border-radius:6px;padding:4px 10px;min-width:0">
            <div style="color:#f85149;font-size:.78rem;font-weight:600;padding:3px 0">🔴 做空入场流程</div>
            ${condHtml(d.conditions_short, '#f85149')}
          </div>
        </div>          </div></div>
        </div>

        <div class="section-title" style="margin-top:6px;margin-bottom:4px">📋 挂单列表 <span class="count">${orders.length}</span></div>
        <div class="table-wrap compact-table-wrap"><table class="compact-table"><thead><tr><th>币种</th><th>方向</th><th>价格</th><th>数量</th><th>状态</th><th>挂单时间</th><th>单号</th></tr></thead><tbody>${orderRows}</tbody></table></div>

        <div class="section-title" style="margin-top:6px;margin-bottom:4px">💼 持仓列表 <span class="count">${positions.length}</span></div>
        <div class="table-wrap compact-table-wrap"><table class="compact-table"><thead><tr><th>币种</th><th>方向</th><th>入场价</th><th>数量</th><th>止盈</th><th>止损</th><th>浮亏</th><th>开仓时间</th><th>单号</th></tr></thead><tbody>${posRows}</tbody></table></div>

        <div class="section-title" style="margin-top:6px;margin-bottom:4px">📜 平仓记录 <span class="count">${closed.length}</span></div>
        <div class="table-wrap compact-table-wrap"><table class="compact-table"><thead><tr><th>币种</th><th>入场价</th><th>平仓价</th><th>盈亏(U)</th><th>盈亏%</th><th>原因</th><th>持仓时间</th><th>单号</th></tr></thead><tbody>${closedRows}</tbody></table></div>
      </div>
    `;

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

// ── OKX 多账户管理 ──────────────────────────────────────────

const OKX_STORAGE_KEY = 'okx_accounts_v1';

function loadOkxAccounts() {
  try { return JSON.parse(localStorage.getItem(OKX_STORAGE_KEY)) || []; }
  catch { return []; }
}

function saveOkxAccounts(accounts) {
  localStorage.setItem(OKX_STORAGE_KEY, JSON.stringify(accounts));
}

function escHtml(s) {
  if (!s) return '';
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');
}

function okxAccCard(acc, idx) {
  return '<div class="okx-card" data-idx="' + idx + '"><div class="okx-card-header"><span class="okx-card-num">#' + (idx+1) + '</span><input class="okx-input okx-input-name" value="' + escHtml(acc.name || '') + '" placeholder="账户名称" onchange="okxUpdateAcc(' + idx + ',\'name\',this.value)"><label class="okx-toggle"><input type="checkbox" ' + (acc.enabled !== false ? 'checked' : '') + ' onchange="okxUpdateAcc(' + idx + ',\'enabled\',this.checked)"><span>启用</span></label><label class="okx-toggle"><input type="checkbox" ' + (acc.sandbox ? 'checked' : '') + ' onchange="okxUpdateAcc(' + idx + ',\'sandbox\',this.checked)"><span>🟡模拟</span></label><button class="okx-btn okx-btn-sm okx-btn-danger" onclick="okxRemoveAcc(' + idx + ')">✕</button></div><div class="okx-card-body"><div class="okx-field"><label>API Key</label><input class="okx-input okx-mono" value="' + escHtml(acc.apiKey || '') + '" placeholder="输入 API Key" onchange="okxUpdateAcc(' + idx + ',\'apiKey\',this.value)"></div><div class="okx-field"><label>Secret</label><input class="okx-input okx-mono" type="password" value="' + escHtml(acc.secret || '') + '" placeholder="输入 Secret" onchange="okxUpdateAcc(' + idx + ',\'secret\',this.value)"></div><div class="okx-field"><label>Passphrase</label><input class="okx-input okx-mono" type="password" value="' + escHtml(acc.password || '') + '" placeholder="输入 Passphrase" onchange="okxUpdateAcc(' + idx + ',\'password\',this.value)"></div></div></div>';
}

// Global OKX functions
function okxUpdateAcc(idx, key, val) {
  const accounts = loadOkxAccounts();
  if (!accounts[idx]) return;
  accounts[idx][key] = val;
  saveOkxAccounts(accounts);
}

function okxRemoveAcc(idx) {
  const accounts = loadOkxAccounts();
  accounts.splice(idx, 1);
  saveOkxAccounts(accounts);
  renderOkx();
}

function okxAddAcc() {
  const accounts = loadOkxAccounts();
  accounts.push({ name: '账户' + (accounts.length+1), apiKey: '', secret: '', password: '', enabled: true, sandbox: false });
  saveOkxAccounts(accounts);
  renderOkx();
}

function okxUpdateResults(html) {
  const el = document.getElementById('okxResults');
  if (el) el.innerHTML = html;
}

function okxGetSelectedAccounts() {
  const accounts = loadOkxAccounts();
  const cards = document.querySelectorAll('.okx-card');
  cards.forEach((card) => {
    const idx = parseInt(card.dataset.idx);
    if (isNaN(idx) || !accounts[idx]) return;
    const inputs = card.querySelectorAll('.okx-card-body .okx-field');
    inputs.forEach((field) => {
      const label = field.querySelector('label');
      const input = field.querySelector('.okx-input');
      if (!label || !input) return;
      const text = label.textContent.trim();
      const val = input.value.trim();
      if (text === 'API Key') accounts[idx].apiKey = val;
      else if (text === 'Secret') accounts[idx].secret = val;
      else if (text === 'Passphrase') accounts[idx].password = val;
    });
  });
  saveOkxAccounts(accounts);
  return accounts.filter(a => a && a.apiKey && !a.apiKey.includes('YOUR_'));
}

async function okxQueryBalance() {
  const accounts = okxGetSelectedAccounts();
  if (!accounts.length) { okxUpdateResults('<div class="empty">⚠️ 请先添加并启用至少一个账户</div>'); return; }
  okxUpdateResults('<div class="loading">查询余额中...</div>');
  try {
    const r = await fetch('/api/okx/balance', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ accounts }) });
    const j = await r.json();
    if (j.code !== 0) throw new Error(j.msg);
    const results = j.data || [];
    let html = '<div class="section-title">📊 账户余额</div><div class="table-wrap"><table><thead><tr><th>账户</th><th>USDT总</th><th>可用</th><th>冻结</th><th>总权益</th><th>浮亏</th><th>持仓</th></tr></thead><tbody>';
    let tUsdt = 0, tEquity = 0, tPnl = 0;
    for (const r of results) {
      if (!r.ok) { html += '<tr><td>' + escHtml(r.name) + '</td><td colspan="6" class="red">❌ ' + escHtml(r.error) + '</td></tr>'; continue; }
      tUsdt += r.usdt_total; tEquity += r.total_equity; tPnl += r.unrealized_pnl;
      const posHtml = (r.positions || []).map(p => '<span class="badge ' + (p.side === 'long' ? 'badge-green' : 'badge-red') + '">' + (p.side === 'long' ? '多' : '空') + ' ' + p.size + '张</span>').join(' ') || '-';
      html += '<tr><td><strong>' + escHtml(r.name) + '</strong></td><td class="green">' + numStr(r.usdt_total) + '</td><td>' + numStr(r.usdt_free) + '</td><td class="yellow">' + numStr(r.usdt_used) + '</td><td class="green">' + numStr(r.total_equity) + '</td><td class="' + pnlClass(r.unrealized_pnl) + '">' + pnlStr(r.unrealized_pnl) + '</td><td>' + posHtml + '</td></tr>';
    }
    html += '</tbody><tfoot><tr class="u-fw7"><td>合计 (' + results.filter(r=>r.ok).length + '个)</td><td>' + numStr(tUsdt) + '</td><td></td><td></td><td>' + numStr(tEquity) + '</td><td class="' + pnlClass(tPnl) + '">' + pnlStr(tPnl) + '</td><td></td></tr></tfoot></table></div>';

    const hasPos = results.filter(r => r.ok && r.positions && r.positions.length);
    if (hasPos.length) {
      html += '<div class="section-title" style="margin-top:16px">📌 持仓明细</div><div class="table-wrap"><table><thead><tr><th>账户</th><th>合约</th><th>方向</th><th>张数</th><th>开仓价</th><th>标记价</th><th>浮亏</th><th>保证金</th></tr></thead><tbody>';
      for (const r of hasPos) {
        for (const p of r.positions) {
          html += '<tr><td>' + escHtml(r.name) + '</td><td>' + (p.symbol || '-') + '</td><td>' + (p.side === 'long' ? '<span class="badge badge-green">多</span>' : '<span class="badge badge-red">空</span>') + '</td><td>' + p.size + '</td><td>$' + numStr(p.entryPrice,1) + '</td><td>$' + numStr(p.markPrice,1) + '</td><td class="' + pnlClass(p.unrealizedPnl) + '">' + pnlStr(p.unrealizedPnl) + '</td><td>' + numStr(p.margin) + '</td></tr>';
        }
      }
      html += '</tbody></table></div>';
    }
    okxUpdateResults(html);
  } catch (e) {
    okxUpdateResults('<div class="empty red">❌ 查询失败: ' + e.message + '</div>');
  }
}

async function okxOpenPosition() {
  const accounts = okxGetSelectedAccounts();
  if (!accounts.length) { okxUpdateResults('<div class="empty">⚠️ 请先添加账户</div>'); return; }
  const symbol = document.getElementById('okxSymbol').value || 'BTC/USDT:USDT';
  const side = document.getElementById('okxSide').value;
  const amount = parseFloat(document.getElementById('okxAmount').value) || 0.01;
  const leverage = parseInt(document.getElementById('okxLeverage').value) || 1;
  const marginMode = document.getElementById('okxMargin').value;
  if (!confirm('确认在所有已启用的账户上' + (side === 'buy' ? '开多' : '开空') + ' ' + amount + ' 张 ' + symbol + ' ?')) return;
  okxUpdateResults('<div class="loading">正在逐账户开仓...</div>');
  let html = '<div class="section-title">📝 开仓结果</div><div class="table-wrap"><table><thead><tr><th>账户</th><th>结果</th><th>成交</th><th>均价</th><th>说明</th></tr></thead><tbody>';
  for (const acc of accounts) {
    try {
      const r = await fetch('/api/okx/open-position', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ account: acc, symbol, side, amount, leverage, marginMode, sandbox: !!acc.sandbox }) });
      const j = await r.json();
      if (j.code !== 0) throw new Error(j.msg);
      const d = j.data;
      html += '<tr><td><strong>' + escHtml(acc.name) + '</strong></td><td><span class="badge badge-green">✅</span></td><td>' + d.filled + '/' + d.amount + '</td><td>$' + d.avg_price + '</td><td style="max-width:200px;font-size:.82rem">' + escHtml(d.message) + '</td></tr>';
    } catch (e) {
      html += '<tr><td><strong>' + escHtml(acc.name) + '</strong></td><td><span class="badge badge-red">❌</span></td><td colspan="3" class="red">' + escHtml(e.message) + '</td></tr>';
    }
  }
  okxUpdateResults(html + '</tbody></table></div>');
}

async function okxCloseAll() {
  const accounts = okxGetSelectedAccounts();
  if (!accounts.length) { okxUpdateResults('<div class="empty">⚠️ 请先添加账户</div>'); return; }
  if (!confirm('⚠️ 确认平掉所有账户的全部持仓？此操作不可撤销！')) return;
  okxUpdateResults('<div class="loading">正在一键平仓...</div>');
  let html = '<div class="section-title">🔄 一键平仓结果</div><div class="table-wrap"><table><thead><tr><th>账户</th><th>合约</th><th>方向</th><th>持仓</th><th>成交</th><th>状态</th></tr></thead><tbody>';
  for (const acc of accounts) {
    try {
      const r = await fetch('/api/okx/close-all', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ account: acc, sandbox: !!acc.sandbox }) });
      const j = await r.json();
      if (j.code !== 0) throw new Error(j.msg);
      const d = j.data;
      if (d.closed && d.closed.length) {
        for (const c of d.closed) {
          const ok = !c.error;
          html += '<tr><td><strong>' + escHtml(acc.name) + '</strong></td><td>' + (c.symbol || '-') + '</td><td>' + (c.side === 'long' ? '<span class="badge badge-green">多</span>' : '<span class="badge badge-red">空</span>') + '</td><td>' + c.size + '</td><td>' + (c.filled || 0) + '</td><td>' + (ok ? '<span class="badge badge-green">已平</span>' : '<span class="badge badge-red">失败:' + escHtml(c.error) + '</span>') + '</td></tr>';
        }
      } else {
        html += '<tr><td>' + escHtml(acc.name) + '</td><td colspan="5">无持仓</td></tr>';
      }
    } catch (e) {
      html += '<tr><td>' + escHtml(acc.name) + '</td><td colspan="5" class="red">❌ ' + escHtml(e.message) + '</td></tr>';
    }
  }
  okxUpdateResults(html + '</tbody></table></div>');
}

async function okxQueryOrders() {
  const accounts = okxGetSelectedAccounts();
  if (!accounts.length) { okxUpdateResults('<div class="empty">⚠️ 请先添加账户</div>'); return; }
  const symbol = document.getElementById('okxSymbol').value || 'BTC/USDT:USDT';
  const limit = parseInt(document.getElementById('okxOrderLimit').value) || 10;
  okxUpdateResults('<div class="loading">查询订单中...</div>');
  let html = '<div class="section-title">📄 最近订单</div>';
  for (const acc of accounts) {
    try {
      const r = await fetch('/api/okx/orders', { method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({ account: acc, symbol, limit, sandbox: !!acc.sandbox }) });
      const j = await r.json();
      if (j.code !== 0) throw new Error(j.msg);
      const orders = j.data || [];
      html += '<div style="margin-top:12px"><strong style="color:#58a6ff">' + escHtml(acc.name) + '</strong> (' + orders.length + ' 条)</div>';
      if (orders.length) {
        html += '<div class="table-wrap"><table><thead><tr><th>时间</th><th>方向</th><th>类型</th><th>数量</th><th>成交</th><th>价格</th><th>成交额</th><th>状态</th></tr></thead><tbody>';
        for (const o of orders) {
          const side = o.side === 'buy' ? '<span class="badge badge-green">买入</span>' : '<span class="badge badge-red">卖出</span>';
          const statusMap = { open:'badge-blue', closed:'badge-gray', filled:'badge-green', canceled:'badge-red' };
          const statusCls = statusMap[o.status] || 'badge-gray';
          html += '<tr><td style="font-size:.8rem">' + (o.datetime ? fmtTime(o.datetime) : '-') + '</td><td>' + side + '</td><td>' + (o.type || '-') + '</td><td>' + (o.amount || '-') + '</td><td>' + (o.filled || 0) + '</td><td>$' + (o.price ? Number(o.price).toFixed(1) : '-') + '</td><td>' + (o.cost ? Number(o.cost).toFixed(2) : '-') + '</td><td><span class="badge ' + statusCls + '">' + (o.status || '-') + '</span></td></tr>';
        }
        html += '</tbody></table></div>';
      } else {
        html += '<div class="empty" style="padding:12px">无订单</div>';
      }
    } catch (e) {
      html += '<div style="margin-top:8px;color:#f85149">' + escHtml(acc.name) + ': ' + escHtml(e.message) + '</div>';
    }
  }
  okxUpdateResults(html);
}

async function renderOkx() {
  setActiveNav('okx');
  const app = qs('#app');
  const accounts = loadOkxAccounts();

  app.innerHTML = '<div class="okx-page"><div class="page-header"><div class="section-title u-fs115">🔑 OKX 多账户管理</div><button class="okx-btn okx-btn-primary" onclick="okxAddAcc()">＋ 添加账户</button></div><div class="okx-hint">API Key 仅存储在你的浏览器本地，不会上传到服务器。</div><div class="okx-cards" id="okxCards">' + (accounts.length ? accounts.map((a,i) => okxAccCard(a,i)).join('') : '<div class="empty" style="grid-column:1/-1">暂无账户</div>') + '</div>' + (accounts.length ? '<div class="okx-actions"><div class="section-title" style="margin-bottom:8px">⚙️ 交易操作</div><div class="okx-params"><div class="okx-param"><label>合约</label><select id="okxSymbol" class="okx-input"><option value="BTC/USDT:USDT">BTC/USDT:USDT</option><option value="ETH/USDT:USDT">ETH/USDT:USDT</option><option value="SOL/USDT:USDT">SOL/USDT:USDT</option><option value="DOGE/USDT:USDT">DOGE/USDT:USDT</option></select></div><div class="okx-param"><label>方向</label><select id="okxSide" class="okx-input"><option value="buy">🟢 开多</option><option value="sell">🔴 开空</option></select></div><div class="okx-param"><label>张数</label><input id="okxAmount" class="okx-input okx-mono" type="number" value="0.01" step="0.01" min="0.01"></div><div class="okx-param"><label>杠杆</label><select id="okxLeverage" class="okx-input"><option value="1">1x</option><option value="2">2x</option><option value="3">3x</option><option value="5">5x</option><option value="10">10x</option></select></div><div class="okx-param"><label>保证金</label><select id="okxMargin" class="okx-input"><option value="isolated">逐仓</option><option value="cross">全仓</option></select></div><div class="okx-param"><label>订单条数</label><input id="okxOrderLimit" class="okx-input okx-mono" type="number" value="10" min="1" max="50"></div></div><div class="okx-btn-row"><button class="okx-btn okx-btn-primary" onclick="okxQueryBalance()">📊 查询余额</button><button class="okx-btn okx-btn-success" onclick="okxOpenPosition()">🚀 开仓</button><button class="okx-btn okx-btn-danger" onclick="okxCloseAll()">🛑 一键平仓</button><button class="okx-btn okx-btn-info" onclick="okxQueryOrders()">📄 查询订单</button></div></div><div class="okx-results" id="okxResults"><div class="empty">执行操作后结果显示在这里</div></div></div>' : '');
}

// ── 趋势打分独立页面 ────────────────────────────────────────

async function renderTrendScorePage() {
  setActiveNav('trend-score');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const data = await api('/api/trend-score');
    const tfs = data.timeframes || {};

    // 构建打分卡片
    let cardsHtml = '';
    for (const [tf, d] of Object.entries(tfs)) {
      const s = d.score || 50;
      const detail = d.detail || {};
      const label = {'5m':'5分钟','15m':'15分钟','1h':'1小时'}[tf] || tf;
      const closePrice = detail.close ? (typeof detail.close === 'number' ? '$' + detail.close.toLocaleString('en', {minimumFractionDigits:1,maximumFractionDigits:1}) : detail.close) : '-';

      // 颜色
      let bgColor, textColor, statusText, statusIcon;
      if (s >= 70) { bgColor = '#0d2e12'; textColor = '#3fb950'; statusText = '偏多'; statusIcon = '🟢'; }
      else if (s >= 55) { bgColor = '#1a1a0d'; textColor = '#d29922'; statusText = '偏多'; statusIcon = '🟡'; }
      else if (s >= 45) { bgColor = '#1a1a0d'; textColor = '#d29922'; statusText = '中性'; statusIcon = '⚪'; }
      else if (s >= 30) { bgColor = '#1a0d0d'; textColor = '#f85149'; statusText = '偏空'; statusIcon = '🟡'; }
      else { bgColor = '#2d0d0d'; textColor = '#f85149'; statusText = '偏空'; statusIcon = '🔴'; }

      // 进度条
      const barColor = s >= 55 ? '#3fb950' : s >= 45 ? '#d29922' : '#f85149';
      const barWidth = Math.max(5, Math.min(100, s));

      // 各子项
      const items = [
        {key:'s_ema', label:'EMA位置', val: detail.s_ema, w:0.20},
        {key:'s_mom', label:'动量', val: detail.s_mom, w:0.20},
        {key:'s_rsi', label:'RSI', val: detail.s_rsi, w:0.15},
        {key:'s_bb', label:'布林带', val: detail.s_bb, w:0.15},
        {key:'s_macd', label:'MACD', val: detail.s_macd, w:0.15},
        {key:'s_vol', label:'量能', val: detail.s_vol, w:0.15},
      ];

      cardsHtml += '<div class="col-4" style="margin-bottom:16px">' +
        '<div style="background:#161b22;border-radius:10px;overflow:hidden;border:1px solid #30363d">' +
          // 头部: 周期 + 分数
          '<div style="background:' + bgColor + ';padding:16px 20px;text-align:center">' +
            '<div style="color:#8b949e;font-size:.85rem;margin-bottom:4px">' + label + '</div>' +
            '<div style="font-size:3rem;font-weight:800;color:' + textColor + ';line-height:1">' + s + '</div>' +
            '<div style="color:' + textColor + ';font-size:.9rem;margin-top:4px">' + statusIcon + ' ' + statusText + '</div>' +
          '</div>' +
          // 进度条
          '<div style="padding:12px 20px 0">' +
            '<div style="height:6px;background:#21262d;border-radius:3px;overflow:hidden">' +
              '<div style="height:100%;width:' + barWidth + '%;background:' + barColor + ';border-radius:3px;transition:width .5s"></div>' +
            '</div>' +
            '<div style="display:flex;justify-content:space-between;font-size:.7rem;color:#484f58;margin-top:2px">' +
              '<span>偏空 0</span><span>50</span><span>偏多 100</span>' +
            '</div>' +
          '</div>' +
          // 收盘价
          '<div style="padding:8px 20px;display:flex;justify-content:space-between;font-size:.85rem;border-bottom:1px solid #21262d">' +
            '<span class="u-muted">收盘价</span><span style="color:#e6edf3;font-weight:600">' + closePrice + '</span>' +
          '</div>' +
          // 子项
          '<div style="padding:8px 20px 12px">' +
            items.map(item => {
              const v = detail[item.key];
              const val = v != null && !isNaN(v) ? Math.round(v) : '-';
              const c = val >= 70 ? '#3fb950' : val >= 45 ? '#d29922' : val <= 30 ? '#f85149' : '#8b949e';
              return '<div style="display:flex;justify-content:space-between;align-items:center;padding:3px 0;font-size:.82rem">' +
                '<span class="u-muted">' + item.label + '</span>' +
                '<div style="display:flex;align-items:center;gap:8px">' +
                  '<div style="width:60px;height:4px;background:#21262d;border-radius:2px">' +
                    '<div style="height:100%;width:' + Math.min(100, Math.max(0, val)) + '%;background:' + c + ';border-radius:2px"></div>' +
                  '</div>' +
                  '<span style="color:' + c + ';font-weight:600;min-width:24px;text-align:right">' + val + '</span>' +
                '</div>' +
              '</div>';
            }).join('') +
          '</div>' +
        '</div></div>';
    }

    app.innerHTML = '<div class="section"><div class="section-title">📊 趋势打分 <span class="count">5m / 15m / 1h</span></div>' +
      '<div class="row">' + cardsHtml + '</div>' +
      '<div class="section"><div class="section-title">📈 评分趋势 <span class="count">近12小时</span></div>' +
      '<div style="background:#161b22;border-radius:10px;padding:16px;border:1px solid #30363d">' +
      '<canvas id="trendChartCanvas" style="width:100%;height:380px"></canvas></div></div>';

    // ── 渲染 Chart.js 曲线 ──
    if (typeof Chart !== 'undefined') {
      if (window._trendChart) { window._trendChart.destroy(); window._trendChart = null; }
      fetch('/api/trend-history')
        .then(function(r) { return r.json(); })
        .then(function(j) {
          var resp = j;
          if (resp.code !== 0) return;
          var data = resp.data || [];
          if (!data.length) return;

          var labels = data.map(function(d) {
            var t = new Date(d.time * 1000);
            var pad = function(n) { return n < 10 ? '0' + n : n; };
            return pad(t.getHours()) + ':' + pad(t.getMinutes());
          });
          var prices = data.map(function(d) { return d.price; });
          var tf5 = data.map(function(d) { return (d.scores || {})['5m'] !== undefined ? d.scores['5m'] : null; });
          var tf15 = data.map(function(d) { return (d.scores || {})['15m'] !== undefined ? d.scores['15m'] : null; });
          var tf1h = data.map(function(d) { return (d.scores || {})['1h'] !== undefined ? d.scores['1h'] : null; });

          // 默认显示最近60个点（1小时）
          var defaultPoints = Math.min(60, data.length);
          var xMin = data.length > defaultPoints ? data.length - defaultPoints : 0;

          var ctx = document.getElementById('trendChartCanvas');
          if (!ctx) return;

          window._trendChart = new Chart(ctx.getContext('2d'), {
            type: 'line',
            data: {
              labels: labels,
              datasets: [
                { label: '5分钟', data: tf5, borderColor: '#ff7f2a', borderWidth: 2.5, backgroundColor: 'rgba(255,127,42,0.08)', fill: true, pointRadius: 0, pointHitRadius: 8, pointHoverRadius: 5, pointHoverBackgroundColor: '#ff7f2a', pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2, tension: 0.35 },
                { label: '15分钟', data: tf15, borderColor: '#58a6ff', borderWidth: 2.5, backgroundColor: 'rgba(88,166,255,0.08)', fill: true, pointRadius: 0, pointHitRadius: 8, pointHoverRadius: 5, pointHoverBackgroundColor: '#58a6ff', pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2, tension: 0.35 },
                { label: '1小时', data: tf1h, borderColor: '#3fb950', borderWidth: 2.5, backgroundColor: 'rgba(63,185,80,0.08)', fill: true, pointRadius: 0, pointHitRadius: 8, pointHoverRadius: 5, pointHoverBackgroundColor: '#3fb950', pointHoverBorderColor: '#fff', pointHoverBorderWidth: 2, tension: 0.35 },
                { label: 'BTC价格', data: prices, borderColor: '#8b949e', borderWidth: 1.5, borderDash: [4, 3], backgroundColor: 'transparent', fill: false, pointRadius: 0, pointHitRadius: 8, pointHoverRadius: 3, pointHoverBackgroundColor: '#8b949e', pointHoverBorderColor: '#fff', pointHoverBorderWidth: 1, tension: 0.3, yAxisID: 'y1' },
              ]
            },
            options: {
              responsive: true,
              maintainAspectRatio: false,
              animation: { duration: 300 },
              interaction: { mode: 'nearest', axis: 'x', intersect: false },
              scales: {
                x: {
                  min: xMin, max: data.length - 1,
                  grid: { color: 'rgba(48,54,61,0.4)', drawBorder: false },
                  ticks: { color: '#8b949e', maxTicksLimit: 12, maxRotation: 0, font: { size: 11 } },
                },
                y: {
                  position: 'left', min: 0, max: 100,
                  grid: { color: 'rgba(48,54,61,0.4)', drawBorder: false },
                  ticks: { color: '#8b949e', stepSize: 20, font: { size: 11 } },
                  title: { display: true, text: '打分', color: '#8b949e', font: { size: 11 } },
                },
                y1: {
                  position: 'right',
                  grid: { display: false },
                  ticks: { color: '#8b949e', font: { size: 10 }, callback: function(v) { return '$' + Number(v).toLocaleString('en'); } },
                  title: { display: true, text: 'BTC价格', color: '#8b949e', font: { size: 11 } },
                },
              },
              plugins: {
                legend: { display: false },
                tooltip: {
                  backgroundColor: '#1c2333', titleColor: '#e6edf3', bodyColor: '#c9d1d9',
                  borderColor: '#30363d', borderWidth: 1, padding: 12, cornerRadius: 8, displayColors: true,
                  callbacks: {
                    title: function(items) {
                      var idx = items[0].dataIndex;
                      var d = data[idx];
                      if (!d) return '';
                      var t = new Date(d.time * 1000);
                      var pad = function(n) { return n < 10 ? '0' + n : n; };
                      return t.getFullYear() + '-' + pad(t.getMonth()+1) + '-' + pad(t.getDate()) + ' ' + pad(t.getHours()) + ':' + pad(t.getMinutes()) + ':' + pad(t.getSeconds());
                    },
                    label: function(ctx) {
                      if (ctx.dataset.label === 'BTC价格') { return ctx.dataset.label + ': $' + Number(ctx.parsed.y).toLocaleString('en'); }
                      return ctx.dataset.label + ': ' + ctx.parsed.y + '分';
                    }
                  }
                },
                zoom: {
                  pan: { enabled: true, mode: 'x', modifierKey: null },
                  zoom: { wheel: { enabled: true, speed: 0.05 }, pinch: { enabled: true }, drag: { enabled: false }, mode: 'x' },
                },
              },
            },
            plugins: [{
              id: 'zoneBackground',
              beforeDraw: function(chart) {
                var ctx2 = chart.ctx;
                var chartArea = chart.chartArea;
                var yAxis = chart.scales.y;
                var xAxis = chart.scales.x;
                if (!chartArea) return;
                var top = yAxis.getPixelForValue(100);
                var mid70 = yAxis.getPixelForValue(70);
                var mid40 = yAxis.getPixelForValue(40);
                var bot = yAxis.getPixelForValue(0);
                var left = chartArea.left;
                var right = chartArea.right;
                ctx2.fillStyle = 'rgba(63,185,80,0.06)';
                ctx2.fillRect(left, top, right - left, mid70 - top);
                ctx2.fillStyle = 'rgba(210,153,34,0.05)';
                ctx2.fillRect(left, mid70, right - left, mid40 - mid70);
                ctx2.fillStyle = 'rgba(248,81,73,0.06)';
                ctx2.fillRect(left, mid40, right - left, bot - mid40);
                ctx2.setLineDash([3, 3]);
                ctx2.lineWidth = 1;
                ctx2.strokeStyle = 'rgba(63,185,80,0.2)';
                ctx2.beginPath(); ctx2.moveTo(left, mid70); ctx2.lineTo(right, mid70); ctx2.stroke();
                ctx2.strokeStyle = 'rgba(248,81,73,0.2)';
                ctx2.beginPath(); ctx2.moveTo(left, mid40); ctx2.lineTo(right, mid40); ctx2.stroke();
                ctx2.setLineDash([]);
              }
            }]
          });
        })
        .catch(function(e) { console.warn('趋势曲线加载失败', e); });
    }

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

// ── AI 入场页面 ───────────────────────────────────────────

// 当前选中的 record_time


// ── Binance AI 页面 ─────────────────────────────────────────

let _binanceAiSelectedTime = null;

async function renderBinanceAi() {
  setActiveNav('binance-ai');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [timesData, data] = await Promise.all([
      api('/api/binance-ai/times').catch(() => ({ times: [] })),
      _binanceAiSelectedTime
        ? api('/api/binance-ai?analysis_time=' + encodeURIComponent(_binanceAiSelectedTime))
        : api('/api/binance-ai'),
    ]);

    const allTimes = timesData.times || [];
    const latestTime = data.analysis_time;
    if (!_binanceAiSelectedTime && latestTime) {
      _binanceAiSelectedTime = latestTime;
    }

    const records = data.records || [];
    const currentTime = _binanceAiSelectedTime || latestTime;

    // 获取订单/持仓状态
    const orderDataRaw = await api('/api/binance-ai/orders').catch(() => null);
    const orderData = orderDataRaw || {};
    const activeOrders = Object.values(orderData.orders || {});
    const positions = Object.values(orderData.positions || {});

    // 时间选择器（按分钟聚合，显示条数）
    const optionsHtml = allTimes.map(t => {
      const sel = t.time === currentTime ? 'selected' : '';
      return '<option value="' + t.time + '" ' + sel + '>' + t.time + ' (' + t.cnt + '条)' + '</option>';
    }).join('');

    const selectorHtml = '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">' +
      '<span class="u-meta">📅 分析时间:</span>' +
      '<select style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 12px;font-size:.88rem;outline:none;cursor:pointer" onchange="onBinanceAiTimeChange(this.value)">' +
        '<option value="">最新 (' + latestTime + ')</option>' +
        optionsHtml +
      '</select>' +
      '<span style="color:#484f58;font-size:.82rem">共 ' + allTimes.length + ' 个时间点</span>' +
    '</div>';

    // 评级统计 + BTC 行情
    const btcTrend = await api('/api/btc-trend').catch(() => null);

    const total = records.length;
    const ratingA = records.filter(r => (r.rating || '').startsWith('A')).length;
    const ratingB = records.filter(r => (r.rating || '').startsWith('B')).length;
    const ratingC = records.filter(r => (r.rating || '').startsWith('C')).length;
    const ratingD = records.filter(r => (r.rating || '').startsWith('D')).length;

    app.innerHTML = `
      <div class="section">
        <div class="section-title">🤖 Binance AI 评分</div>
        ${selectorHtml}
        <div class="row">
          <div class="col-4"><div class="stat-card">
            <div class="label">🟢 A 级 (推荐)</div>
            <div class="value green">${ratingA}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟡 B 级</div>
            <div class="value yellow">${ratingB}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟠 C 级</div>
            <div class="value u-orange">${ratingC}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🔴 D 级</div>
            <div class="value red">${ratingD}</div>
          </div></div>
        </div>
      </div>

      ${btcTrend ? `
      <div class="section">
        <div class="section-title">📊 BTC 六因子评分 <span class="count">${btcTrend.score}/100 · ${btcTrend.updated_at || ''}更新</span></div>
        <div class="stat-card" style="padding:14px 20px">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <span style="font-size:1.3rem;font-weight:700">$${Number(btcTrend.price).toLocaleString('en')}</span>
              <span style="font-size:.9rem;padding:3px 10px;border-radius:4px;background:${btcTrend.score >= 60 ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)'};color:${btcTrend.score >= 60 ? '#3fb950' : '#f85149'};font-weight:600">${btcTrend.score >= 70 ? '🟢 大概率盈利' : btcTrend.score >= 60 ? '🟡 保本区域' : '🔴 ' + (btcTrend.verdict || '大概率亏损')}</span>
            </div>
            <div class="u-meta-sm">
              RSI ${btcTrend.rsi} | 24h ${btcTrend.change_24h >= 0 ? '+' : ''}${btcTrend.change_24h}%
            </div>
          </div>

          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
            ${Object.entries(btcTrend.factors || {}).map(([name, f]) => {
              const pct = f.score / f.max * 100;
              const color = pct >= 70 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149';
              return '<div style="flex:1;min-width:80px;background:#0d1117;border-radius:6px;padding:8px 10px;text-align:center">' +
                '<div style="font-size:.7rem;color:#8b949e;margin-bottom:2px">' + name + '</div>' +
                '<div style="font-size:1.1rem;font-weight:700;color:' + color + '">' + f.score + '</div>' +
                '<div style="height:3px;background:#21262d;border-radius:2px;margin-top:3px">' +
                  '<div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:2px"></div>' +
                '</div>' +
              '</div>';
            }).join('')}
          </div>

          <div style="font-size:.85rem;color:#c9d1d9;line-height:1.6;padding:8px 0;border-top:1px solid #21262d">
            ${btcTrend.desc}
          </div>

          ${btcTrend.analysis ? `
          <div style="font-size:.82rem;color:#c9d1d9;line-height:1.7;padding:10px 0;border-top:1px solid #21262d">${btcTrend.analysis}</div>` : ''}

          <div style="margin-top:8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <span style="font-size:.9rem;font-weight:600;padding:6px 12px;border-radius:6px;background:${btcTrend.score >= 60 ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)'};color:${btcTrend.score >= 60 ? '#3fb950' : '#f85149'}">💡 ${btcTrend.suggest}</span>
            ${btcTrend.support ? '<span class="u-meta-78">⬇支撑 $' + Number(btcTrend.support).toLocaleString('en') + '</span>' : ''}
            ${btcTrend.resistance ? '<span class="u-meta-78">⬆阻力 $' + Number(btcTrend.resistance).toLocaleString('en') + '</span>' : ''}
          </div>
        </div>
      </div>` : ''}

      <div class="section">
        <div class="section-title">📋 币种列表 <span class="count">${total} 个 · 评分从高到低</span></div>
        <div class="table-wrap">${renderBinanceAiTable(records)}</div>
      </div>

      <div class="section">
        <div class="section-title">📦 挂单列表 <span class="count">${activeOrders.length} 笔</span></div>
        <div class="table-wrap">${renderAiEntryOrders(activeOrders)}</div>
      </div>

      ${positions.length ? `
      <div class="section">
        <div class="section-title">💼 持仓列表 <span class="count">${positions.length} 笔</span></div>
        <div class="table-wrap">${renderAiEntryPositions(positions)}</div>
      </div>` : ''}

      <div class="section">
        <div class="section-title">📄 已平仓 <span class="count">${(orderData.closed_positions||[]).length} 条</span></div>
        <div class="table-wrap">${renderAiEntryClosedPositions(orderData.closed_positions||[])}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function onBinanceAiTimeChange(value) {
  _binanceAiSelectedTime = value || null;
  renderBinanceAi();
}

// ── TradFi 品种中文名映射 ──────────────────────────────────
const TRADFI_NAMES = {
  'AAPL': '苹果', 'AMD': '超微半导体', 'AMZN': '亚马逊', 'ARM': '安谋',
  'ASTS': 'AST空间移动', 'AVGO': '博通', 'BABA': '阿里巴巴', 'BBX': 'BBX',
  'BE': '布鲁姆能源', 'BRKB': '伯克希尔B', 'BZ': 'BZ',
  'CBRS': 'CBRS', 'CL': '世邦魏理仕',
  'CLUS': 'CLUS', 'COHR': '相干公司', 'COIN': 'Coinbase',
  'COPPER': '铜ETF', 'CRCL': 'CRCL', 'CRWV': 'CRWV',
  'CSCO': '思科', 'DIS': '迪士尼', 'DRAM': 'DRAM',
  'EWJ': '日本ETF', 'EWT': '台湾ETF', 'EWY': '韩国ETF',
  'FLNC': 'FLNC', 'GOOGL': '谷歌', 'HD': '家得宝',
  'HOOD': 'Robinhood', 'INTC': '英特尔', 'JPM': '摩根大通',
  'LITE': 'Lumentum', 'LLY': '礼来', 'META': 'Meta',
  'MRVL': '美满电子', 'MSFT': '微软', 'MSTR': '微策略',
  'MU': '美光科技', 'NATGAS': '天然气ETF', 'NBIS': 'NBIS',
  'NOK': '诺基亚', 'NVDA': '英伟达', 'NVO': '诺和诺德',
  'OPENAI': 'OpenAI', 'ORCL': '甲骨文', 'PAYP': 'PayPal',
  'PLTR': 'Palantir', 'QCOM': '高通', 'QNTX': 'QNTX',
  'QQQ': '纳斯达克100ETF', 'RKLB': '火箭实验室', 'SNDK': '闪迪',
  'SOXL': '半导体三倍做多', 'SPCX': 'SPCX', 'SPY': '标普500ETF',
  'TSLA': '特斯拉', 'TSM': '台积电', 'UBER': '优步',
  'USAR': 'USAR', 'V': 'Visa',
  'WDC': '西部数据', 'WMT': '沃尔玛',
  'XAG': '白银ETF', 'XAU': '黄金ETF', 'XPD': '钯金ETF', 'XPT': '铂金ETF',
};

function renderBinanceAiTable(records, isTradfi) {
  if (!records || !records.length) return '<div class="empty">暂无数据</div>';

  function ratingBadge(r) {
    const rating = (r || '').toUpperCase();
    if (rating.startsWith('A')) return '<span class="badge badge-green u-fw7">A</span>';
    if (rating.startsWith('B')) return '<span class="badge badge-yellow u-fw7">B</span>';
    if (rating.startsWith('C')) return '<span class="badge" style="background:rgba(240,136,62,.15);color:#f0883e;font-weight:700">C</span>';
    if (rating.startsWith('D')) return '<span class="badge badge-red u-fw7">D</span>';
    return '<span class="badge badge-gray">' + escHtml(rating) + '</span>';
  }

  function scoreBar(s) {
    const n = Number(s);
    const c = n >= 80 ? '#3fb950' : n >= 70 ? '#d29922' : n >= 60 ? '#f0883e' : '#f85149';
    const w = Math.max(5, Math.min(100, n));
    return '<div style="display:flex;align-items:center;gap:6px">' +
      '<div style="width:60px;height:6px;background:#21262d;border-radius:3px;overflow:hidden">' +
        '<div style="height:100%;width:' + w + '%;background:' + c + ';border-radius:3px"></div>' +
      '</div>' +
      '<span style="color:' + c + ';font-weight:700;min-width:40px;text-align:right">' + n.toFixed(1) + '</span>' +
    '</div>';
  }

  function priceStr(v) {
    if (v == null) return '-';
    const n = Number(v);
    if (n === 0) return '-';
    return n >= 1000 ? '$' + n.toLocaleString('en', {minFraction:2,maxFraction:2})
         : n >= 1    ? '$' + n.toFixed(4)
                     : '$' + n.toFixed(6);
  }

  function volStr(v) {
    const n = Number(v);
    if (!n) return '-';
    if (n >= 1e9) return (n / 1e9).toFixed(2) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(2) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(2) + 'K';
    return n.toFixed(2);
  }

  let html = `<table>
    <thead><tr>
      <th>币种${isTradfi ? '<span style="font-weight:400">/中文名</span>' : ''}</th><th>评分</th><th>评级</th><th>当前价</th><th>24h涨跌</th>
      <th>24h成交量</th><th>入场低限</th><th>入场高限</th><th>止损价</th><th>目标价</th>
    </tr></thead><tbody>`;

  for (const r of records) {
    const chg = r.change_24h != null ? Number(r.change_24h) : null;
    const chgCls = chg >= 0 ? 'green' : 'red';
    const chgStr = chg != null ? (chg > 0 ? '+' : '') + chg.toFixed(2) + '%' : '-';

    const symbolClean = (r.symbol || '').replace(/USDT$/i, '');
    const okxUrl = 'https://www.okx.com/zh-hans/trade-swap/' + symbolClean.toLowerCase() + '-usdt-swap';

    const commentary = r.commentary || '';
    const commentaryHtml = commentary
      ? '<div style="font-size:.72rem;color:#8b949e;margin-top:3px;max-width:280px;line-height:1.3;overflow:hidden;text-overflow:ellipsis;display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical" title="' + escHtml(commentary) + '">' + escHtml(commentary) + '</div>'
      : '';

    // 解析回调点位: callback_points 格式 "high-low"（如 "578.4075-560.1420"）
    let entryLow = '-', entryHigh = '-';
    if (r.callback_points && String(r.callback_points) !== 'None') {
      const parts = String(r.callback_points).split('-');
      if (parts.length >= 2) {
        entryHigh = parts[0].trim();
        entryLow = parts[1].trim();
      }
    }

    // 中文名（仅 TradFi 页面）
    const cnName = isTradfi && TRADFI_NAMES[symbolClean] ? ' <span class="u-meta-78">' + TRADFI_NAMES[symbolClean] + '</span>' : '';

    html += '<tr>' +
      '<td>' + (r.direction === 'down' ? '<span class="red">空</span>' : '<span class="green">多</span>') + '</td>' +
      '<td>' + scoreBar(r.profit_score) + '</td>' +
      '<td style="text-align:center;font-size:1rem">' + ratingBadge(r.rating) + '</td>' +
      '<td class="mono">' + priceStr(r.current_price) + '</td>' +
      '<td class="mono ' + chgCls + '">' + chgStr + '</td>' +
      '<td class="mono u-muted">' + volStr(r.volume_24h) + '</td>' +
      '<td class="mono">$' + entryLow + '</td>' +
      '<td class="mono">$' + entryHigh + '</td>' +
      '<td class="mono red">' + priceStr(r.stop_loss) + '</td>' +
      '<td class="mono green">' + priceStr(r.target_price) + '</td>' +
    '</tr>';
  }
  html += '</tbody></table>';
  return html;
}


// ── AI入场 订单／持仓表格 ──────────────────────────────────

function getCoinLink(coin) {
  if (window._bbRideLinkExchange === 'okx') {
    return 'https://www.okx.com/zh-hans/trade-swap/' + coin.toLowerCase() + '-usdt-swap';
  }
  return 'https://www.binance.com/zh-CN/futures/' + coin + 'USDT';
}

function renderAiEntryOrders(orders) {
  if (!orders || !orders.length) return '<div class="empty">暂无挂单</div>';
  let html = `<table>
    <thead><tr>
      <th>币种</th><th>方向</th><th>挂单价</th><th>挂单量</th>
      <th>金额(USDT)</th><th>已挂时间</th><th>止盈</th><th>止损</th><th>状态</th><th>单号</th>
    </tr></thead><tbody>`;
  for (const o of orders) {
    const isLong = o.direction === 'LONG' || o.side === 'buy';
    const sideHtml = isLong ? '<span class="badge badge-green">买入</span>' : '<span class="badge badge-red">卖出</span>';
    const qty = o.quantity_coin || o.quantity;
    const amount = (o.price * qty).toFixed(2);
    const age = o.age_hours != null
      ? (o.age_hours < 1 ? (o.age_hours * 60).toFixed(0) + '分钟' : o.age_hours.toFixed(1) + '小时')
      : '-';
    const statusHtml = o.status === 'open'
      ? '<span class="badge badge-blue">挂单中</span>'
      : o.status === 'closed'
        ? '<span class="badge badge-green">已成交</span>'
        : '<span class="badge badge-gray">' + escHtml(o.status) + '</span>';

    html += '<tr>' +
      '<td><strong><a href="' + getCoinLink(o.coin) + '" target="_blank" rel="noopener" class="u-link">' + escHtml(o.coin) + ' ↗</a></strong></td>' +
      '<td>' + sideHtml + '</td>' +
      '<td class="mono">$' + Number(o.price).toFixed(4) + '</td>' +
      '<td class="mono">' + Number(o.quantity).toFixed(2) + '</td>' +
      '<td class="mono">' + amount + '</td>' +
      '<td class="u-muted">' + age + '</td>' +
      '<td class="mono green">' + (o.tp_price ? '$' + Number(o.tp_price).toFixed(4) : '-') + '</td>' +
      '<td class="mono red">' + (o.sl_price ? '$' + Number(o.sl_price).toFixed(4) : '-') + '</td>' +
      '<td>' + statusHtml + '</td>' +
      '<td class="u-faint u-meta-72">' + ((o.order_id||'').slice(-10)||'-') + '</td>' +
    '</tr>';
  }
  html += '</tbody></table>';
  return html;
}

function renderAiEntryPositions(positions) {
  if (!positions || !positions.length) return '<div class="empty">暂无持仓</div>';
  let html = `<table>
    <thead><tr>
      <th>币种</th><th>方向</th><th>入场价</th><th>数量</th>
      <th>金额(USDT)</th><th>当前价</th><th>盈亏</th><th>盈亏%</th><th>成交时间</th><th>单号</th>
    </tr></thead><tbody>`;
  for (const p of positions) {
    const isLong = p.direction !== 'SHORT';
    const qty = p.quantity_coin || p.quantity;
    const amount = (p.entry_price * qty).toFixed(2);
    const curPrice = p.current_price || 0;
    const upnl = p.unrealized_pnl;
    const upnlPct = p.unrealized_pnl_pct;
    const upnlStr = upnl != null ? (upnl > 0 ? '+' : '') + upnl.toFixed(2) : '-';
    const upnlPctStr = upnlPct != null ? (upnlPct > 0 ? '+' : '') + upnlPct.toFixed(2) + '%' : '-';

    html += '<tr>' +
      '<td><strong><a href="' + getCoinLink(p.coin) + '" target="_blank" rel="noopener" class="u-link">' + escHtml(p.coin) + ' ↗</a></strong></td>' +
      '<td>' + (isLong ? '<span class="badge badge-green">多头</span>' : '<span class="badge badge-red">空头</span>') + '</td>' +
      '<td class="mono">$' + Number(p.entry_price).toFixed(4) + '</td>' +
      '<td class="mono">' + Number(p.quantity).toFixed(2) + '</td>' +
      '<td class="mono">' + amount + '</td>' +
      '<td class="mono">' + (curPrice ? '$' + Number(curPrice).toFixed(4) : '-') + '</td>' +
      '<td class="mono ' + (upnl > 0 ? 'green' : upnl < 0 ? 'red' : '') + '">' + upnlStr + '</td>' +
      '<td class="mono ' + (upnlPct > 0 ? 'green' : upnlPct < 0 ? 'red' : '') + '">' + upnlPctStr + '</td>' +
      '<td class="u-muted">' + (p.filled_at_str || '-') + '</td>' +
      '<td class="u-faint u-meta-72">' + ((p.order_id||'').slice(-10)||'-') + '</td>' +
    '</tr>';
  }
  html += '</tbody></table>';
  return html;
}

function renderAiEntryClosedPositions(closed) {
  if (!closed || !closed.length) return '<div class="empty">暂无已平仓记录</div>';
  const sorted = [...closed].reverse();
  let html = `<table>
    <thead><tr>
      <th>币种</th><th>方向</th><th>开仓时间</th><th>开仓价</th>
      <th>平仓时间</th><th>平仓价</th><th>数量</th><th>盈亏(USDT)</th><th>盈亏%</th><th>策略</th><th>单号</th>
    </tr></thead><tbody>`;
  for (const r of sorted) {
    const pnl = r.pnl != null ? r.pnl : 0;
    const pnlPct = r.pnl_pct != null ? r.pnl_pct : 0;
    html += '<tr>' +
      '<td><strong><a href="' + getCoinLink(r.coin) + '" target="_blank" rel="noopener" class="u-link">' + escHtml(r.coin) + ' ↗</a></strong></td>' +
      '<td>' + (r.direction === 'SHORT' ? '<span class="badge badge-red">空头</span>' : '<span class="badge badge-green">多头</span>') + '</td>' +
      '<td class="u-muted">' + (r.filled_at_str || '-') + '</td>' +
      '<td class="mono">$' + Number(r.entry_price || 0).toFixed(4) + '</td>' +
      '<td class="u-muted">' + (r.close_time_str || '-') + '</td>' +
      '<td class="mono">$' + Number(r.close_price || 0).toFixed(4) + '</td>' +
      '<td class="mono">' + Number(r.quantity || 0).toFixed(2) + '</td>' +
      '<td class="mono ' + pnlClass(pnl) + '">' + (pnl > 0 ? '+' : '') + pnl.toFixed(2) + '</td>' +
      '<td class="mono ' + pnlClass(pnlPct) + '">' + (pnlPct > 0 ? '+' : '') + pnlPct.toFixed(2) + '%</td>' +
      '<td class="u-muted">' + escHtml(r.strategy || '-') + '</td>' +
      '<td class="u-faint u-meta-72">' + ((r.order_id||'').slice(-10)||'-') + '</td>' +
    '</tr>';
  }
  html += '</tbody></table>';
  return html;
}


// ── OKX AI 页面 ─────────────────────────────────────────────

let _okxAiSelectedTime = null;

async function renderOkxAi() {
  setActiveNav('okx-ai');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [timesData, data] = await Promise.all([
      api('/api/okx-ai/times').catch(() => ({ times: [] })),
      _okxAiSelectedTime
        ? api('/api/okx-ai?analysis_time=' + encodeURIComponent(_okxAiSelectedTime))
        : api('/api/okx-ai'),
    ]);

    const allTimes = timesData.times || [];
    const latestTime = data.analysis_time;
    if (!_okxAiSelectedTime && latestTime) {
      _okxAiSelectedTime = latestTime;
    }

    const records = data.records || [];
    const currentTime = _okxAiSelectedTime || latestTime;

    const optionsHtml = allTimes.map(t => {
      const sel = t.time === currentTime ? 'selected' : '';
      return '<option value="' + t.time + '" ' + sel + '>' + t.time + ' (' + t.cnt + '条)' + '</option>';
    }).join('');

    const selectorHtml = '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">' +
      '<span class="u-meta">📅 分析时间:</span>' +
      '<select style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 12px;font-size:.88rem;outline:none;cursor:pointer" onchange="onOkxAiTimeChange(this.value)">' +
        '<option value="">最新 (' + latestTime + ')</option>' +
        optionsHtml +
      '</select>' +
      '<span style="color:#484f58;font-size:.82rem">共 ' + allTimes.length + ' 个时间点</span>' +
    '</div>';

    // 获取订单/持仓状态
    const orderDataRaw = await api('/api/okx-ai/orders').catch(() => null);
    const orderData = orderDataRaw || {};
    const activeOrders = Object.values(orderData.orders || {});
    const positions = Object.values(orderData.positions || {});

    // BTC 行情
    const btcTrend = await api('/api/btc-trend').catch(() => null);

    const total = records.length;
    const ratingA = records.filter(r => (r.rating || '').startsWith('A')).length;
    const ratingB = records.filter(r => (r.rating || '').startsWith('B')).length;
    const ratingC = records.filter(r => (r.rating || '').startsWith('C')).length;
    const ratingD = records.filter(r => (r.rating || '').startsWith('D')).length;

    app.innerHTML = `
      <div class="section">
        <div class="section-title">🤖 OKX AI 评分
          <span style="float:right;font-size:.75rem;font-weight:400">
            <a href="/okx-danger" style="color:#f85149;text-decoration:none;margin-left:12px">⚠️Danger(OKX)</a>
            <a href="/binance-danger" style="color:#f85149;text-decoration:none;margin-left:8px">⚠️Danger(币安)</a>
          </span>
        </div></div>
        ${selectorHtml}
        <div class="row">
          <div class="col-4"><div class="stat-card">
            <div class="label">🟢 A 级 (推荐)</div>
            <div class="value green">${ratingA}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟡 B 级</div>
            <div class="value yellow">${ratingB}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟠 C 级</div>
            <div class="value u-orange">${ratingC}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🔴 D 级</div>
            <div class="value red">${ratingD}</div>
          </div></div>
        </div>
      </div>

      ${btcTrend ? `
      <div class="section">
        <div class="section-title">📊 BTC 六因子评分 <span class="count">${btcTrend.score}/100 · ${btcTrend.updated_at || ''}更新</span></div>
        <div class="stat-card" style="padding:14px 20px">
          <div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;margin-bottom:10px">
            <div style="display:flex;align-items:center;gap:12px;flex-wrap:wrap">
              <span style="font-size:1.3rem;font-weight:700">$${Number(btcTrend.price).toLocaleString('en')}</span>
              <span style="font-size:.9rem;padding:3px 10px;border-radius:4px;background:${btcTrend.score >= 60 ? 'rgba(63,185,80,0.15)' : 'rgba(248,81,73,0.15)'};color:${btcTrend.score >= 60 ? '#3fb950' : '#f85149'};font-weight:600">${btcTrend.score >= 70 ? '🟢 大概率盈利' : btcTrend.score >= 60 ? '🟡 保本区域' : '🔴 ' + (btcTrend.verdict || '大概率亏损')}</span>
            </div>
            <div class="u-meta-sm">
              RSI ${btcTrend.rsi} | 24h ${btcTrend.change_24h >= 0 ? '+' : ''}${btcTrend.change_24h}%
            </div>
          </div>

          <div style="display:flex;flex-wrap:wrap;gap:6px;margin-bottom:10px">
            ${Object.entries(btcTrend.factors || {}).map(([name, f]) => {
              const pct = f.score / f.max * 100;
              const color = pct >= 70 ? '#3fb950' : pct >= 50 ? '#d29922' : '#f85149';
              return '<div style="flex:1;min-width:80px;background:#0d1117;border-radius:6px;padding:8px 10px;text-align:center">' +
                '<div style="font-size:.7rem;color:#8b949e;margin-bottom:2px">' + name + '</div>' +
                '<div style="font-size:1.1rem;font-weight:700;color:' + color + '">' + f.score + '</div>' +
                '<div style="height:3px;background:#21262d;border-radius:2px;margin-top:3px">' +
                  '<div style="height:100%;width:' + pct + '%;background:' + color + ';border-radius:2px"></div>' +
                '</div>' +
              '</div>';
            }).join('')}
          </div>

          <div style="font-size:.85rem;color:#c9d1d9;line-height:1.6;padding:8px 0;border-top:1px solid #21262d">
            ${btcTrend.desc}
          </div>

          ${btcTrend.analysis ? `
          <div style="font-size:.82rem;color:#c9d1d9;line-height:1.7;padding:10px 0;border-top:1px solid #21262d">${btcTrend.analysis}</div>` : ''}

          <div style="margin-top:8px;display:flex;align-items:center;gap:10px;flex-wrap:wrap">
            <span style="font-size:.9rem;font-weight:600;padding:6px 12px;border-radius:6px;background:${btcTrend.score >= 60 ? 'rgba(63,185,80,0.1)' : 'rgba(248,81,73,0.1)'};color:${btcTrend.score >= 60 ? '#3fb950' : '#f85149'}">💡 ${btcTrend.suggest}</span>
            ${btcTrend.support ? '<span class="u-meta-78">⬇支撑 $' + Number(btcTrend.support).toLocaleString('en') + '</span>' : ''}
            ${btcTrend.resistance ? '<span class="u-meta-78">⬆阻力 $' + Number(btcTrend.resistance).toLocaleString('en') + '</span>' : ''}
          </div>
        </div>
      </div>` : ''}

      <div class="section">
        <div class="section-title">📋 币种列表 <span class="count">${total} 个 · 评分从高到低</span></div>
        <div class="table-wrap">${renderBinanceAiTable(records)}</div>
      </div>

      <div class="section">
        <div class="section-title">📦 挂单列表 <span class="count">${activeOrders.length} 笔</span></div>
        <div class="table-wrap">${renderAiEntryOrders(activeOrders)}</div>
      </div>

      ${positions.length ? `
      <div class="section">
        <div class="section-title">💼 持仓列表 <span class="count">${positions.length} 笔</span></div>
        <div class="table-wrap">${renderAiEntryPositions(positions)}</div>
      </div>` : ''}

      <div class="section">
        <div class="section-title">📄 已平仓 <span class="count">${(orderData.closed_positions||[]).length} 条</span></div>
        <div class="table-wrap">${renderAiEntryClosedPositions(orderData.closed_positions||[])}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function onOkxAiTimeChange(value) {
  _okxAiSelectedTime = value || null;
  renderOkxAi();
}

// ── TradFi AI 页面 ──────────────────────────────────────────

let _tradfiAiSelectedTime = null;

async function renderTradfiAi() {
  setActiveNav('tradfi-ai');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    const [timesData, data] = await Promise.all([
      api('/api/tradfi-ai/times').catch(() => ({ times: [] })),
      _tradfiAiSelectedTime
        ? api('/api/tradfi-ai?analysis_time=' + encodeURIComponent(_tradfiAiSelectedTime))
        : api('/api/tradfi-ai'),
    ]);

    const allTimes = timesData.times || [];
    const latestTime = data.analysis_time;
    if (!_tradfiAiSelectedTime && latestTime) {
      _tradfiAiSelectedTime = latestTime;
    }

    const records = data.records || [];
    const currentTime = _tradfiAiSelectedTime || latestTime;

    const optionsHtml = allTimes.map(t => {
      const sel = t.time === currentTime ? 'selected' : '';
      return '<option value="' + t.time + '" ' + sel + '>' + t.time + ' (' + t.cnt + '条)' + '</option>';
    }).join('');

    const selectorHtml = '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">' +
      '<span class="u-meta">📅 分析时间:</span>' +
      '<select style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 12px;font-size:.88rem;outline:none;cursor:pointer" onchange="onTradfiAiTimeChange(this.value)">' +
        '<option value="">最新 (' + (latestTime||'') + ')</option>' +
        optionsHtml +
      '</select>' +
      '<span style="color:#484f58;font-size:.82rem">共 ' + allTimes.length + ' 个时间点</span>' +
    '</div>';

    const total = records.length;
    const ratingA = records.filter(r => (r.rating || '').startsWith('A')).length;
    const ratingB = records.filter(r => (r.rating || '').startsWith('B')).length;
    const ratingC = records.filter(r => (r.rating || '').startsWith('C')).length;
    const ratingD = records.filter(r => (r.rating || '').startsWith('D')).length;

    app.innerHTML = `
      <div class="section">
        <div class="section-title">📈 TradFi AI 评分 <span class="count">币安美股/ETF/商品</span></div>
        ${selectorHtml}
        <div class="row">
          <div class="col-4"><div class="stat-card">
            <div class="label">🟢 A 级 (推荐)</div>
            <div class="value green">${ratingA}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟡 B 级</div>
            <div class="value yellow">${ratingB}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🟠 C 级</div>
            <div class="value u-orange">${ratingC}</div>
          </div></div>
          <div class="col-4"><div class="stat-card">
            <div class="label">🔴 D 级</div>
            <div class="value red">${ratingD}</div>
          </div></div>
        </div>
        <div style="background:#0d1117;padding:10px 16px;border-radius:8px;margin-top:8px;font-size:.78rem;color:#8b949e">
          💡 基于币安合约 TradFi 品种（美股/ETF/商品）的6维度评分分析。仅包含 TradFi 类品种（如 NVDA、AAPL、TSLA、QQQ、XAU 等）。
        </div>
      </div>

      <div class="section">
        <div class="section-title">📋 币种列表 <span class="count">${total} 个 · 评分从高到低</span></div>
        <div class="table-wrap">${renderBinanceAiTable(records, true)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function onTradfiAiTimeChange(value) {
  _tradfiAiSelectedTime = value || null;
  renderTradfiAi();
}

// ── OKX 做多危险指数 ──────────────────────────────────────

let _okxDangerSelectedTime = null;
let _binanceDangerSelectedTime = null;

async function renderOkxDanger() {
  setActiveNav('okx-danger');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  try {
    console.log('[Danger] Fetching API...');
    const data = await (_okxDangerSelectedTime
      ? api('/api/okx-danger?analysis_time=' + encodeURIComponent(_okxDangerSelectedTime))
      : api('/api/okx-danger'));
    console.log('[Danger] API response:', data);
    console.log('[Danger] records:', data?.records?.length, 'analysis_time:', data?.analysis_time);

    const records = data.records || [];
    const allTimes = data.times || [];
    const latestTime = data.analysis_time;
    const currentTime = _okxDangerSelectedTime || latestTime;

    if (!_okxDangerSelectedTime && latestTime) {
      _okxDangerSelectedTime = latestTime;
    }

    const optionsHtml = allTimes.map(t =>
      '<option value="' + t.time + '"' + (t.time === currentTime ? ' selected' : '') + '>' +
        t.time + ' (' + t.cnt + '条)' +
      '</option>'
    ).join('');

    const selectorHtml =
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">' +
      '<span class="u-meta">📅 分析时间:</span>' +
      '<select style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 12px;font-size:.88rem;outline:none;cursor:pointer" onchange="onOkxDangerTimeChange(this.value)">' +
        '<option value="">最新 (' + (latestTime||'') + ')</option>' +
        optionsHtml +
      '</select></div>';

    // 按风险等级统计
    const critical = records.filter(r => r.risk_level === 'CRITICAL').length;
    const high = records.filter(r => r.risk_level === 'HIGH').length;
    const danger = records.filter(r => r.risk_level === 'DANGER').length;
    const warning = records.filter(r => r.risk_level === 'WARNING').length;
    const safe = records.filter(r => r.risk_level === 'SAFE' || r.risk_level === 'VERY_SAFE').length;

    // 获取 AI 分析
    const analysisData = await api('/api/okx-danger/analysis').catch(() => null);
    const analysisHtml = analysisData?.analysis || '';
    const analysisTimeStr = analysisData?.analysis_time || '';

    app.innerHTML = `
      <div class="section">
        <div class="section-title">⚠️ OKX 做多危险指数评分 <span class="count">总分范围0~100</span></div>
        ${selectorHtml}
        <div class="row">
          <div class="col-2"><div class="stat-card"><div class="label">🛑 CRITICAL</div><div class="value red">${critical}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">🔥 HIGH</div><div class="value u-orange">${high}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">⚠️ DANGER</div><div class="value yellow">${danger}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">🤔 WARNING</div><div class="value yellow">${warning}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">✅ SAFE</div><div class="value green">${safe}</div></div></div>
        </div>
      </div>

      ${function(){
        if (!analysisHtml) return '';
        var lines = analysisHtml.split('\n');
        var summary = '', danger = '', safe = '', advice = '';
        var section = '';
        for (var i = 0; i < lines.length; i++) {
          var l = lines[i].trim();
          if (!l) continue;
          if (/🔥/.test(l)) { section = 'danger'; continue; }
          if (/✅/.test(l)) { section = 'safe'; continue; }
          if (/💡/.test(l)) { section = 'advice'; continue; }
          if (section === '' && /[平均分]/.test(l)) { summary = l; continue; }
          if (section === 'danger')
            danger += '<div style="padding:3px 0 3px 8px;border-left:2px solid #f85149;margin:2px 0;color:#c9d1d9">' + l + '</div>';
          else if (section === 'safe')
            safe += '<div style="padding:3px 0 3px 8px;border-left:2px solid #3fb950;margin:2px 0;color:#c9d1d9">' + l + '</div>';
          else if (section === 'advice')
            advice = l;
        }
        var rows = '';
        if (summary) rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#8b949e">行情总结</div><div style="background:#0d1117;padding:10px 14px;color:#c9d1d9">' + summary + '</div>';
        if (danger)  rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#f85149">🔥 重点回避</div><div style="background:#0d1117;padding:10px 14px">' + danger + '</div>';
        if (safe)    rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#3fb950">✅ 相对安全</div><div style="background:#0d1117;padding:10px 14px">' + safe + '</div>';
        if (advice)  rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#d29922">💡 建议</div><div style="background:#0d1117;padding:10px 14px;color:#c9d1d9">' + advice + '</div>';
        return '<div class="section"><div class="section-title">📊 AI 评分分析 <span class="count">' + analysisTimeStr + '</span></div>' +
          '<div style="display:grid;grid-template-columns:90px 1fr;gap:1px;background:#21262d;border-radius:8px;overflow:hidden;font-size:.85rem">' + rows + '</div></div>';
      }()}

      <div class="section">
        <div class="table-wrap">${renderDangerTable(records)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function renderDangerTable(records) {
  if (!records || !records.length) return '<div class="empty">暂无数据</div>';

  const rows = records.map(r => {
    const sc = r.total_score || 0;
    const emoji = sc >= 75 ? '🛑' : sc >= 65 ? '🔥' : sc >= 55 ? '⚠️' : sc >= 45 ? '🤔' : sc >= 35 ? '✅' : '🟢';
    const color = sc >= 65 ? '#f85149' : sc >= 55 ? '#d29922' : sc >= 45 ? '#8b949e' : '#3fb950';
    const price = Number(r.current_price || 0);
    const priceStr = price < 0.001 ? price.toExponential(3) : price < 1 ? price.toFixed(6) : price.toFixed(2);
    const chg = r.chg_24h || 0;
    const chgColor = chg >= 0 ? '#3fb950' : '#f85149';
    const fr = (Number(r.funding_rate) * 100);
    const frStr = fr <= -0.5 ? fr.toFixed(3) : fr.toFixed(4);
    const riskFactors = r.risk_factors === 'none' ? '' : (r.risk_factors||'').split(',').slice(0, 3).join(' ');
    const signal = r.trade_signal || '';

    return '<tr>' +
      '<td style="font-weight:600;color:' + color + '">' + emoji + ' ' + sc + '</td>' +
      '<td class="u-fw6"><a href="https://www.okx.com/zh-hans/trade-swap/' + r.coin_name.toLowerCase() + '-usdt-swap" target="_blank" class="u-link">' + r.coin_name + ' ↗</a></td>' +
      '<td>' + priceStr + '</td>' +
      '<td style="color:' + chgColor + '">' + (chg >= 0 ? '+' : '') + Number(chg).toFixed(1) + '%</td>' +
      '<td style="font-size:.82rem">' + r.score_ema + '|' + r.score_funding + '|' + r.score_momentum + '|' + r.score_position + '|' + r.score_rsi + '|' + r.score_volatility + '|' + r.score_dispersion + '</td>' +
      '<td>' + frStr + '%</td>' +
      '<td style="font-size:.78rem;color:#8b949e;max-width:120px;overflow:hidden;white-space:nowrap;text-overflow:ellipsis" title="' + riskFactors + '">' + riskFactors + '</td>' +
      '<td class="u-meta-78">' + signal + '</td>' +
      '</tr>';
  }).join('');

  return '<table class="table"><thead><tr>' +
    '<th>得分</th><th>币种</th><th>价格</th><th>24h</th><th>E|L|M|P|R|V|D</th><th>费率%</th><th>风险因子</th><th>信号</th>' +
    '</tr></thead><tbody>' + rows + '</tbody></table>';
}

function onOkxDangerTimeChange(value) {
  _okxDangerSelectedTime = value || null;
  renderOkxDanger();
}

async function renderBinanceDanger() {
  setActiveNav('binance-danger');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';
  try {
    const data = await (_binanceDangerSelectedTime
      ? api('/api/binance-danger?analysis_time=' + encodeURIComponent(_binanceDangerSelectedTime))
      : api('/api/binance-danger'));
    const records = data.records || [];
    const allTimes = data.times || [];
    const latestTime = data.analysis_time;
    const currentTime = _binanceDangerSelectedTime || latestTime;
    if (!_binanceDangerSelectedTime && latestTime) _binanceDangerSelectedTime = latestTime;

    const optionsHtml = allTimes.map(t =>
      '<option value="' + t.time + '"' + (t.time === currentTime ? ' selected' : '') + '>' +
        t.time + ' (' + t.cnt + '条)' + '</option>'
    ).join('');

    const selectorHtml =
      '<div style="display:flex;align-items:center;gap:10px;margin-bottom:12px;flex-wrap:wrap">' +
      '<span class="u-meta">📅 分析时间:</span>' +
      '<select style="background:#0d1117;border:1px solid #30363d;border-radius:6px;color:#c9d1d9;padding:6px 12px;font-size:.88rem;outline:none;cursor:pointer" onchange="onBinanceDangerTimeChange(this.value)">' +
        '<option value="">最新 (' + (latestTime||'') + ')</option>' + optionsHtml +
      '</select></div>';

    const critical = records.filter(r => r.risk_level === 'CRITICAL').length;
    const high = records.filter(r => r.risk_level === 'HIGH').length;
    const danger = records.filter(r => r.risk_level === 'DANGER').length;
    const warning = records.filter(r => r.risk_level === 'WARNING').length;
    const safe = records.filter(r => r.risk_level === 'SAFE' || r.risk_level === 'VERY_SAFE').length;

    const analysisData = await api('/api/binance-danger/analysis').catch(() => null);
    const analysisHtml = analysisData?.analysis || '';
    const analysisTimeStr = analysisData?.analysis_time || '';

    app.innerHTML = `
      <div class="section">
        <div class="section-title">⚠️ 币安做多危险指数评分 <span class="count">总分范围0~100</span></div>
        ${selectorHtml}
        <div class="row">
          <div class="col-2"><div class="stat-card"><div class="label">🛑 CRITICAL</div><div class="value red">${critical}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">🔥 HIGH</div><div class="value u-orange">${high}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">⚠️ DANGER</div><div class="value yellow">${danger}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">🤔 WARNING</div><div class="value yellow">${warning}</div></div></div>
          <div class="col-2"><div class="stat-card"><div class="label">✅ SAFE</div><div class="value green">${safe}</div></div></div>
        </div>
      </div>

      ${function(){
        if (!analysisHtml) return '';
        var lines = analysisHtml.split('\n');
        var summary = '', danger = '', safe = '', advice = '';
        var section = '';
        for (var i = 0; i < lines.length; i++) {
          var l = lines[i].trim();
          if (!l) continue;
          if (/🔥/.test(l)) { section = 'danger'; continue; }
          if (/✅/.test(l)) { section = 'safe'; continue; }
          if (/💡/.test(l)) { section = 'advice'; continue; }
          if (section === '' && /[平均分]/.test(l)) { summary = l; continue; }
          if (section === 'danger')
            danger += '<div style="padding:3px 0 3px 8px;border-left:2px solid #f85149;margin:2px 0;color:#c9d1d9">' + l + '</div>';
          else if (section === 'safe')
            safe += '<div style="padding:3px 0 3px 8px;border-left:2px solid #3fb950;margin:2px 0;color:#c9d1d9">' + l + '</div>';
          else if (section === 'advice')
            advice = l;
        }
        var rows = '';
        if (summary) rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#8b949e">行情总结</div><div style="background:#0d1117;padding:10px 14px;color:#c9d1d9">' + summary + '</div>';
        if (danger)  rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#f85149">🔥 重点回避</div><div style="background:#0d1117;padding:10px 14px">' + danger + '</div>';
        if (safe)    rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#3fb950">✅ 相对安全</div><div style="background:#0d1117;padding:10px 14px">' + safe + '</div>';
        if (advice)  rows += '<div style="background:#0d1117;padding:10px 14px;font-weight:600;color:#d29922">💡 建议</div><div style="background:#0d1117;padding:10px 14px;color:#c9d1d9">' + advice + '</div>';
        return '<div class="section"><div class="section-title">📊 AI 评分分析 <span class="count">' + analysisTimeStr + '</span></div>' +
          '<div style="display:grid;grid-template-columns:90px 1fr;gap:1px;background:#21262d;border-radius:8px;overflow:hidden;font-size:.85rem">' + rows + '</div></div>';
      }()}

      <div class="section">
        <div class="table-wrap">${renderDangerTable(records)}</div>
      </div>
    `;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function onBinanceDangerTimeChange(value) {
  _binanceDangerSelectedTime = value || null;
  renderBinanceDanger();
}

// ── BB Ride 布林骑行扫描 ──────────────────────────────────

let _bbRideExchange = 'binance';  // 'binance' | 'okx'
let _bbRideMode = 'scanner';       // 'scanner' | 'breakout'

async function renderBbRide() {
  setActiveNav('bb-ride');
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载底部启动形态...</div>';
  try {
    if (_bbRideMode === 'breakout') {
      await _renderBbRideBreakout();
    } else if (_bbRideMode === 'wave') {
      await _renderBbRideWave();
    } else if (_bbRideMode === 'pushretest') {
      await _renderBbRidePushRetest();
    } else {
      await _renderBbRideWithExchange(_bbRideExchange);
    }
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

async function _renderBbRideBreakout() {
  _bbRideMode = 'breakout';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载突破信号...</div>';
  try {
    const data = await api('/api/bb-ride/breakout');
    const results = data.results || [];
    const scanTime = data.scan_time || '-';

    let h = `<div class="page-header">
      <div class="section-title">📊 V型反转突破信号</div>
      <div class="page-subtitle">扫描: ${fmtFullTime(scanTime)} | OKX热度前80 + 强制名单</div>
      <div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">
        <span class="u-meta">模式:</span>
        <button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'scanner\')">扫描信号</button>
        <button class="btn-sm btn-primary" onclick="_switchBbRideMode(\'breakout\')">突破信号</button>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'wave\')">波浪信号</button>' +
        <span style="margin-left:12px;font-size:.85rem;color:#8b949e">
          共 <strong style="color:#f0f6fc">${results.length}</strong> 个突破形态
        </span>
      </div>
    </div>`;

    if (!results.length) {
      h += '<div class="empty" style="margin-top:20px">暂无突破信号</div>';
    } else {
      // 按评分排序
      const sorted = [...results].sort((a,b) => (b.score||0) - (a.score||0));
      h += `<div class="table-wrap"><table class="data-table"><thead><tr>
        <th>币种</th><th>前期高点</th><th>高点时间</th><th>确认完成</th><th>中级跌幅</th><th>站上确认</th><th>评分</th>
      </tr></thead><tbody>`;
      for (const r of sorted) {
        const scoreStr = '⭐'.repeat(r.score || 0) + '☆'.repeat(5 - (r.score || 0));
        const linkUrl = 'https://www.okx.com/zh-hans/trade-swap/' + r.coin.toLowerCase() + '-usdt-swap';
        h += `<tr>
          <td><strong><a href="${linkUrl}" target="_blank" rel="noopener" class="u-link">${escHtml(r.coin)} ↗</a></strong></td>
          <td>${fmtCryptoPrice(r.prev_high)}</td>
          <td class="u-muted">${r.prev_high_time || '-'}</td>
          <td class="u-muted">${r.confirm_time || '-'}</td>
          <td style="color:${r.drop_pct < -20 ? '#f85149' : '#d29922'}">${r.drop_pct || 0}%</td>
          <td>${r.close_above_count || 0}/8</td>
          <td style="font-size:.82rem">${scoreStr}</td>
        </tr>`;
      }
      h += '</tbody></table></div>';
    }

    app.innerHTML = h;

    // 也加载波浪信号
    try {
      const waveData = await api('/api/bb-ride/wave');
      const waveResults = waveData.results || [];
      const up = waveResults.filter(r => r.direction !== 'down');
      const down = waveResults.filter(r => r.direction === 'down');
      if (up.length || down.length) {
        let wh = '<div style="margin-top:24px"><div class="section-title">🌊 波浪信号 <span class="count u-muted">' + waveResults.length + ' 条</span></div>';
        if (up.length) {
          wh += '<div class="date-section-title" style="color:#3fb950;margin-top:12px">🟢 波浪上升 <span class="count u-muted">' + up.length + ' 条</span></div>';
          wh += '<div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>得分</th><th>价格</th><th>分类</th><th>建议</th></tr></thead><tbody>';
          for (const r of up) {
            const cl = 'https://www.okx.com/zh-hans/trade-swap/' + r.coin.toLowerCase() + '-usdt-swap';
            wh += '<tr><td><strong><a href="' + cl + '" target="_blank" style="color:#58a6ff">' + r.coin + ' ↗</a></strong></td><td class="u-fw6">' + r.score + '</td><td>' + fmtCryptoPrice(r.price) + '</td><td>[' + (r.classification||'') + ']</td><td class="u-meta-sm">' + (r.advice||'') + '</td></tr>';
          }
          wh += '</tbody></table></div>';
        }
        if (down.length) {
          wh += '<div class="date-section-title" style="color:#f85149;margin-top:16px">🔴 波浪下跌 <span class="count u-muted">' + down.length + ' 条</span></div>';
          wh += '<div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>得分</th><th>价格</th><th>分类</th><th>建议</th></tr></thead><tbody>';
          for (const r of down) {
            const cl = 'https://www.okx.com/zh-hans/trade-swap/' + r.coin.toLowerCase() + '-usdt-swap';
            wh += '<tr><td><strong><a href="' + cl + '" target="_blank" style="color:#58a6ff">' + r.coin + ' ↗</a></strong></td><td class="u-fw6">' + r.score + '</td><td>' + fmtCryptoPrice(r.price) + '</td><td>[' + (r.classification||'') + ']</td><td class="u-meta-sm">' + (r.advice||'') + '</td></tr>';
          }
          wh += '</tbody></table></div>';
        }
        wh += '</div>';
        app.innerHTML = h + wh;
      }
    } catch(e) {}

  } catch (e) {
    app.innerHTML = '<div class="empty">加载突破信号失败: ' + e.message + '</div>';
  }
}

async function _renderBbRideWave() {
  _bbRideMode = 'wave';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载波浪信号...</div>';
  try {
    const data = await api('/api/bb-ride/wave');
    const results = data.results || [];
    const scanTime = data.scan_time || '-';

    let h = '<div class="page-header"><div class="section-title">🌊 波浪向上攀升信号</div>' +
      '<div class="page-subtitle">扫描: ' + fmtFullTime(scanTime) + ' | OKX前30名 | EMA多头+高低点抬升+量价健康 | 打分0-100</div>' +
      '<div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">' +
      '<span class="u-meta">模式:</span>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'scanner\')">扫描信号</button>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'breakout\')">突破信号</button>' +
      '<button class="btn-sm btn-primary" onclick="_switchBbRideMode(\'wave\')">波浪信号</button>' +
      '<span style="margin-left:12px;font-size:.85rem;color:#8b949e">共 <strong style="color:#f0f6fc">' + results.length + '</strong> 个波浪形态</span></div></div>';

    if (!results.length) {
      h += '<div class="empty" style="margin-top:20px">暂无波浪信号</div>';
    } else {
      h += '<div class="table-wrap"><table class="data-table"><thead><tr>' +
        '<th>方向</th><th>币种</th><th>得分</th><th>价格</th><th>EMA12</th><th>偏离%</th><th>斜率</th><th>量比</th><th>状态</th></tr></thead><tbody>';
      for (const r of results) {
        const scoreCls = r.score >= 80 ? 'color:#3fb950' : r.score >= 60 ? 'color:#d29922' : 'color:#f85149';
        const linkUrl = 'https://www.okx.com/zh-hans/trade-swap/' + r.coin.toLowerCase() + '-usdt-swap';
        h += '<tr>' +
          '<td>' + (r.direction === 'down' ? '<span style=\"color:#f85149\">空</span>' : '<span style=\"color:#3fb950\">多</span>') + '</td>' +
          '<td><strong><a href=\"' + linkUrl + '" target="_blank" class="u-link">' + escHtml(r.coin) + ' ↗</a></strong></td>' +
          '<td style="' + scoreCls + ';font-weight:600">' + r.score + '</td>' +
          '<td>' + fmtCryptoPrice(r.price) + '</td>' +
          '<td>' + r.ema12.toFixed(4) + '</td>' +
          '<td>' + (r.dist_ema12 != null ? r.dist_ema12.toFixed(1) + '%' : '-') + '</td>' +
          '<td>' + (r.slope != null ? r.slope.toFixed(2) + '%' : '-') + '</td>' +
          '<td>' + (r.vol_ratio != null ? r.vol_ratio.toFixed(2) : '-') + '</td>' +
          '<td class="u-meta-sm">' + (r.score_a >= 40 ? '✅回踩 ' : '') + (r.score_b >= 25 ? '斜率佳 ' : '') + (r.score_c >= 15 ? '量健康' : '') + '</td>' +
          '</tr>';
      }
      h += '</tbody></table></div>';

      // 详细列表
      h += '<div style="margin-top:16px">';
      for (const r of results) {
        const scoreCls = r.score >= 80 ? 'color:#3fb950' : r.score >= 60 ? 'color:#d29922' : 'color:#f85149';
        h += '<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:12px 16px;margin-bottom:8px">' +
          '<div style="display:flex;justify-content:space-between;align-items:center">' +
          '<strong style="font-size:1.05rem">' + escHtml(r.coin) + ' <span style="color:' + scoreCls + '">' + r.score + '分</span></strong>' +
          '<span class="u-meta-sm">[' + (r.classification || '?') + '] ' + (r.advice || '') + '</span></div>' +
          '<div style="margin-top:6px;display:flex;gap:16px;font-size:.85rem;color:#8b949e">' +
          '<span>A(E12回踩): <strong>' + r.score_a + '/40</strong></span>' +
          '<span>B(斜率): <strong>' + r.score_b + '/30</strong></span>' +
          '<span>C(量): <strong>' + r.score_c + '/20</strong></span>' +
          '<span>D(空间): <strong>' + r.score_d + '/10</strong></span></div></div>';
      }
      h += '</div>';
    }

    app.innerHTML = h;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载波浪信号失败: ' + e.message + '</div>';
  }
}

async function _renderBbRidePushRetest() {
  _bbRideMode = 'pushretest';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载推土机突破信号...</div>';
  try {
    if (!window._pushRetestDate) {
      // 默认今天，生成过去7天日期
      const today = new Date();
      const dates = [];
      for (let i = 6; i >= 0; i--) {
        const d = new Date(today);
        d.setDate(d.getDate() - i);
        dates.push(d.getFullYear() + '-' + String(d.getMonth()+1).padStart(2,'0') + '-' + String(d.getDate()).padStart(2,'0'));
      }
      window._pushRetestDates = dates;
      window._pushRetestDate = dates[dates.length-1]; // 默认今天
    }

    const data = await api('/api/bb-ride/push-retest?date=' + window._pushRetestDate);
    const results = data.results || [];
    const scanTime = data.scan_time || '-';

    let h = '<div class="page-header"><div class="section-title">🚜 推土机突破→急速深回踩</div>' +
      '<div class="page-subtitle">扫描: ' + fmtFullTime(scanTime) + ' | OKX | 推土机突破日内高点 → 回踩布林下轨/EMA50</div>' +
      '<div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">' +
      '<span class="u-meta">模式:</span>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'scanner\')">扫描信号</button>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'breakout\')">突破信号</button>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'wave\')">波浪信号</button>' +
      '<button class="btn-sm btn-primary" onclick="_switchBbRideMode(\'pushretest\')">推土机</button>' +
      '<span style="margin-left:12px;font-size:.85rem;color:#8b949e">' + window._pushRetestDate + ' | ' + results.length + ' 个形态</span></div></div>';

    // 日期标签
    h += '<div class="date-tabs">';
    for (const d of window._pushRetestDates) {
      const cls = 'date-tab' + (d === window._pushRetestDate ? ' active' : '') + (results.length === 0 && d === window._pushRetestDate ? ' empty' : '');
      h += '<div class="' + cls + '" onclick="window._pushRetestDate=\'' + d + '\';_renderBbRidePushRetest()">' + d.slice(5) + '</div>';
    }
    h += '</div>';

    if (!results.length) {
      h += '<div class="empty" style="margin-top:20px">该日无突破信号</div>';
    } else {
      for (const r of results) {
        const linkUrl = 'https://www.okx.com/zh-hans/trade-swap/' + r.coin.toLowerCase() + '-usdt-swap';
        const scoreCls = r.score >= 70 ? 'color:#3fb950' : r.score >= 50 ? 'color:#d29922' : 'color:#f85149';
        h += '<div style="background:#161b22;border:1px solid #30363d;border-radius:8px;padding:10px 14px;margin:8px 0">' +
          '<div style="display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap">' +
          '<strong><a href="' + linkUrl + '" target="_blank" style="color:#58a6ff;text-decoration:none;font-size:1rem">' + r.coin + ' ↗</a></strong>' +
          '<span style="' + scoreCls + ';font-weight:600">' + r.score + '分</span></div>' +
          '<div style="display:flex;gap:12px;font-size:.85rem;margin-top:6px;color:#8b949e;flex-wrap:wrap">' +
          '<span>📈 突破: <strong style="color:#c9d1d9">' + (r.breakout_time || '?') + '</strong></span>' +
          '<span>📉 回踩: <strong style="color:#c9d1d9">' + (r.retest_time || '?') + '</strong></span>' +
          '<span>⏳ 间隔: ' + r.gap_bars + '根(' + r.gap_minutes + 'min)</span>' +
          '<span>触: ' + (r.retest_type || '?') + '</span></div></div>';
      }
    }

    app.innerHTML = h;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载推土机信号失败: ' + e.message + '</div>';
  }
}

window._switchBbRideMode = function(mode) {
  _bbRideMode = mode;
  renderBbRide();
};

async function _renderBbRideWithExchange(exchange) {
  _bbRideExchange = exchange;
  window._bbRideLinkExchange = exchange;
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载中...</div>';

  const apiUrl = exchange === 'okx' ? '/api/bb-ride/okx' : '/api/bb-ride';
  const [scanData, execData] = await Promise.all([
    api(apiUrl),
    api(exchange === 'okx' ? '/api/bb-ride-execution/okx' : '/api/bb-ride-execution').catch(() => null),
  ]);

  let results = exchange === 'okx' ? (scanData.signals || []) : (scanData.results || []);
  const scanTime = scanData.scan_time || '-';
  const volThreshold = exchange === 'okx' ? '1000万' : '2000万';
  const execState = execData || {};
  const activeOrders = Object.values(execState.orders || {});
  const positions = Object.values(execState.positions || {});
  const closed = execState.closed_positions || [];

  // OKX信号没有signal_time字段，用pattern_start_bj估算
  if (exchange === 'okx') {
    for (const r of results) {
      if (!r.signal_time && r.pattern_start_bj) {
        let startStr = r.pattern_start_bj.replace(' ', 'T');
        if (!startStr.endsWith('+08:00') && !startStr.endsWith('Z')) {
          startStr += '+08:00';
        }
        const start = new Date(startStr);
        if (!isNaN(start)) {
          const sig = new Date(start.getTime() + 225 * 60000);
          const bj = new Date(sig.getTime() + 8 * 3600000);
          const pad2 = n => String(n).padStart(2, '0');
          r.signal_time = bj.getUTCFullYear() + '-' + pad2(bj.getUTCMonth()+1) + '-' + pad2(bj.getUTCDate())
            + ' ' + pad2(bj.getUTCHours()) + ':' + pad2(bj.getUTCMinutes()) + ':' + pad2(bj.getUTCSeconds());
        }
      }
    }
  }

  // 按日期分组
  const byDate = {};
  let totalUp = 0, totalDown = 0;
  for (const r of results) {
    const dateKey = r.pattern_start_bj ? r.pattern_start_bj.substring(0, 10) : '';
    if (!dateKey) continue;
    if (!byDate[dateKey]) byDate[dateKey] = [];
    byDate[dateKey].push(r);
    if (r.direction === 'up') totalUp++;
    else if (r.direction === 'down') totalDown++;
  }

  // 日期列表
  const today = new Date();
  const pad = n => String(n).padStart(2, '0');
  const dateKeys = [];
  for (let i = 6; i >= 0; i--) {
    const d = new Date(today);
    d.setDate(d.getDate() - i);
    const k = d.getFullYear() + '-' + pad(d.getMonth()+1) + '-' + pad(d.getDate());
    const cnt = byDate[k] ? byDate[k].length : 0;
    const label = pad(d.getMonth()+1) + pad(d.getDate());
    dateKeys.push({key: k, label, count: cnt, isToday: i===0});
  }

  let selectedDate = [...dateKeys].reverse().find(d => byDate[d.key])?.key || dateKeys[dateKeys.length-1].key;

  function buildPage(dateKey) {
    const rows = byDate[dateKey] || [];
    const exchangeName = exchange === 'okx' ? 'OKX' : '币安';
    const linkUrl = exchange === 'okx'
      ? `https://www.okx.com/zh-hans/trade-swap/`
      : 'https://www.binance.com/zh-CN/futures/';

    let h = `<div class="page-header">\
      <div class="section-title">📊 底部启动扫描</div>\
      <div class="page-subtitle">扫描: ${fmtFullTime(scanTime)} | 15根K线≥12阳/阴+无暴涨 | 量≥${volThreshold}USDT</div>\
      <div style="display:flex;gap:8px;margin-top:12px;align-items:center;flex-wrap:wrap">\
        <span class="u-meta">模式:</span>\
        <button class="btn-sm btn-primary" onclick="_switchBbRideMode(\'scanner\')">扫描信号</button>\
        <button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'breakout\')">突破信号</button>' +
      '<button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'wave\')">波浪信号</button>' +\
        <span style="margin-left:12px;font-size:.85rem;color:#8b949e">交易所:</span>\
        <button class="btn-sm ${exchange==='binance'?'btn-primary':'btn-secondary'}" onclick="_switchBbRideExchange('binance')">币安</button>\
        <button class="btn-sm ${exchange==='okx'?'btn-primary':'btn-secondary'}" onclick="_switchBbRideExchange('okx')">OKX</button>\
        <span style="margin-left:12px;font-size:.85rem;color:#8b949e">\
          做多 <strong class="green">${totalUp}</strong> 条 /\
          做空 <strong class="red">${totalDown}</strong> 条\
        </span>\
      </div>\
    </div>`;

    // 日期标签
    h += '<div class="date-tabs">';
    for (const d of dateKeys) {
      const cls = 'date-tab' + (d.key === dateKey ? ' active' : '') + (d.count === 0 ? ' empty' : '');
      h += `<div class="${cls}" onclick="_renderBbRideDate('${d.key}')">${d.label}<span class="count">${d.count}</span></div>`;
    }
    h += '</div>';

    if (!rows.length) {
      h += '<div class="empty">该日无数据</div>';
    } else {
      const up = rows.filter(r => r.direction === 'up');
      const down = rows.filter(r => r.direction === 'down');
      const sortRows = arr => arr.sort((a,b) => ((b.signal_time||'') > (a.signal_time||'') ? 1 : -1));

      function renderTable(list, title, dirLabel, dirColor) {
        let s = `<div class="date-section-title" style="color:${dirColor}">${title} <span class="count u-muted">${list.length} 条</span></div>`;
        s += `<div class="table-wrap"><table class="data-table"><thead><tr>\
          <th>币种</th><th>当前价</th><th>匹配</th><th>涨跌幅%</th><th>最大单根%</th><th>24h量</th><th>评分</th><th>开始(北京)</th><th>发现时间</th>\
        </tr></thead><tbody>`;
        for (const r of list) {
          const volStr = r.volume_24h >= 1e9 ? `$${(r.volume_24h/1e9).toFixed(1)}B` : `$${(r.volume_24h/1e6).toFixed(0)}M`;
          const startStr = r.pattern_start_bj ? r.pattern_start_bj.substring(0, 16).replace('T', ' ') : '-';
          const signalStr = r.signal_time ? r.signal_time.substring(0, 16).replace('T', ' ') : '-';
          const matchStr = r.volume_ratio ? r.volume_ratio + "/15" : r.match_count ? r.match_count + "/15" : "-";
          const riseCls = r.direction === 'up' ? 'color:#3fb950' : 'color:#f85149';
          const scoreStr = '⭐'.repeat(r.score || 0) + '☆'.repeat(5 - (r.score || 0));

          let coinLink;
          if (exchange === 'okx') {
            coinLink = `https://www.okx.com/zh-hans/trade-swap/${escHtml(r.coin).toLowerCase()}-usdt-swap`;
          } else {
            coinLink = `https://www.binance.com/zh-CN/futures/${escHtml(r.coin)}USDT`;
          }

          s += `<tr>
            <td><strong><a href="${coinLink}" target="_blank" rel="noopener" class="u-link" title="在${exchangeName}打开">${escHtml(r.coin)} ↗</a></strong></td>
            <td>${fmtCryptoPrice(r.current_price)}</td>
            <td>${matchStr}</td>
            <td style="${riseCls}">${r.rise_pct ? (r.rise_pct > 0 ? '+' : '') + r.rise_pct.toFixed(2) + '%' : '-'}</td>
            <td>${r.pct_from_mid ? Number(r.pct_from_mid).toFixed(2) + '%' : r.max_extreme ? Number(r.max_extreme).toFixed(2) + '%' : '-'}</td>
            <td>${volStr}</td>
            <td style="font-size:.82rem">${scoreStr}</td>
            <td>${startStr}</td>
            <td class="u-meta-sm">${signalStr}</td>
          </tr>`;
        }
        s += '</tbody></table></div>';
        return s;
      }

      if (up.length) h += renderTable(sortRows(up), '🟢 做多', '#3fb950', '#3fb950');
      if (down.length) h += renderTable(sortRows(down), '🔴 做空', '#f85149', '#f85149');
    }

    // ⚡ 执行策略
    h += '<div style="margin-top:24px">';
    h += '<div class="section-title">⚡ 执行策略</div>';
    h += '<div class="section" style="margin-top:12px">';
    h += '<div class="section-title">📦 挂单列表 <span class="count">' + activeOrders.length + ' 笔</span></div>';
    h += '<div class="table-wrap">' + renderAiEntryOrders(activeOrders) + '</div></div>';
    if (positions.length) {
      h += '<div class="section" style="margin-top:12px">';
      h += '<div class="section-title">💼 持仓列表 <span class="count">' + positions.length + ' 笔</span></div>';
      h += '<div class="table-wrap">' + renderAiEntryPositions(positions) + '</div></div>';
    }
    h += '</div>';

    return h;
  }

  window._renderBbRideDate = function(dateKey) {
    selectedDate = dateKey;
    app.innerHTML = buildPage(dateKey);
  };

  app.innerHTML = buildPage(selectedDate);
}

window._switchBbRideExchange = function(exchange) {
  _bbRideExchange = exchange;
  _renderBbRideWithExchange(exchange);
};

window._switchBbRideExecExchange = function(exchange) {
  _bbRideExecExchange = exchange;
  window._bbRideExecPage = 1;
  _renderBbRideExecWithExchange(exchange);
};

let _bbRideExecExchange = 'binance';  // 'binance' | 'okx'

async function renderBbRideExec() {
  setActiveNav('bb-ride-exec');
  if (!window._bbRideExecPage) window._bbRideExecPage = 1;
  await _renderBbRideExecWithExchange(_bbRideExecExchange);
}

async function _renderBbRideExecWithExchange(exchange) {
  _bbRideExecExchange = exchange;
  window._bbRideLinkExchange = exchange;  // 用于render函数的币种链接
  if (!window._bbRideExecPage) window._bbRideExecPage = 1;
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载执行策略状态...</div>';
  try {
    const apiUrl = exchange === 'okx' ? '/api/bb-ride-execution/okx' : exchange === 'pushretest' ? '/api/bb-ride-execution/push-retest' : '/api/bb-ride-execution';
    const statsUrl = exchange === 'okx' ? '/api/bb-ride-execution/okx' : exchange === 'pushretest' ? '/api/bb-ride-execution/push-retest' : '/api/bb-ride-execution/stats';
    const [state, stats] = await Promise.all([
      api(apiUrl),
      api(statsUrl).catch(() => null),
    ]);
    const orders = state.orders || {};
    const positions = state.positions || {};
    const closed = state.closed_positions || [];
    const exchangeName = exchange === 'okx' ? 'OKX' : '币安';

    // 统一 stats
    const totalStats = state.total_stats || {};
    const totalTrades = stats?.total_closed || totalStats.trades || 0;
    const totalWins = stats?.total_wins || totalStats.wins || 0;
    const winRate = totalTrades > 0 ? (totalWins / totalTrades * 100).toFixed(0) : '-';
    const uniqueCoins = new Set(closed.map(c => c.coin)).size;
    const totalPnl = stats?.pnl_total || totalStats.pnl || 0;

    let html = `<div class="page-header">
      <div class="section-title">⚡ BB-Ride 执行策略</div>
      <div class="exchange-tabs" style="display:flex;gap:8px;margin-top:12px;align-items:center">
        <span class="u-meta">模式:</span>\n        <button class="btn-sm btn-primary" onclick="_switchBbRideMode(\'scanner\')">扫描信号</button>\n        <button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'breakout\')">突破信号</button>\n        <button class="btn-sm btn-secondary" onclick="_switchBbRideMode(\'wave\')">波浪信号</button>\n        <span style="margin-left:12px;font-size:.85rem;color:#8b949e">交易所:</span>
        <button class="btn-sm ${exchange==='binance'?'btn-primary':'btn-secondary'}" onclick="_switchBbRideExecExchange('binance')">币安</button>
        
        <span style="margin-left:12px;font-size:.82rem;color:#8b949e">${exchangeName}</span>
      </div>
    </div>`;

    html += `<div style="display:flex;gap:12px;flex-wrap:wrap;margin:0 0 16px">
      <div class="stat-card"><div class="value">${totalTrades}</div><div class="label">总单数</div></div>
      <div class="stat-card"><div class="value">${winRate}%</div><div class="label">胜率</div></div>
      <div class="stat-card"><div class="value">${uniqueCoins}</div><div class="label">币种数</div></div>
      <div class="stat-card"><div class="value" style="color:${totalPnl >= 0 ? '#3fb950' : '#f85149'}">${totalPnl >= 0 ? '+' : ''}${totalPnl.toFixed(2)}</div><div class="label">总盈利(USDT)</div></div>
    </div>`;

    const orderKeys = Object.keys(orders);
    const posKeys = Object.keys(positions);

    // ── 挂单 ──
    if (orderKeys.length) {
      html += `<div class="section-title" style="margin-top:16px;font-size:1rem">📋 挂单 (${orderKeys.length})</div>
        <div class="table-wrap"><table class="data-table"><thead><tr>
          <th>币种</th><th>方向</th><th>价格</th><th>数量</th><th>金额</th><th>已挂</th>
        </tr></thead><tbody>`;
      for (const key of orderKeys) {
        const o = orders[key];
        const dirIcon = o.direction === 'LONG' ? '🟢多' : '🔴空';
        const dirStyle = o.direction === 'LONG' ? 'color:#3fb950' : 'color:#f85149';
        html += `<tr>
          <td><strong><a href="${getCoinLink(o.coin)}" target="_blank" rel="noopener" class="u-link">${escHtml(o.coin)} ↗</a></strong></td>
          <td style="${dirStyle}">${dirIcon}</td>
          <td>${fmtPrice(o.price)}</td>
          <td>${o.quantity || '-'}</td>
          <td>$${((o.price || 0) * (o.quantity || 0)).toFixed(0)}</td>
          <td>${o.age_hours ? o.age_hours + 'h' : '-'}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;
    }

    // ── 持仓 ──
    if (posKeys.length) {
      html += `<div class="section-title" style="margin-top:16px;font-size:1rem">💼 持仓 (${posKeys.length})</div>
        <div class="table-wrap"><table class="data-table"><thead><tr>
          <th>币种</th><th>方向</th><th>入场价</th><th>数量</th><th>当前价</th><th>盈亏</th><th>持仓时间</th>
        </tr></thead><tbody>`;
      for (const key of posKeys) {
        const p = positions[key];
        const dirIcon = p.direction === 'LONG' ? '🟢多' : '🔴空';
        const dirStyle = p.direction === 'LONG' ? 'color:#3fb950' : 'color:#f85149';
        const pnl = p.unrealized_pnl ?? 0;
        const pnlPct = p.unrealized_pnl_pct ?? 0;
        const pnlCls = pnl >= 0 ? 'color:#3fb950' : 'color:#f85149';
        html += `<tr>
          <td><strong><a href="${getCoinLink(p.coin)}" target="_blank" rel="noopener" class="u-link">${escHtml(p.coin)} ↗</a></strong></td>
          <td style="${dirStyle}">${dirIcon}</td>
          <td>${fmtPrice(p.entry_price)}</td>
          <td>${p.quantity || '-'}</td>
          <td>${fmtPrice(p.current_price)}</td>
          <td style="${pnlCls}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)</td>
          <td>${p.filled_at_str || '-'}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;
    }

    // ── 已平仓（分页） ──
    if (closed.length) {
      const PAGE_SIZE = 20;
      const totalPages = Math.ceil(closed.length / PAGE_SIZE);
      const page = window._bbRideExecPage || 1;
      const startIdx = (page - 1) * PAGE_SIZE;
      const pageItems = closed.slice(-startIdx - PAGE_SIZE || undefined).slice(-PAGE_SIZE).reverse();
      // 或者更直观：倒序
      const reversed = [...closed].reverse();
      const paged = reversed.slice(startIdx, startIdx + PAGE_SIZE);

      html += `<div class="section-title" style="margin-top:16px;font-size:1rem">📜 已平仓 (${closed.length} 笔)</div>
        <div class="table-wrap"><table class="data-table"><thead><tr>
          <th>币种</th><th>方向</th><th>入场价</th><th>平仓价</th><th>数量</th><th>盈亏</th><th>开仓时间</th><th>平仓时间</th><th>持仓时长</th>
        </tr></thead><tbody>`;
      for (const c of paged) {
        const dirIcon = c.direction === 'LONG' ? '🟢多' : '🔴空';
        const pnl = c.pnl ?? 0;
        const pnlPct = c.pnl_pct ?? 0;
        const pnlCls = pnl >= 0 ? 'color:#3fb950' : 'color:#f85149';
        const duration = c.filled_at && c.close_time ? ((c.close_time - c.filled_at) / 3600).toFixed(1) + 'h' : '-';
        html += `<tr>
          <td><strong><a href="${getCoinLink(c.coin)}" target="_blank" rel="noopener" class="u-link">${escHtml(c.coin)} ↗</a></strong></td>
          <td>${dirIcon}</td>
          <td>${fmtPrice(c.entry_price)}</td>
          <td>${fmtPrice(c.close_price)}</td>
          <td>${c.quantity || '-'}</td>
          <td style="${pnlCls}">${pnl >= 0 ? '+' : ''}${pnl.toFixed(2)} (${pnlPct >= 0 ? '+' : ''}${pnlPct.toFixed(2)}%)</td>
          <td class="u-meta-sm">${c.filled_at_str || '-'}</td>
          <td class="u-meta-sm">${c.close_time_str || '-'}</td>
          <td>${duration}</td>
        </tr>`;
      }
      html += `</tbody></table></div>`;

      // 分页按钮
      html += `<div style="display:flex;justify-content:center;align-items:center;gap:8px;margin-top:12px">`;
      html += `<button class="date-tab" onclick="window._bbRideExecPage=1;renderBbRideExec()" ${page<=1?'disabled':''} style="${page<=1?'opacity:.4':''}">⏮ 首页</button>`;
      html += `<button class="date-tab" onclick="window._bbRideExecPage=${Math.max(1,page-1)};renderBbRideExec()" ${page<=1?'disabled':''} style="${page<=1?'opacity:.4':''}">◀ 上一页</button>`;
      html += `<span class="u-meta">第 ${page}/${totalPages} 页</span>`;
      html += `<button class="date-tab" onclick="window._bbRideExecPage=${Math.min(totalPages,page+1)};renderBbRideExec()" ${page>=totalPages?'disabled':''} style="${page>=totalPages?'opacity:.4':''}">下一页 ▶</button>`;
      html += `<button class="date-tab" onclick="window._bbRideExecPage=${totalPages};renderBbRideExec()" ${page>=totalPages?'disabled':''} style="${page>=totalPages?'opacity:.4':''}">尾页 ⏭</button>`;
      html += `</div>`;
    }

    if (!orderKeys.length && !posKeys.length && !closed.length) {
      html += '<div class="empty">暂无数据 — 等待 BB-Ride 信号...</div>';
    }

    app.innerHTML = html;
  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

// ── BB Ride 骑行执行面板（嵌入 SPA 版） ───────────────────

let _dexExecData = null;
let _dexScanData = null;
let _dexActiveTab = 'f';

async function renderBbRideExecDash() {
  setActiveNav('bb-ride-exec-dash');
  window._bbRideLinkExchange = 'binance';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载骑行面板...</div>';
  if (window._dexTimer) { clearInterval(window._dexTimer); window._dexTimer = null; }
  try {
    const [execData, scanData] = await Promise.all([
      api('/api/bb-ride-execution'),
      api('/api/bb-ride'),
    ]);
    _dexExecData = execData;
    _dexScanData = scanData;
    _dexActiveTab = 'f';

    app.innerHTML = _dexBuildHtml(execData, scanData);
    _dexFillData(execData, scanData);

    document.getElementById('dexTabs').addEventListener('click', function(e) {
      const btn = e.target.closest('.dash-tab');
      if (!btn) return;
      _dexActiveTab = btn.getAttribute('data-p');
      document.querySelectorAll('#dexTabs .dash-tab').forEach(function(x) { x.classList.remove('active'); });
      document.querySelectorAll('.dash-panel').forEach(function(x) { x.classList.remove('active'); });
      btn.classList.add('active');
      var panel = document.getElementById('dexP' + _dexActiveTab);
      if (panel) panel.classList.add('active');
    });

    window._dexTimer = setInterval(function() {
      if (!document.getElementById('dexTabs')) { clearInterval(window._dexTimer); return; }
      Promise.all([
        api('/api/bb-ride-execution').catch(function() { return null; }),
        api('/api/bb-ride').catch(function() { return null; }),
      ]).then(function(r) {
        if (!document.getElementById('dexTabs')) return;
        var ed = r[0], sd = r[1];
        if (ed) _dexExecData = ed;
        if (sd) _dexScanData = sd;
        _dexFillData(_dexExecData, _dexScanData);
      });
    }, 10000);

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

async function renderBbRideExecDashOkx() {
  setActiveNav('bb-ride-exec-dash-okx');
  window._bbRideLinkExchange = 'okx';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载骑行面板(OKX)...</div>';
  if (window._dexTimer) { clearInterval(window._dexTimer); window._dexTimer = null; }
  try {
    const [execData, scanData] = await Promise.all([
      api('/api/bb-ride-execution/okx'),
      api('/api/bb-ride/okx'),
    ]);
    _dexExecData = execData;
    _dexScanData = scanData;
    _dexActiveTab = 'f';

    app.innerHTML = _dexBuildHtml(execData, scanData);
    _dexFillData(execData, scanData);

    document.getElementById('dexTabs').addEventListener('click', function(e) {
      const btn = e.target.closest('.dash-tab');
      if (!btn) return;
      _dexActiveTab = btn.getAttribute('data-p');
      document.querySelectorAll('#dexTabs .dash-tab').forEach(function(x) { x.classList.remove('active'); });
      document.querySelectorAll('.dash-panel').forEach(function(x) { x.classList.remove('active'); });
      btn.classList.add('active');
      var panel = document.getElementById('dexP' + _dexActiveTab);
      if (panel) panel.classList.add('active');
    });

    window._dexTimer = setInterval(function() {
      if (!document.getElementById('dexTabs')) { clearInterval(window._dexTimer); return; }
      Promise.all([
        api('/api/bb-ride-execution/okx').catch(function() { return null; }),
        api('/api/bb-ride/okx').catch(function() { return null; }),
      ]).then(function(r) {
        if (!document.getElementById('dexTabs')) return;
        var ed = r[0], sd = r[1];
        if (ed) _dexExecData = ed;
        if (sd) _dexScanData = sd;
        _dexFillData(_dexExecData, _dexScanData);
      });
    }, 10000);

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function _dexBuildHtml(execData, scanData) {
  var orders = (execData && execData.orders) || {};
  var positions = (execData && execData.positions) || {};
  var closed = (execData && execData.closed_positions) || [];
  var ts = (execData && execData.total_stats) || {};
  var resultsAll = (scanData && scanData.results) || [];

  var todayStr = new Date().getFullYear() + '-' +
    String(new Date().getMonth()+1).padStart(2,'0') + '-' +
    String(new Date().getDate()).padStart(2,'0');
  var results = resultsAll.filter(function(r) { return (r.pattern_start_bj||'').substring(0,10) === todayStr; });

  var pendingCount = Object.keys(orders).length;
  var filledCount = Object.keys(positions).length;
  var closedCount = closed.length;
  var totalPnl = ts.pnl || 0;
  var totalTrades = ts.trades || closedCount;
  var totalWins = ts.wins || 0;
  var winRate = totalTrades > 0 ? totalWins / totalTrades * 100 : 0;
  var lossStreaks = Object.keys((execData && execData.loss_streaks) || {}).length;
  var longPosCount = Object.keys(positions).filter(function(k) { return k.startsWith('LONG'); }).length;
  var shortPosCount = Object.keys(positions).filter(function(k) { return k.startsWith('SHORT'); }).length;
  var longSignals = results.filter(function(r) { return r.direction === 'up'; });
  var shortSignals = results.filter(function(r) { return r.direction === 'down'; });

  var pnlCls = totalPnl >= 0 ? 'green' : 'red';
  var wrCls = winRate >= 50 ? 'green' : 'red';

  var h = '';

  // header
  h += '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:14px">' +
    '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">' +
    '<div class="section-title" style="margin:0;font-size:18px">🏍️ BB Ride · 布林骑行执行面板</div>' +
    '<span class="dash-badge">' + todayStr.replace('2026-','') + ' 持仓 <strong>' + filledCount + '</strong></span>' +
    '<span class="dash-dot"></span></div>' +
    '<span class="dash-badge" id="dexStBadge">🕐 ' + new Date().toLocaleTimeString() + ' 更新</span></div>';

  // cards
  h += '<div class="dash-cards">' +
    '<div class="dash-card"><div class="l">持仓（多/空）</div><div class="v" id="dexCardFilled">' + filledCount + '</div><div class="s">多' + longPosCount + ' / 空' + shortPosCount + '</div></div>' +
    '<div class="dash-card"><div class="l">挂单中</div><div class="v blue" id="dexCardPending">' + pendingCount + '</div></div>' +
    '<div class="dash-card"><div class="l">已平仓</div><div class="v" id="dexCardClosed">' + closedCount + '</div></div>' +
    '<div class="dash-card"><div class="l">总盈亏</div><div class="v ' + pnlCls + '" id="dexCardPnl">' + (totalPnl >= 0 ? '+' : '') + fmtNum(totalPnl) + '</div><div class="s">USDT</div></div>' +
    '<div class="dash-card"><div class="l">胜率</div><div class="v ' + wrCls + '" id="dexCardWr">' + fmtNum(winRate, 1) + '%</div><div class="s">' + totalWins + '胜 / ' + totalTrades + '单</div></div>' +
    '<div class="dash-card"><div class="l">连亏币种</div><div class="v' + (lossStreaks > 0 ? ' red' : '') + '" id="dexCardLs">' + lossStreaks + '</div><div class="s">⛔黑名单</div></div>' +
    '</div>';

  // tabs
  h += '<div class="dash-tabs" id="dexTabs">' +
    '<button class="dash-tab active" data-p="f">📊 持仓中 <span class="c green" id="dexTabFi">' + filledCount + '</span></button>' +
    '<button class="dash-tab" data-p="p">⏳ 挂单中 <span class="c gray" id="dexTabPe">' + pendingCount + '</span></button>' +
    '<button class="dash-tab" data-p="c">✔ 已平仓 <span class="c gray" id="dexTabCl">' + closedCount + '</span></button>' +
    '<button class="dash-tab" data-p="sl">📈 多头信号 <span class="c blue" id="dexTabSl">' + (longSignals.length > 10 ? '10+' : longSignals.length) + '</span></button>' +
    '<button class="dash-tab" data-p="sk">📉 空头信号 <span class="c red" id="dexTabSk">' + (shortSignals.length > 10 ? '10+' : shortSignals.length) + '</span></button>' +
    '</div>';

  // panels
  h += '<div class="dash-panel active" id="dexPf"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>入场价</th><th>数量</th><th>当前价</th><th>浮盈</th><th>止盈</th><th>止损</th><th>持仓时间</th></tr></thead><tbody id="dexTbF"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="dexPp"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>限价</th><th>数量</th><th>挂单时间</th><th>止盈</th><th>止损</th><th>过期剩余</th></tr></thead><tbody id="dexTbP"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="dexPc"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>入场→出场</th><th>盈亏</th><th>盈亏%</th><th>原因</th><th>时间</th></tr></thead><tbody id="dexTbC"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="dexPsl"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>当前价</th><th>匹配</th><th>涨跌幅%</th><th>最大单根%</th><th>24h量</th><th>⭐评分</th><th>开始(北京)</th><th>发现时间</th></tr></thead><tbody id="dexTbSl"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="dexPsk"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>当前价</th><th>匹配</th><th>涨跌幅%</th><th>最大单根%</th><th>24h量</th><th>⭐评分</th><th>开始(北京)</th><th>发现时间</th></tr></thead><tbody id="dexTbSk"></tbody></table></div></div>';

  return h;
}

function _dexFillData(execData, scanData) {
  var orders = (execData && execData.orders) || {};
  var positions = (execData && execData.positions) || {};
  var closed = (execData && execData.closed_positions) || [];
  var ts = (execData && execData.total_stats) || {};
  var resultsAll = (scanData && scanData.results) || [];

  var todayStr = new Date().getFullYear() + '-' +
    String(new Date().getMonth()+1).padStart(2,'0') + '-' +
    String(new Date().getDate()).padStart(2,'0');
  var results = resultsAll.filter(function(r) { return (r.pattern_start_bj||'').substring(0,10) === todayStr; });

  var pendingCount = Object.keys(orders).length;
  var filledCount = Object.keys(positions).length;
  var closedCount = closed.length;
  var totalPnl = ts.pnl || 0;
  var totalTrades = ts.trades || closedCount;
  var totalWins = ts.wins || 0;
  var winRate = totalTrades > 0 ? totalWins / totalTrades * 100 : 0;
  var lossStreaks = Object.keys((execData && execData.loss_streaks) || {}).length;
  var longPosCount = Object.keys(positions).filter(function(k) { return k.startsWith('LONG'); }).length;
  var shortPosCount = Object.keys(positions).filter(function(k) { return k.startsWith('SHORT'); }).length;
  var longSignals = results.filter(function(r) { return r.direction === 'up'; });
  var shortSignals = results.filter(function(r) { return r.direction === 'down'; });

  var now = Date.now() / 1000;

  // card values
  var el = document.getElementById('dexCardFilled'); if (el) el.textContent = filledCount;
  el = document.getElementById('dexCardPending'); if (el) el.textContent = pendingCount;
  el = document.getElementById('dexCardClosed'); if (el) el.textContent = closedCount;
  el = document.getElementById('dexCardPnl'); if (el) { el.textContent = (totalPnl >= 0 ? '+' : '') + fmtNum(totalPnl); el.className = 'v ' + (totalPnl >= 0 ? 'green' : 'red'); }
  el = document.getElementById('dexCardWr'); if (el) { el.textContent = fmtNum(winRate, 1) + '%'; el.className = 'v ' + (winRate >= 50 ? 'green' : 'red'); }
  el = document.getElementById('dexCardLs'); if (el) { el.textContent = lossStreaks; el.className = 'v' + (lossStreaks > 0 ? ' red' : ''); }

  // tab labels
  el = document.getElementById('dexTabFi'); if (el) el.textContent = filledCount;
  el = document.getElementById('dexTabPe'); if (el) el.textContent = pendingCount;
  el = document.getElementById('dexTabCl'); if (el) el.textContent = closedCount;
  el = document.getElementById('dexTabSl'); if (el) el.textContent = longSignals.length > 10 ? '10+' : longSignals.length;
  el = document.getElementById('dexTabSk'); if (el) el.textContent = shortSignals.length > 10 ? '10+' : shortSignals.length;

  // status
  el = document.getElementById('dexStBadge'); if (el) el.innerHTML = '🕐 ' + new Date().toLocaleTimeString() + ' 更新';

  // --- positions table ---
  var fHtml = '';
  var posKeys = Object.keys(positions);
  if (posKeys.length) {
    for (var i = 0; i < posKeys.length; i++) {
      var o = positions[posKeys[i]];
      var dir = o.direction === 'SHORT' ? '🔴 空' : '🟢 多';
      var curPx = o.current_price || o.entry_price;
      var upnl = o.unrealized_pnl;
      var upnlPct = o.unrealized_pnl_pct;
      var upnlStr = '-';
      if (upnl !== undefined && upnl !== null) {
        upnlStr = '<span style="color:' + (upnl >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (upnl >= 0 ? '+' : '') + fmtNum(upnl) + '</span>';
        if (upnlPct !== undefined && upnlPct !== null) {
          upnlStr += ' <span style="color:' + (upnlPct >= 0 ? 'var(--green)' : 'var(--red)') + '">(' + (upnlPct >= 0 ? '+' : '') + fmtNum(upnlPct, 1) + '%)</span>';
        }
      }
      var dur = o.filled_at ? now - o.filled_at : 0;
      fHtml += '<tr>' +
        '<td><strong><a href="' + getCoinLink(o.coin) + '" target="_blank" class="u-link">' + escHtml(o.coin) + ' ↗</a></strong></td>' +
        '<td>' + dir + '</td>' +
        '<td>' + fmtNum(o.entry_price, 6) + '</td>' +
        '<td>' + fmtNum(o.quantity, 2) + '</td>' +
        '<td>' + (typeof curPx === 'number' ? fmtNum(curPx, 6) : curPx) + '</td>' +
        '<td>' + upnlStr + '</td>' +
        '<td>' + fmtNum(o.tp_price, 6) + '</td>' +
        '<td>' + fmtNum(o.sl_price, 6) + '</td>' +
        '<td>' + fmtDuration(dur) + '</td>' +
        '</tr>';
    }
  } else { fHtml = '<tr><td colspan="9" class="dash-emp">暂无持仓</td></tr>'; }
  el = document.getElementById('dexTbF'); if (el) el.innerHTML = fHtml;

  // --- pending orders table ---
  var pHtml = '';
  var ordKeys = Object.keys(orders);
  if (ordKeys.length) {
    for (var i = 0; i < ordKeys.length; i++) {
      var o = orders[ordKeys[i]];
      var dir = o.direction === 'SHORT' ? '🔴 空' : '🟢 多';
      var placedAt = o.placed_at || 0;
      var elapsed = placedAt > 0 ? now - placedAt : 0;
      var expireRemain = Math.max(0, 300 - elapsed);
      var remainStr = expireRemain > 0 ? fmtDuration(expireRemain) : '⏰ 过期';
      pHtml += '<tr>' +
        '<td><strong><a href="' + getCoinLink(o.coin) + '" target="_blank" class="u-link">' + escHtml(o.coin) + ' ↗</a></strong></td>' +
        '<td>' + dir + '</td>' +
        '<td>' + fmtNum(o.price, 6) + '</td>' +
        '<td>' + fmtNum(o.quantity, 2) + '</td>' +
        '<td>' + fmtTime(placedAt * 1000) + '</td>' +
        '<td>' + fmtNum(o.tp_price, 6) + '</td>' +
        '<td>' + fmtNum(o.sl_price, 6) + '</td>' +
        '<td style="color:' + (expireRemain <= 60 ? 'var(--red)' : 'inherit') + '">' + remainStr + '</td>' +
        '</tr>';
    }
  } else { pHtml = '<tr><td colspan="8" class="dash-emp">暂无挂单</td></tr>'; }
  el = document.getElementById('dexTbP'); if (el) el.innerHTML = pHtml;

  // --- closed positions table ---
  var cHtml = '';
  if (closed.length) {
    var cList = closed.slice(-50).reverse();
    for (var i = 0; i < cList.length; i++) {
      var o = cList[i];
      var dir = o.direction === 'SHORT' ? '🔴 空' : '🟢 多';
      var pnl = o.pnl || 0;
      var pnlPct = o.pnl_pct || 0;
      cHtml += '<tr>' +
        '<td><strong><a href="' + getCoinLink(o.coin) + '" target="_blank" class="u-link">' + escHtml(o.coin) + ' ↗</a></strong></td>' +
        '<td>' + dir + '</td>' +
        '<td>' + fmtNum(o.entry_price, 4) + '→' + fmtNum(o.close_price, 4) + '</td>' +
        '<td style="color:' + (pnl >= 0 ? 'var(--green)' : 'var(--red)') + ';font-weight:500">' + (pnl >= 0 ? '+' : '') + fmtNum(pnl) + '</td>' +
        '<td style="color:' + (pnlPct >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (pnlPct >= 0 ? '+' : '') + fmtNum(pnlPct, 1) + '%</td>' +
        '<td>' + (pnl >= 0 ? '✅' : '❌') + '</td>' +
        '<td>' + (o.close_time_str || '-') + '</td>' +
        '</tr>';
    }
  } else { cHtml = '<tr><td colspan="7" class="dash-emp">暂无已平仓记录</td></tr>'; }
  el = document.getElementById('dexTbC'); if (el) el.innerHTML = cHtml;

  // --- long signals table ---
  var slHtml = '';
  var longSorted = longSignals.sort(function(a, b) {
    var ta = a.signal_time || '', tb = b.signal_time || '';
    return tb > ta ? 1 : (tb < ta ? -1 : 0);
  }).slice(0, 10);
  if (longSorted.length) {
    for (var i = 0; i < longSorted.length; i++) {
      var r = longSorted[i];
      var risePct = r.rise_pct || 0;
      var volStr = r.volume_24h >= 1e9 ? '$' + (r.volume_24h / 1e9).toFixed(1) + 'B' : '$' + (r.volume_24h / 1e6).toFixed(0) + 'M';
      var matchStr = (r.volume_ratio || r.match_count || '-') + '/15';
      var starStr = '⭐'.repeat(Math.min(r.score || 0, 5)) + '☆'.repeat(Math.max(0, 5 - (r.score || 0)));
      var startStr = (r.pattern_start_bj || '').substring(0, 16).replace('T', ' ') || '-';
      var signalStr = (r.signal_time || '').substring(0, 16).replace('T', ' ') || '-';
      slHtml += '<tr>' +
        '<td><strong><a href="' + getCoinLink(r.coin) + '" target="_blank" class="u-link">' + escHtml(r.coin) + ' ↗</a></strong></td>' +
        '<td>' + fmtCryptoPrice(r.current_price) + '</td>' +
        '<td>' + matchStr + '</td>' +
        '<td style="color:var(--green)">+' + fmtNum(risePct, 2) + '%</td>' +
        '<td>' + (r.max_extreme ? fmtNum(r.max_extreme, 2) + '%' : '-') + '</td>' +
        '<td>' + volStr + '</td>' +
        '<td style="font-size:.82rem">' + starStr + '</td>' +
        '<td>' + startStr + '</td>' +
        '<td style="color:#8b949e">' + signalStr + '</td>' +
        '</tr>';
    }
  } else { slHtml = '<tr><td colspan="9" class="dash-emp">暂无多头信号</td></tr>'; }
  el = document.getElementById('dexTbSl'); if (el) el.innerHTML = slHtml;

  // --- short signals table ---
  var skHtml = '';
  var shortSorted = shortSignals.sort(function(a, b) {
    var ta = a.signal_time || '', tb = b.signal_time || '';
    return tb > ta ? 1 : (tb < ta ? -1 : 0);
  }).slice(0, 10);
  if (shortSorted.length) {
    for (var i = 0; i < shortSorted.length; i++) {
      var r = shortSorted[i];
      var risePct = r.rise_pct || 0;
      var volStr = r.volume_24h >= 1e9 ? '$' + (r.volume_24h / 1e9).toFixed(1) + 'B' : '$' + (r.volume_24h / 1e6).toFixed(0) + 'M';
      var matchStr = (r.volume_ratio || r.match_count || '-') + '/15';
      var starStr = '⭐'.repeat(Math.min(r.score || 0, 5)) + '☆'.repeat(Math.max(0, 5 - (r.score || 0)));
      var startStr = (r.pattern_start_bj || '').substring(0, 16).replace('T', ' ') || '-';
      var signalStr = (r.signal_time || '').substring(0, 16).replace('T', ' ') || '-';
      skHtml += '<tr>' +
        '<td><strong><a href="' + getCoinLink(r.coin) + '" target="_blank" class="u-link">' + escHtml(r.coin) + ' ↗</a></strong></td>' +
        '<td>' + fmtCryptoPrice(r.current_price) + '</td>' +
        '<td>' + matchStr + '</td>' +
        '<td style="color:var(--red)">' + fmtNum(risePct, 2) + '%</td>' +
        '<td>' + (r.max_extreme ? fmtNum(r.max_extreme, 2) + '%' : '-') + '</td>' +
        '<td>' + volStr + '</td>' +
        '<td style="font-size:.82rem">' + starStr + '</td>' +
        '<td>' + startStr + '</td>' +
        '<td style="color:#8b949e">' + signalStr + '</td>' +
        '</tr>';
    }
  } else { skHtml = '<tr><td colspan="9" class="dash-emp">暂无空头信号</td></tr>'; }
  el = document.getElementById('dexTbSk'); if (el) el.innerHTML = skHtml;
}

// ── 推土机执行面板（嵌入 SPA 版） ────────────────────────

let _prdExecData = null;
let _prdScanData = null;
let _prdBalance = null;
let _prdActiveTab = 's';

async function renderBbRidePushRetestDash() {
  setActiveNav('push-retest');
  window._bbRideLinkExchange = 'okx';
  const app = qs('#app');
  app.innerHTML = '<div class="loading">加载推土机面板...</div>';
  if (window._prdTimer) { clearInterval(window._prdTimer); window._prdTimer = null; }
  try {
    const [scanData, execData, balanceData] = await Promise.all([
      api('/api/bb-ride/push-retest'),
      api('/api/bb-ride-execution/push-retest'),
      api('/api/push-retest/balance').catch(function() { return null; }),
    ]);
    _prdScanData = scanData;
    _prdExecData = execData;
    _prdBalance = balanceData;
    _prdActiveTab = 's';

    app.innerHTML = _prdBuildHtml(scanData, execData, balanceData);
    _prdFillData(scanData, execData, balanceData);

    document.getElementById('prdTabs').addEventListener('click', function(e) {
      var btn = e.target.closest('.dash-tab');
      if (!btn) return;
      _prdActiveTab = btn.getAttribute('data-p');
      document.querySelectorAll('#prdTabs .dash-tab').forEach(function(x) { x.classList.remove('active'); });
      document.querySelectorAll('.dash-panel').forEach(function(x) { x.classList.remove('active'); });
      btn.classList.add('active');
      var panel = document.getElementById('prdP' + _prdActiveTab);
      if (panel) panel.classList.add('active');
    });

    window._prdTimer = setInterval(function() {
      if (!document.getElementById('prdTabs')) { clearInterval(window._prdTimer); return; }
      Promise.all([
        api('/api/bb-ride/push-retest').catch(function() { return null; }),
        api('/api/bb-ride-execution/push-retest').catch(function() { return null; }),
      ]).then(function(r) {
        if (!document.getElementById('prdTabs')) return;
        var sd = r[0], ed = r[1];
        if (sd) _prdScanData = sd;
        if (ed) _prdExecData = ed;
        _prdFillData(_prdScanData, _prdExecData, _prdBalance);
      });
    }, 10000);

  } catch (e) {
    app.innerHTML = '<div class="empty">加载失败: ' + e.message + '</div>';
  }
}

function _prdBuildHtml(scanData, execData, balance) {
  var results = (scanData && scanData.results) || [];
  var scanTime = (scanData && scanData.scan_time) || '';
  var orders = (execData && execData.orders) || {};
  var positions = (execData && execData.positions) || {};
  var closed = (execData && execData.closed_positions) || [];
  var stats = (execData && execData.total_stats) || {};

  var pendingCount = Object.keys(orders).length;
  var filledCount = Object.keys(positions).length;
  var closedCount = closed.length;
  var totalPnl = (stats && stats.pnl) || 0;
  var balStr = balance ? fmtNum(balance.usdt_equity, 1) : '...';
  var upnl = (balance && balance.unrealized_pnl) || 0;

  var longs = results.filter(function(r) { return r.direction === 'long'; });
  var shorts = results.filter(function(r) { return r.direction !== 'long'; });

  var h = '';

  // header
  h += '<div style="display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:8px;padding-bottom:10px;border-bottom:1px solid var(--border);margin-bottom:14px">' +
    '<div style="display:flex;align-items:center;gap:10px;flex-wrap:wrap">' +
    '<div class="section-title" style="margin:0;font-size:18px">🧰 推土机策略 · OKX</div>' +
    '<span class="dash-badge">扫描 <strong>' + (scanData ? (scanData.total || results.length) : '?') + '</strong></span>' +
    '<span class="dash-dot"></span>' +
    '<span class="dash-badge" id="prdTBadge">🕐 ' + (scanTime || '') + '</span></div>' +
    '<span class="dash-badge" id="prdStBadge">🕐 ' + new Date().toLocaleTimeString() + ' OK</span></div>';

  // cards
  h += '<div class="dash-cards">' +
    '<div class="dash-card"><div class="l">候选币种</div><div class="v" id="prdCardCoins">' + results.length + '</div></div>' +
    '<div class="dash-card"><div class="l">持仓</div><div class="v green" id="prdCardFilled">' + filledCount + '</div></div>' +
    '<div class="dash-card"><div class="l">挂单</div><div class="v blue" id="prdCardPending">' + pendingCount + '</div></div>' +
    '<div class="dash-card"><div class="l">已平仓</div><div class="v" id="prdCardClosed">' + closedCount + '</div></div>' +
    '<div class="dash-card"><div class="l">总盈亏</div><div class="v ' + (totalPnl >= 0 ? 'green' : 'red') + '" id="prdCardPnl">' + (totalPnl >= 0 ? '+' : '') + fmtNum(totalPnl) + '</div><div class="s">USDT</div></div>' +
    '<div class="dash-card"><div class="l">合约资产</div><div class="v" id="prdCardBal">' + balStr + '</div><div class="s">USDT ' + (balance ? (balance.pos_count > 0 ? balance.pos_count + '仓' : '无持仓') : '') + ' | 浮盈:<span style="color:' + (upnl >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (upnl >= 0 ? '+' : '') + fmtNum(upnl) + '</span></div></div>' +
    '</div>';

  // tabs
  h += '<div class="dash-tabs" id="prdTabs">' +
    '<button class="dash-tab active" data-p="s">📈 多头候选 <span class="c blue" id="prdTabSc">' + longs.length + '</span></button>' +
    '<button class="dash-tab" data-p="k">📉 空头候选 <span class="c red" id="prdTabSk">' + shorts.length + '</span></button>' +
    '<button class="dash-tab" data-p="p">⏳ 挂单中 <span class="c gray" id="prdTabPe">' + pendingCount + '</span></button>' +
    '<button class="dash-tab" data-p="f">📊 持仓中 <span class="c green" id="prdTabFi">' + filledCount + '</span></button>' +
    '<button class="dash-tab" data-p="c">✔ 已平仓 <span class="c gray" id="prdTabCl">' + closedCount + '</span></button>' +
    '</div>';

  // panels
  h += '<div class="dash-panel active" id="prdPs"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>评分</th><th>突破时间</th><th>突破价</th><th>涨幅</th><th>当前价</th><th>回踩类型</th><th>状态</th></tr></thead><tbody id="prdTbS"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="prdPk"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>评分</th><th>跌破时间</th><th>跌破价</th><th>跌幅</th><th>当前价</th><th>反弹类型</th><th>状态</th></tr></thead><tbody id="prdTbK"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="prdPp"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>限价</th><th>数量</th><th>时间</th><th>止盈</th><th>止损</th></tr></thead><tbody id="prdTbP"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="prdPf"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>入场价</th><th>数量</th><th>当前价</th><th>浮盈</th><th>止盈</th><th>止损</th></tr></thead><tbody id="prdTbF"></tbody></table></div></div>';
  h += '<div class="dash-panel" id="prdPc"><div class="table-wrap"><table class="data-table"><thead><tr><th>币种</th><th>方向</th><th>入场→出场</th><th>盈亏</th><th>盈亏%</th><th>原因</th><th>时间</th></tr></thead><tbody id="prdTbC"></tbody></table></div></div>';

  return h;
}

function _prdFillData(scanData, execData, balance) {
  var results = (scanData && scanData.results) || [];
  var scanTime = (scanData && scanData.scan_time) || '';
  var orders = (execData && execData.orders) || {};
  var positions = (execData && execData.positions) || {};
  var closed = (execData && execData.closed_positions) || [];
  var stats = (execData && execData.total_stats) || {};

  var pendingCount = Object.keys(orders).length;
  var filledCount = Object.keys(positions).length;
  var closedCount = closed.length;
  var totalPnl = (stats && stats.pnl) || 0;
  var balStr = balance ? fmtNum(balance.usdt_equity, 1) : '...';
  var upnl = (balance && balance.unrealized_pnl) || 0;

  var longs = results.filter(function(r) { return r.direction === 'long'; });
  var shorts = results.filter(function(r) { return r.direction !== 'long'; });
  var now = Date.now() / 1000;

  // card values
  var el = document.getElementById('prdCardCoins'); if (el) el.textContent = results.length;
  el = document.getElementById('prdCardFilled'); if (el) el.textContent = filledCount;
  el = document.getElementById('prdCardPending'); if (el) el.textContent = pendingCount;
  el = document.getElementById('prdCardClosed'); if (el) el.textContent = closedCount;
  el = document.getElementById('prdCardPnl'); if (el) { el.textContent = (totalPnl >= 0 ? '+' : '') + fmtNum(totalPnl); el.className = 'v ' + (totalPnl >= 0 ? 'green' : 'red'); }
  el = document.getElementById('prdCardBal'); if (el) { el.textContent = balStr; }
  el = document.getElementById('prdTBadge'); if (el) el.textContent = '🕐 ' + (scanTime || '');

  // tab labels
  el = document.getElementById('prdTabSc'); if (el) el.textContent = longs.length;
  el = document.getElementById('prdTabSk'); if (el) el.textContent = shorts.length;
  el = document.getElementById('prdTabPe'); if (el) el.textContent = pendingCount;
  el = document.getElementById('prdTabFi'); if (el) el.textContent = filledCount;
  el = document.getElementById('prdTabCl'); if (el) el.textContent = closedCount;
  el = document.getElementById('prdStBadge'); if (el) el.innerHTML = '🕐 ' + new Date().toLocaleTimeString() + ' OK';

  // --- long candidates ---
  var sHtml = '';
  var longSorted = longs.sort(function(a, b) {
    var ta = a.break_time || '', tb = b.break_time || '';
    var bt = tb.localeCompare(ta);
    return bt || (b.score || 0) - (a.score || 0);
  });
  for (var i = 0; i < longSorted.length; i++) {
    var c = longSorted[i];
    var roc = c.price && c.break_price ? ((c.price - c.break_price) / c.break_price * 100) : 0;
    var statusTxt, statusCls;
    if (!c.retest_time || !c.retest_type || c.retest_type.indexOf('待') >= 0) {
      statusTxt = '⏳ 待回踩'; statusCls = 'color:var(--text-muted)';
    } else if (c.retest_type.indexOf('BB') >= 0 || c.retest_type.indexOf('布林') >= 0) {
      statusTxt = '✅ 布林回踩'; statusCls = 'color:var(--green)';
    } else if (c.retest_type.indexOf('EMA') >= 0) {
      statusTxt = '✅ EMA回踩'; statusCls = 'color:var(--green)';
    } else {
      statusTxt = '🔵 关注'; statusCls = 'color:var(--blue)';
    }
    var link = 'https://www.okx.com/zh-hans/trade-swap/' + c.coin.toLowerCase() + '-usdt-swap';
    sHtml += '<tr>' +
      '<td><strong><a href="' + link + '" target="_blank" class="u-link">' + escHtml(c.coin) + ' ↗</a></strong></td>' +
      '<td>' + (c.score || '-') + '</td>' +
      '<td>' + (c.break_time || '-') + '</td>' +
      '<td>' + fmtNum(c.break_price, 4) + '</td>' +
      '<td style="color:var(--green)">+' + (c.break_strength || 0).toFixed(2) + '%</td>' +
      '<td style="color:' + (roc >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmtNum(c.price, 4) + '</td>' +
      '<td>' + (c.retest_type || '-') + '</td>' +
      '<td style="' + statusCls + '">' + statusTxt + '</td>' +
      '</tr>';
  }
  el = document.getElementById('prdTbS'); if (el) el.innerHTML = sHtml || '<tr><td colspan="8" class="dash-emp">暂无</td></tr>';

  // --- short candidates ---
  var kHtml = '';
  for (var i = 0; i < shorts.length; i++) {
    var c = shorts[i];
    var roc = c.price && c.break_price ? ((c.price - c.break_price) / c.break_price * 100) : 0;
    var statusTxt, statusCls;
    if (!c.retest_time || !c.retest_type || c.retest_type.indexOf('待') >= 0) {
      statusTxt = '⏳ 待反弹'; statusCls = 'color:var(--text-muted)';
    } else if (c.retest_type.indexOf('BB') >= 0 || c.retest_type.indexOf('布林') >= 0) {
      statusTxt = '✅ 布林反弹'; statusCls = 'color:var(--green)';
    } else if (c.retest_type.indexOf('EMA') >= 0) {
      statusTxt = '✅ EMA反弹'; statusCls = 'color:var(--green)';
    } else {
      statusTxt = '🔵 关注'; statusCls = 'color:var(--blue)';
    }
    var link = 'https://www.okx.com/zh-hans/trade-swap/' + c.coin.toLowerCase() + '-usdt-swap';
    kHtml += '<tr>' +
      '<td><strong><a href="' + link + '" target="_blank" class="u-link">' + escHtml(c.coin) + ' ↗</a></strong></td>' +
      '<td>' + (c.score || '-') + '</td>' +
      '<td>' + (c.break_time || '-') + '</td>' +
      '<td>' + fmtNum(c.break_price, 4) + '</td>' +
      '<td style="color:var(--red)">-' + (c.break_strength || 0).toFixed(2) + '%</td>' +
      '<td style="color:' + (roc >= 0 ? 'var(--green)' : 'var(--red)') + '">' + fmtNum(c.price, 4) + '</td>' +
      '<td>' + (c.retest_type || '-') + '</td>' +
      '<td style="' + statusCls + '">' + statusTxt + '</td>' +
      '</tr>';
  }
  el = document.getElementById('prdTbK'); if (el) el.innerHTML = kHtml || '<tr><td colspan="8" class="dash-emp">暂无</td></tr>';

  // --- pending orders ---
  var pHtml = '';
  var ordKeys = Object.keys(orders);
  for (var i = 0; i < ordKeys.length; i++) {
    var o = orders[ordKeys[i]];
    var dir = (o.direction || 'long').toUpperCase() === 'SHORT' ? '🔴 空' : '🟢 多';
    pHtml += '<tr>' +
      '<td><strong><a href="https://www.okx.com/zh-hans/trade-swap/' + (o.coin||'').toLowerCase() + '-usdt-swap" target="_blank" class="u-link">' + escHtml(o.coin||'') + ' ↗</a></strong></td>' +
      '<td>' + dir + '</td>' +
      '<td>' + fmtNum(o.entry_price || o.limit_price, 4) + '</td>' +
      '<td>' + fmtNum(o.quantity, 4) + '</td>' +
      '<td>' + (o.entry_time ? fmtTime(o.entry_time * 1000) : '-') + '</td>' +
      '<td>' + fmtNum(o.tp_price, 4) + '</td>' +
      '<td>' + fmtNum(o.sl_price, 4) + '</td>' +
      '</tr>';
  }
  el = document.getElementById('prdTbP'); if (el) el.innerHTML = pHtml || '<tr><td colspan="7" class="dash-emp">暂无挂单</td></tr>';

  // --- positions ---
  var fHtml = '';
  var posKeys = Object.keys(positions);
  for (var i = 0; i < posKeys.length; i++) {
    var o = positions[posKeys[i]];
    var dir = (o.direction || 'long').toUpperCase() === 'SHORT' ? '🔴 空' : '🟢 多';
    var curPx = o.current_price || '-';
    var upnl = o.unrealized_pnl;
    var upnlPct = o.unrealized_pnl_pct;
    var upnlStr = '-';
    if (upnl !== undefined && upnl !== null) {
      upnlStr = '<span style="color:' + (upnl >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (upnl >= 0 ? '+' : '') + fmtNum(upnl) + '</span>';
      if (upnlPct !== undefined && upnlPct !== null) {
        upnlStr += ' <span style="color:' + (upnlPct >= 0 ? 'var(--green)' : 'var(--red)') + '">(' + (upnlPct >= 0 ? '+' : '') + fmtNum(upnlPct, 1) + '%)</span>';
      }
    }
    fHtml += '<tr>' +
      '<td><strong><a href="https://www.okx.com/zh-hans/trade-swap/' + (o.coin||'').toLowerCase() + '-usdt-swap" target="_blank" class="u-link">' + escHtml(o.coin||'') + ' ↗</a></strong></td>' +
      '<td>' + dir + '</td>' +
      '<td>' + fmtNum(o.entry_price, 4) + '</td>' +
      '<td>' + fmtNum(o.quantity, 4) + '</td>' +
      '<td>' + (typeof curPx === 'number' ? fmtNum(curPx, 4) : curPx) + '</td>' +
      '<td>' + upnlStr + '</td>' +
      '<td>' + fmtNum(o.tp_price, 4) + '</td>' +
      '<td>' + fmtNum(o.sl_price, 4) + '</td>' +
      '</tr>';
  }
  el = document.getElementById('prdTbF'); if (el) el.innerHTML = fHtml || '<tr><td colspan="8" class="dash-emp">暂无持仓</td></tr>';

  // --- closed (按平仓时间倒序) ---
  var cHtml = '';
  var closedSorted = closed.slice().sort(function(a, b) {
    var ta = a.close_time || 0, tb = b.close_time || 0;
    return tb - ta;
  });
  for (var i = 0; i < closedSorted.length; i++) {
    var o = closedSorted[i];
    var dir = (o.direction || 'long').toUpperCase() === 'SHORT' ? '🔴 空' : '🟢 多';
    var pnl = o.pnl || 0;
    var pnlPct = o.pnl_pct || 0;
    cHtml += '<tr>' +
      '<td><strong><a href="https://www.okx.com/zh-hans/trade-swap/' + (o.coin||'').toLowerCase() + '-usdt-swap" target="_blank" class="u-link">' + escHtml(o.coin||'') + ' ↗</a></strong></td>' +
      '<td>' + dir + '</td>' +
      '<td>' + fmtNum(o.entry_price, 2) + '→' + fmtNum(o.close_price, 2) + '</td>' +
      '<td style="color:' + (pnl >= 0 ? 'var(--green)' : 'var(--red)') + ';font-weight:500">' + (pnl >= 0 ? '+' : '') + fmtNum(pnl) + '</td>' +
      '<td style="color:' + (pnlPct >= 0 ? 'var(--green)' : 'var(--red)') + '">' + (pnlPct >= 0 ? '+' : '') + fmtNum(pnlPct, 1) + '%</td>' +
      '<td>' + (o.reason || '-') + '</td>' +
      '<td>' + (o.close_time_str || '-') + '</td>' +
      '</tr>';
  }
  el = document.getElementById('prdTbC'); if (el) el.innerHTML = cHtml || '<tr><td colspan="7" class="dash-emp">暂无已平仓</td></tr>';
}

function fmtPrice(v) {
  if (!v) return '-';
  v = parseFloat(v);
  if (v >= 1000) return v.toFixed(2);
  if (v >= 1) return v.toFixed(4);
  if (v >= 0.01) return v.toFixed(6);
  return v.toFixed(8);
}

// ── navigate & routing ──────────────────────────────────────

function navigate(path) {
  history.pushState({}, '', path);
  route();
}

function route() {
  const path = window.location.pathname;
  if (path === '/' || path === '') renderDashboard();
  else if (path === '/strategies') renderStrategies();
  else if (path === '/usdc') renderUsdc();
  else if (path === '/okx') renderOkx();
  else if (path === '/trend-score-page') renderTrendScorePage();
  else if (path === '/trend-convergence') renderTrendConv();
  else if (path === '/binance-ai') renderBinanceAi();
  else if (path === '/tradfi-ai') renderTradfiAi();
  else if (path === '/okx-ai') renderOkxAi();
  else if (path === '/okx-danger') renderOkxDanger();
  else if (path === '/binance-danger') renderBinanceDanger();
  else if (path === '/bb-ride') renderBbRide();
  else if (path === '/bb-ride-exec') renderBbRideExec();
  else if (path === '/bb-ride-exec-dashboard') renderBbRideExecDash();
  else if (path === '/okx-bb-ride-exec-dashboard') renderBbRideExecDashOkx();
  else if (path === '/push-retest-dashboard') renderBbRidePushRetestDash();
  else if (/^\/strategy\/(\d+)$/.test(path)) {
    const id = path.match(/^\/strategy\/(\d+)$/)[1];
    renderStrategyDetail(id);
  } else renderDashboard();
}

// ── init ───────────────────────────────────────────────────

window.addEventListener('popstate', route);
document.addEventListener('DOMContentLoaded', route);

// ── SPA 导航拦截（nav-link 点击不刷新页面） ──
document.addEventListener('click', function(e) {
  var link = e.target.closest('.nav-link');
  if (link && link.hostname === window.location.hostname) {
    e.preventDefault();
    navigate(link.getAttribute('href'));
  }
});

// ESC 关闭 modal（键盘无障碍）
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') {
    var ov = document.getElementById('modalOverlay');
    if (ov && ov.classList.contains('show')) closeModal();
  }
});
