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
const PALETTE = ['#3399FF', '#F9B115', '#2EB85C', '#5856D6', '#F9802B', '#5D6D78', '#1D8A99', '#E55353'];

// ------------------------------------------------------------------ metadata: domain, kolom, lineage
// Memakai RNG terpisah per nama objek (hash), sehingga urutan TABLES di atas tidak berubah.
const hashStr = s => { let h = 2166136261; for(let i = 0; i < s.length; i++){ h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return h >>> 0; };
const DOMAIN_OF = {cdr: 'usage', usage: 'usage', probe: 'usage', recharge: 'billing', billing: 'billing', revenue: 'billing', finance: 'billing',
  crm: 'customer', subscriber: 'customer', churn: 'customer', campaign: 'customer', features: 'customer', training: 'ml', predictions: 'ml',
  embeddings: 'ml', network: 'network', kpi: 'network', site: 'network', coverage: 'geo', geo: 'geo', geography: 'geo', region: 'geo',
  ref: 'reference', product: 'reference', device: 'device', monitoring: 'ops', audit: 'ops', shared: 'reporting', archive: 'archive',
  scratch: 'sandbox', tmp: 'sandbox', poc: 'sandbox', adhoc: 'sandbox', backup: 'sandbox', core: 'customer'};
function domainOf(t){ for(const tok of t.dataset.split('_')) if(DOMAIN_OF[tok]) return DOMAIN_OF[tok];
  for(const tok of t.table.split('_')) if(DOMAIN_OF[tok]) return DOMAIN_OF[tok]; return 'other'; }
const CATEGORY = {customer: 'Pelanggan & segmentasi', usage: 'Penggunaan & CDR', network: 'Jaringan & performa site', billing: 'Billing & revenue',
  device: 'Perangkat', geo: 'Geografi & cakupan', ml: 'Model & fitur ML', reference: 'Data referensi', ops: 'Operasional & audit',
  reporting: 'Pelaporan bersama', archive: 'Arsip', sandbox: 'Sandbox & sementara', other: 'Lainnya'};
const COLS = {
  customer: [['subscriber_id', 'STRING', 'ID pelanggan (hash, stabil lintas sistem)'], ['msisdn', 'STRING', 'Nomor pelanggan', 1],
    ['activation_date', 'DATE', 'Tanggal aktivasi kartu'], ['segment', 'STRING', 'Segmen nilai pelanggan (hasil model)'],
    ['region_code', 'STRING', 'Kode region layanan'], ['arpu_3m', 'NUMERIC', 'Rata-rata pendapatan per pelanggan 3 bulan (IDR)'],
    ['tenure_month', 'INT64', 'Lama berlangganan dalam bulan'], ['status', 'STRING', 'Status kartu: aktif, grace, churn'],
    ['nik_hash', 'STRING', 'Hash nomor identitas pelanggan', 1], ['churn_score', 'FLOAT64', 'Probabilitas churn 30 hari']],
  usage: [['event_ts', 'TIMESTAMP', 'Waktu kejadian (UTC)'], ['msisdn', 'STRING', 'Nomor pelanggan', 1], ['imsi', 'STRING', 'IMSI perangkat', 1],
    ['cell_id', 'STRING', 'ID sel yang melayani'], ['event_type', 'STRING', 'Jenis kejadian: voice, sms, data'],
    ['duration_sec', 'INT64', 'Durasi panggilan (detik)'], ['bytes_up', 'INT64', 'Volume unggah (byte)'], ['bytes_down', 'INT64', 'Volume unduh (byte)'],
    ['rat', 'STRING', 'Teknologi akses: 2G, 4G, 5G'], ['charge_idr', 'NUMERIC', 'Biaya yang dikenakan (IDR)']],
  network: [['kpi_date', 'DATE', 'Tanggal KPI'], ['site_id', 'STRING', 'ID site'], ['cell_id', 'STRING', 'ID sel'], ['vendor', 'STRING', 'Vendor perangkat radio'],
    ['technology', 'STRING', 'Teknologi: 2G, 4G, 5G'], ['availability_pct', 'FLOAT64', 'Ketersediaan sel (%)'], ['traffic_gb', 'FLOAT64', 'Trafik data (GB)'],
    ['call_drop_rate', 'FLOAT64', 'Rasio panggilan terputus (%)'], ['prb_util_pct', 'FLOAT64', 'Utilisasi PRB rata-rata (%)'], ['kabupaten_code', 'STRING', 'Kode kabupaten/kota']],
  billing: [['txn_id', 'STRING', 'ID transaksi'], ['subscriber_id', 'STRING', 'ID pelanggan (hash)'], ['txn_ts', 'TIMESTAMP', 'Waktu transaksi (UTC)'],
    ['amount_idr', 'NUMERIC', 'Nilai transaksi (IDR)'], ['product_code', 'STRING', 'Kode produk/paket'], ['channel', 'STRING', 'Kanal pembelian'],
    ['payment_method', 'STRING', 'Metode pembayaran'], ['msisdn', 'STRING', 'Nomor pelanggan', 1], ['is_refund', 'BOOL', 'Transaksi pengembalian dana']],
  device: [['tac', 'STRING', 'Type Allocation Code'], ['brand', 'STRING', 'Merek perangkat'], ['model', 'STRING', 'Model perangkat'],
    ['os', 'STRING', 'Sistem operasi'], ['is_5g', 'BOOL', 'Mendukung 5G'], ['launch_year', 'INT64', 'Tahun rilis']],
  geo: [['h3_index', 'STRING', 'Sel H3 resolusi 8'], ['lat', 'FLOAT64', 'Lintang'], ['lon', 'FLOAT64', 'Bujur'], ['kabupaten_code', 'STRING', 'Kode kabupaten/kota'],
    ['province_code', 'STRING', 'Kode provinsi'], ['population', 'INT64', 'Estimasi penduduk'], ['coverage_4g_pct', 'FLOAT64', 'Cakupan 4G (%)'], ['poi_count', 'INT64', 'Jumlah POI']],
  ml: [['subscriber_id', 'STRING', 'ID pelanggan (hash)'], ['feature_date', 'DATE', 'Tanggal fitur'], ['model_version', 'STRING', 'Versi model'],
    ['score', 'FLOAT64', 'Skor prediksi'], ['label', 'INT64', 'Label aktual (bila tersedia)'], ['feature_vector', 'ARRAY<FLOAT64>', 'Vektor fitur']],
  reference: [['code', 'STRING', 'Kode referensi'], ['name', 'STRING', 'Nama'], ['valid_from', 'DATE', 'Berlaku sejak'], ['valid_to', 'DATE', 'Berlaku hingga'], ['parent_code', 'STRING', 'Kode induk']],
  ops: [['job_name', 'STRING', 'Nama job/DAG'], ['run_id', 'STRING', 'ID eksekusi'], ['status', 'STRING', 'Status eksekusi'], ['started_at', 'TIMESTAMP', 'Waktu mulai'],
    ['duration_sec', 'INT64', 'Durasi (detik)'], ['rows_written', 'INT64', 'Baris ditulis'], ['user_email', 'STRING', 'Pengguna yang menjalankan', 1]],
};
COLS.reporting = COLS.customer; COLS.archive = COLS.usage; COLS.sandbox = COLS.usage; COLS.other = COLS.reference;
const COMMON = [['partition_date', 'DATE', 'Tanggal partisi'], ['load_ts', 'TIMESTAMP', 'Waktu data dimuat ke warehouse']];
function columnsFor(t){
  const r = rng(hashStr(t.full)), base = COLS[domainOf(t)] || COLS.other, n = Math.min(base.length, 4 + Math.floor(r() * base.length));
  const cols = base.slice(0, n).map(([name, type, desc, pii]) => ({name, type, desc: r() < .86 ? desc : '', pii: !!pii}));
  if(t.parts) cols.push(...COMMON.map(([name, type, desc]) => ({name, type, desc: r() < .95 ? desc : '', pii: false})));
  return cols;
}
const LAYER = p => p.startsWith('raw-') ? 0 : /^(dwh-core-prd|geo-|archive-)/.test(p) ? 1 : /^(mart-|ml-features)/.test(p) ? 2 : 3;
let _lineage = null;
function lineage(){
  if(_lineage) return _lineage;
  const objs = TABLES.filter(t => t.type !== 'EXTERNAL' || LAYER(t.project) === 0);
  const byLayer = [[], [], [], []];
  objs.forEach(t => { t.layer = LAYER(t.project); t.domain = domainOf(t); byLayer[t.layer].push(t); });
  const up = new Map(), down = new Map(), edges = [];
  const add = (src, dst, job) => { edges.push({src, dst, job}); (up.get(dst) || up.set(dst, []).get(dst)).push(src); (down.get(src) || down.set(src, []).get(src)).push(dst); };
  for(const t of objs){
    if(t.layer === 0) continue;
    const r = rng(hashStr('lin:' + t.full));
    const pool = byLayer[t.layer - 1].length ? byLayer[t.layer - 1] : byLayer[0];
    const same = pool.filter(x => x.domain === t.domain), cand = same.length >= 2 ? same : pool;
    const n = 1 + Math.floor(r() * (t.layer === 3 ? 2 : 4)), chosen = new Set();
    for(let k = 0; k < n * 3 && chosen.size < n; k++) chosen.add(cand[Math.floor(r() * cand.length)]);
    if(r() < .25 && t.layer >= 2){ const x = byLayer[t.layer - 2]; if(x.length) chosen.add(x[Math.floor(r() * x.length)]); }   // lompat lapisan
    const job = `dag_${t.project.split('-')[0]}_${t.dataset}`;
    chosen.forEach(s => add(s.full, t.full, job));
  }
  const byName = new Map(objs.map(t => [t.full, t]));
  _lineage = {edges, up, down, byName, jobs: new Set(edges.map(e => e.job))};
  return _lineage;
}

// ------------------------------------------------------------------ pemakaian tabel (90 hari)
let _usage = null;
function usage(){
  if(_usage) return _usage;
  const L = lineage(), out = new Map();
  for(const t of TABLES){
    const r = rng(hashStr('use:' + t.full)), layer = LAYER(t.project), downstream = (L.down.get(t.full) || []).length;
    const sandbox = /sandbox|-dev$/.test(t.project), archive = t.project.startsWith('archive');
    let user = layer === 3 && !sandbox ? r() * 1400 : layer === 2 ? r() * 520 : layer === 1 ? r() * 160 : r() * 35;
    if(sandbox) user = r() < .45 ? 0 : r() * 28;
    if(archive) user = r() < .8 ? 0 : r() * 4;
    if(t.ageDays >= 180) user = r() < .6 ? 0 : user * .1;
    if(/tmp|backup|scratch/.test(t.full) && r() < .55) user = 0;
    user = Math.round(user);
    const job = t.type === 'VIEW' ? 0 : downstream * 90;
    const reads = user + job, users = user ? 1 + Math.floor(r() * Math.min(40, 2 + user / 12)) : 0;
    const lastRead = reads ? new Date(SNAP - Math.floor(r() * (user ? Math.min(60, 900 / (user + 1)) : 1)) * DAY) : null;
    out.set(t.full, {reads, userReads: user, jobReads: job, users, lastRead,
      status: !reads ? 'unused' : reads < 10 ? 'rare' : 'active'});
  }
  _usage = out;
  return out;
}

// ------------------------------------------------------------------ pipeline (job/DAG dari lineage)
const SLOT_PRICE = 0.06;                          // USD per slot-hour (asumsi ilustrasi)
let _pipes = null;
function pipelines(){
  if(_pipes) return _pipes;
  const L = lineage(), U = usage(), byJob = new Map();
  for(const e of L.edges){ (byJob.get(e.job) || byJob.set(e.job, new Set()).get(e.job)).add(e.dst); }
  const list = [];
  for(const [name, dsts] of byJob){
    const r = rng(hashStr('dag:' + name)), tables = [...dsts].map(d => L.byName.get(d)).filter(Boolean);
    const project = tables[0].project, layer = LAYER(project), sandbox = /sandbox|-dev$/.test(project);
    const schedule = /bi-|ops-/.test(project) && r() < .6 ? 'hourly' : sandbox ? 'weekly' : r() < .12 ? 'weekly' : 'daily';
    const runsMonth = schedule === 'hourly' ? 720 : schedule === 'daily' ? 30 : 4;
    const bytes = tables.reduce((s, t) => s + t.bytes, 0);
    const slotPerRun = Math.max(.5, Math.pow(bytes / 1e12, .72) * (.6 + r() * 1.4) * 55 * (schedule === 'hourly' ? .05 : 1));
    let slotMonth = slotPerRun * runsMonth;
    const tier = /finance|core-prd|network-prd/.test(project) ? 1 : layer <= 1 ? 2 : sandbox ? 4 : 3;
    const status = sandbox && r() < .35 ? 'paused' : r() < .08 ? 'paused' : 'active';
    const success = r() < .15 ? .7 + r() * .2 : .95 + r() * .05;
    if(status === 'paused') slotMonth *= r() < .5 ? .15 : 0;          // dijeda tapi kadang masih dipicu manual
    const duration = Math.max(1, slotPerRun * 60 / (300 + r() * 1500) + r() * 8);                  // menit, 300-1800 slot paralel
    const growth = (r() - .3) * .06, spike = r() < .15 ? Math.floor(r() * 12) : -1;
    const monthly = Array.from({length: 12}, (_, i) => slotMonth * SLOT_PRICE * Math.pow(1 + growth, i - 11) * (i === spike ? 1.8 : 1) * (1 + (r() - .5) * .08));
    monthly[11] = slotMonth * SLOT_PRICE;
    const unusedOut = tables.filter(t => U.get(t.full).status === 'unused').length;
    list.push({name, project, owner: tables[0].owner, tables, schedule, runsMonth, tier, status, success, duration, slotMonth,
      cost: slotMonth * SLOT_PRICE, monthly, unusedOut});
  }
  list.sort((a, b) => b.cost - a.cost);
  _pipes = list;
  return list;
}

window.GOV = {rng, GiB, TiB, PRICE, SNAP, DAY, PROJECTS, TABLES, HIST_DAYS, CLEAN_DAY, history,
  hashStr, domainOf, CATEGORY, columnsFor, lineage, LAYER, usage, pipelines, SLOT_PRICE,
  $, esc, fmtBytes, fmtNum, usd, date, pct, delta, css, PALETTE};
})();
