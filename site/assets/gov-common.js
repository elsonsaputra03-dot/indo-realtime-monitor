/* Warehouse tiruan bersama untuk semua modul Data Governance (data sintetis, deterministik di semua browser). */
(() => {
'use strict';
// ------------------------------------------------------------------ generator deterministik
function rng(seed){ return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const R = rng(20260930);
const pick = a => a[Math.floor(R() * a.length)];
const shuffle = a => { a = a.slice(); for(let i = a.length - 1; i > 0; i--){ const j = Math.floor(R() * (i + 1)); [a[i], a[j]] = [a[j], a[i]]; } return a; };
const between = (a, b) => a + R() * (b - a);
const lognorm = (mu, sigma) => Math.exp(mu + sigma * Math.sqrt(-2 * Math.log(R() || 1e-9)) * Math.cos(2 * Math.PI * R()));
const GiB = 1024 ** 3, TiB = 1024 ** 4;
const PRICE = {active: 0.02, lt: 0.01};                 // USD per GiB per bulan (asumsi harga daftar)
const SNAP = new Date('2026-09-30T00:00:00Z'), DAY = 864e5;

const PROJECTS = [
  ['raw-cdr-prd', 'Data Engineering', 34], ['raw-network-prd', 'Network Analytics', 16], ['dwh-core-prd', 'Data Engineering', 14],
  ['raw-billing-prd', 'Data Engineering', 9], ['archive-cold-prd', 'Data Engineering', 8], ['mart-network-prd', 'Network Analytics', 5],
  ['ml-features-prd', 'Data Science', 4.5], ['raw-crm-prd', 'Data Engineering', 3.5], ['geo-analytics-prd', 'Network Analytics', 3],
  ['mart-marketing-prd', 'Marketing', 2.4], ['mart-finance-prd', 'Finance', 2], ['bi-reporting-prd', 'BI & Reporting', 1.6],
  ['sandbox-ds-dev', 'Data Science', 1.5], ['sandbox-analyst-dev', 'BI & Reporting', 1.2], ['dwh-core-dev', 'Data Engineering', 1],
  ['ops-monitoring-prd', 'Data Engineering', .6], ['partner-share-prd', 'BI & Reporting', .4], ['ml-sandbox-dev', 'Data Science', .3]];
const DS_POOL = {
  raw: ['cdr_voice', 'cdr_data', 'cdr_sms', 'usage_events', 'network_kpi_raw', 'probe_sessions', 'billing_events', 'recharge', 'crm_interactions', 'device_catalog'],
  dwh: ['core_subscriber', 'core_usage', 'core_revenue', 'core_network', 'ref_geography', 'ref_product', 'core_device'],
  mart: ['kpi_daily', 'kpi_weekly', 'campaign_response', 'churn_scores', 'site_performance', 'revenue_summary', 'region_rollup'],
  ml: ['features_subscriber', 'features_site', 'training_sets', 'predictions', 'embeddings'],
  sandbox: ['scratch', 'tmp_analysis', 'poc_models', 'adhoc_exports', 'backup_manual'],
  other: ['monitoring', 'audit_logs', 'shared_views', 'archive_2023', 'archive_2024', 'geo_poi', 'coverage_grid']};
const TB_WORDS = ['daily', 'hourly', 'monthly', 'snapshot', 'agg', 'detail', 'summary', 'fct', 'dim', 'stg', 'hist', 'v2', 'final', 'backup', 'tmp'];
function dsPool(p){ const k = p.split('-')[0]; return DS_POOL[k === 'raw' ? 'raw' : k === 'dwh' ? 'dwh' : k === 'mart' || k === 'bi' ? 'mart'
  : k === 'ml' ? 'ml' : k === 'sandbox' ? 'sandbox' : 'other']; }

const TABLES = [];
for(const [project, owner, weight] of PROJECTS){
  const nDs = Math.max(2, Math.round(between(3, 10) * Math.sqrt(weight / 4)));
  const pool = shuffle(dsPool(project));
  const cold = project.startsWith('archive'), sandbox = project.includes('sandbox') || project.endsWith('-dev');
  for(let d = 0; d < nDs; d++){
    const dataset = pool[d % pool.length] + (d >= pool.length ? '_' + (d + 1) : '');
    const nTb = Math.round(between(6, 55) * (sandbox ? .7 : 1));
    for(let t = 0; t < nTb; t++){
      const r = R();
      const type = r < .84 ? 'TABLE' : r < .94 ? 'VIEW' : r < .98 ? 'MATERIALIZED_VIEW' : 'EXTERNAL';
      const name = `${dataset.split('_')[0]}_${pick(TB_WORDS)}_${pick(TB_WORDS)}${R() < .3 ? '_' + (2023 + Math.floor(R() * 4)) : ''}`;
      const ageDays = cold ? between(200, 900) : sandbox ? Math.floor(lognorm(4.2, 1.1)) : Math.floor(lognorm(1.5, 1.6));
      const lastMod = new Date(SNAP - Math.min(ageDays, 1100) * DAY - between(0, DAY));
      let bytes = type === 'TABLE' || type === 'MATERIALIZED_VIEW' ? lognorm(22.4 + Math.log(weight), 2.1) : 0;
      bytes = Math.min(bytes, 1.8e15);
      const partitioned = type === 'TABLE' && R() < .62;
      const parts = partitioned ? Math.max(1, Math.round(between(20, 1400))) : 0;
      // porsi long-term: partisi lama tidak diubah >= 90 hari
      let ltShare = ageDays >= 90 ? 1 : partitioned ? Math.min(.92, Math.max(0, (parts - 90) / parts) * between(.6, 1)) : 0;
      if(type !== 'TABLE') ltShare = ageDays >= 90 ? 1 : 0;
      const firstPart = partitioned ? new Date(lastMod - parts * DAY) : null;
      TABLES.push({project, owner, dataset, table: name + (t > 0 && R() < .15 ? '_' + t : ''), type, bytes,
        active: bytes * (1 - ltShare), longterm: bytes * ltShare, rows: bytes ? Math.round(bytes / between(90, 650)) : 0,
        parts, firstPart, lastMod, ageDays: Math.floor((SNAP - lastMod) / DAY)});
    }
  }
}
// dedup nama tabel dalam dataset yang sama
const seen = new Set();
for(const t of TABLES){ let n = t.table, k = 1; while(seen.has(`${t.project}.${t.dataset}.${n}`)) n = `${t.table}_${++k}`; t.table = n; seen.add(`${t.project}.${t.dataset}.${n}`); }
const cost = t => t.active / GiB * PRICE.active + t.longterm / GiB * PRICE.lt;
TABLES.forEach(t => { t.cost = cost(t); t.full = `${t.project}.${t.dataset}.${t.table}`; });

// riwayat 90 hari: pertumbuhan harian + pembersihan sandbox pada hari ke-56
const HIST_DAYS = 90, CLEAN_DAY = 56;
function history(tables){
  const byProj = {};
  tables.forEach(t => { (byProj[t.project] ||= {active: 0, lt: 0, n: 0, rows: 0}); const p = byProj[t.project];
    p.active += t.active; p.lt += t.longterm; p.n += 1; p.rows += t.rows; });
  const hr = rng(4242), days = [];
  const projs = Object.keys(byProj);
  const whole = Object.values(byProj).reduce((s, b) => s + b.active + b.lt, 0);
  const sb = projs.filter(p => p.includes('sandbox') || p.endsWith('-dev'));
  const extra = Object.fromEntries(sb.map(p => [p, whole * .11 / sb.length]));          // backup & tmp yang dihapus saat pembersihan
  const growth = Object.fromEntries(projs.map(p => [p, p.startsWith('raw') ? .0042 : p.includes('sandbox') ? .0065 : p.startsWith('archive') ? .0008 : .0025]));
  for(let i = HIST_DAYS - 1; i >= 0; i--){
    const date = new Date(SNAP - i * DAY), row = {date, perProj: {}};
    let A = 0, L = 0, N = 0, W = 0;
    for(const p of projs){
      const b = byProj[p], back = Math.pow(1 + growth[p], -i);
      const noise = i ? .004 * Math.sin(i / 3 + p.length) + (hr() - .5) * .003 : 0;        // hari ini = snapshot persis
      let a = b.active * back * (1 + noise), l = b.lt * Math.pow(1 + growth[p] * .5, -i);
      let n = b.n * Math.pow(1 + growth[p] * .35, -i) * (1 + (i ? (hr() - .5) * .002 : 0)), w = b.rows * back;
      if(extra[p] && HIST_DAYS - 1 - i < CLEAN_DAY){ a += extra[p] * .35; l += extra[p] * .65; n *= 2.4; w *= 1.8; }   // sebelum pembersihan
      row.perProj[p] = {active: a, lt: l, cost: a / GiB * PRICE.active + l / GiB * PRICE.lt};
      A += a; L += l; N += n; W += w;
    }
    Object.assign(row, {active: A, lt: L, size: A + L, cost: A / GiB * PRICE.active + L / GiB * PRICE.lt, tables: Math.round(N), rows: W});
    days.push(row);
  }
  return days;
}

// ------------------------------------------------------------------ util tampilan
const $ = id => document.getElementById(id);
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[c]));
const fmtBytes = b => { const u = ['B', 'KB', 'MB', 'GB', 'TB', 'PB']; let i = 0; while(b >= 1024 && i < u.length - 1){ b /= 1024; i++; }
  return (b >= 100 ? b.toFixed(0) : b >= 10 ? b.toFixed(1) : b.toFixed(2)) + ' ' + u[i]; };
const fmtNum = n => n >= 1e12 ? (n / 1e12).toFixed(2) + 'T' : n >= 1e9 ? (n / 1e9).toFixed(2) + 'B' : n >= 1e6 ? (n / 1e6).toFixed(1) + 'M'
  : n >= 1e3 ? (n / 1e3).toFixed(1) + 'K' : String(Math.round(n));
const usd = v => '$' + (v >= 1e4 ? Math.round(v).toLocaleString('en-US') : v.toLocaleString('en-US', {minimumFractionDigits: 2, maximumFractionDigits: 2}));
const date = d => d.toLocaleDateString('id-ID', {day: 'numeric', month: 'short', year: 'numeric'});
const pct = (a, b) => b ? (a / b * 100) : 0;
const delta = (now, prev, fmt, invert) => { if(!prev) return ''; const d = (now - prev) / prev * 100; if(Math.abs(d) < .05) return '<span class="muted">tetap</span>';
  const up = d > 0; return `<span class="${up !== !!invert ? 'up' : 'down'}">${up ? '+' : ''}${d.toFixed(1)}%</span>`; };
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const PALETTE = ['#2E5E8C', '#E9B44C', '#3E8E5E', '#8F3F97', '#D9722E', '#5D6D78', '#1D8A99', '#B3261E'];

window.GOV = {rng, GiB, TiB, PRICE, SNAP, DAY, PROJECTS, TABLES, HIST_DAYS, CLEAN_DAY, history,
  $, esc, fmtBytes, fmtNum, usd, date, pct, delta, css, PALETTE};
})();
