/* Tampilan "Internet publik" di Network KPI Monitor: data NYATA dari Cloudflare Radar (CC BY-NC 4.0).
   Snapshot dibuat GitHub Actions (scripts/radar_snapshot.py) ke data/radar_id.json. */
(function(){
'use strict';
const SRC = 'data/radar_id.json';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, d = 0) => v == null || v === '' || isNaN(v) ? '–' : Number(v).toLocaleString('id-ID', {maximumFractionDigits: d, minimumFractionDigits: d});
const num = v => v == null || v === '' ? null : Number(v);
const tgl = s => s ? new Date(s).toLocaleString('id-ID', {day: 'numeric', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta'}) + ' WIB' : '–';
const tglD = s => s ? new Date(s).toLocaleDateString('id-ID', {day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Asia/Jakarta'}) : '–';
const dur = (a, b) => { if(!a || !b) return 'berlangsung / tidak dicatat'; const h = (new Date(b) - new Date(a)) / 36e5;
  return h < 1 ? Math.round(h * 60) + ' menit' : h < 48 ? fmt(h, 1) + ' jam' : fmt(h / 24, 1) + ' hari'; };
const CAUSE = {POWER_OUTAGE: 'Power outage', CABLE_CUT: 'Cable cut', WEATHER: 'Weather', GOVERNMENT_DIRECTED: 'Government directed',
  TECHNICAL_PROBLEM: 'Technical problem', MAINTENANCE: 'Maintenance', EARTHQUAKE: 'Earthquake', FIRE: 'Fire', CYBERATTACK: 'Cyberattack',
  MILITARY_ACTION: 'Military action', UNKNOWN: 'Unknown'};
const TYPE = {NATIONWIDE: 'Nationwide', REGIONAL: 'Regional', NETWORK: 'Operator network', PLATFORM: 'Platform'};
const COLORS = ['#B3261E', '#2E5E8C', '#C9901D', '#3E8E5E', '#8F3F97', '#1D8A99'];
let data = null, loading = null, charts = [], pickAsn = null, lmap = null, pickGeo = null, regOp = 'ID';
const DIRS = [['Southeast', 'Tenggara'], ['Southwest', 'Barat Daya'], ['Northeast', 'Timur Laut'], ['North', 'Utara'], ['South', 'Selatan'], ['East', 'Timur'],
  ['West', 'Barat'], ['Central', 'Tengah'], ['Highland', 'Pegunungan']];
function provName(n){
  n = String(n || '');
  const fixed = {'Jakarta': 'DKI Jakarta', 'Special Region of Yogyakarta': 'DI Yogyakarta', 'Yogyakarta': 'DI Yogyakarta', 'Aceh': 'Aceh', 'Riau Islands': 'Kepulauan Riau',
    'Bangka-Belitung Islands': 'Kepulauan Bangka Belitung', 'Bangka–Belitung Islands': 'Kepulauan Bangka Belitung', 'Bangka Belitung Islands': 'Kepulauan Bangka Belitung'};
  if(fixed[n]) return fixed[n];
  let x = n.replace(/\bJava\b/g, 'Jawa').replace(/\bSumatra\b/g, 'Sumatera').replace(/ Province$/, '');
  for(const [en, id] of DIRS) if(x.startsWith(en + ' ')) { x = x.slice(en.length + 1) + ' ' + id; break; }
  return x;
}
let cells = null, cellsLoading = null, cmap = null, cOp = '', cMetric = 'pop', cProv = '', cSort = ['total', -1], cQ = '';
function loadCells(){ return cells ? Promise.resolve(cells) : (cellsLoading ||= Promise.all([
  fetch('data/cells_id.json?v=' + (Date.now() / 36e5 | 0)).then(r => { if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }),
  fetch('data/kabkota_id.geojson').then(r => { if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })]).then(([c, g]) => (cells = {c, g}))); }
const median = a => { const x = a.filter(v => v != null).sort((p, q) => p - q); return x.length ? x[Math.floor(x.length / 2)] : null; };

const kpi = (v, k, sub = '') => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div>${sub ? `<div class="d" style="color:var(--muted)">${sub}</div>` : ''}</div>`;
const table = (cols, rows, empty) => rows.length ? `<div class="tw"><table><thead><tr>${cols.map(c => `<th class="${c.n ? 'r' : ''}">${esc(c.l)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c.n ? 'r' : ''}${c.w ? ' wrap' : ''}">${c.h ? c.h(r) : esc(r[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
  : `<p class="onote">${empty}</p>`;
const card = (title, sub, body) => `<section class="card" style="margin-bottom:14px"><h3>${title}${sub ? ` <span>${sub}</span>` : ''}</h3>${body}</section>`;
const asnName = (d, asn) => { const a = d.asns[String(asn)]; return a ? `${a.label} <span class="muted">AS${asn}</span>` : `AS${esc(asn)}`; };
const isOp = (d, asn) => !!d.asns[String(asn)];
const head = d => `<div class="ointro pub-real"><strong>Data nyata, publik.</strong> Sumber <a href="${esc(d.attribution.url)}" target="_blank" rel="noopener noreferrer">Cloudflare Radar</a>,
  lisensi <a href="${esc(d.attribution.license_url)}" target="_blank" rel="noopener noreferrer">${esc(d.attribution.license)}</a>. Diambil otomatis oleh GitHub Actions
  (snapshot ${tgl(d.generated_at)}). Ini pandangan dari luar jaringan operator (traffic yang melewati Cloudflare), bukan data OSS internal operator.</div>`;
const chart = (el, cfg) => { if(window.Chart && el) charts.push(new Chart(el, cfg)); };

function load(){ return data ? Promise.resolve(data) : (loading ||= fetch(SRC + '?v=' + (Date.now() / 36e5 | 0), {cache: 'no-store'})
  .then(r => { if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(d => (data = d))); }

// penurunan tidak normal: nilai jam ini < 60% median jam yang sama (hari-dalam-minggu yang sama) di minggu lain
function drops(s){
  if(!s || !s.t) return [];
  const byHow = {}, out = [];
  s.t.forEach((t, i) => { const d = new Date(t), k = d.getUTCDay() * 24 + d.getUTCHours(); (byHow[k] ||= []).push(i); });
  s.t.forEach((t, i) => { const v = s.v[i]; if(v == null) return;
    const d = new Date(t), others = byHow[d.getUTCDay() * 24 + d.getUTCHours()].filter(j => j !== i).map(j => s.v[j]).filter(x => x != null).sort((a, b) => a - b);
    if(others.length < 2) return; const med = others[Math.floor(others.length / 2)];
    if(med > 0.1 && v < 0.6 * med) out.push({t, v, med, ratio: v / med}); });
  return out;
}
// celah data: >= 6 jam berturut-turut hampir nol (mis. ASN tidak terlihat), dikeluarkan dari deteksi outage
function gaps(s){
  const out = new Set(); if(!s || !s.t) return out; let run = [];
  const flush = () => { if(run.length >= 6) run.forEach(t => out.add(t)); run = []; };
  s.t.forEach((t, i) => { const v = s.v[i]; if(v == null || v <= .02) run.push(t); else flush(); }); flush();
  return out;
}
const OPC = {'Telkomsel': '#D62839', 'Indosat': '#E0A100', 'XL Axiata': '#1F6FD1', 'Tri (IOH)': '#7B3FC4', 'Telkom Indonesia': '#E36414', 'Smartfren': '#C2185B'};
const opColor = l => OPC[l] || '#2E5E8C';
function spark(v, col){
  const x = v.filter(a => a != null); if(x.length < 2) return '<svg class="po-sp"></svg>';
  const W = 220, H = 44, n = v.length, p = v.map((a, i) => [i / (n - 1) * W, H - 3 - (a == null ? 0 : a) * (H - 6)]);
  const line = p.map((q, i) => (i ? 'L' : 'M') + q[0].toFixed(1) + ',' + q[1].toFixed(1)).join('');
  return `<svg class="po-sp" viewBox="0 0 ${W} ${H}" preserveAspectRatio="none" aria-hidden="true"><path d="${line}L${W},${H}L0,${H}Z" fill="${col}22"/><path d="${line}" fill="none" stroke="${col}" stroke-width="1.4"/></svg>`;
}
const hero = (d, title, sub, stats) => `<div class="pub-hero"><div class="ph-l"><span class="ph-live"><i></i>DATA NYATA · DIPERBARUI TIAP 3 JAM</span>
    <div class="ph-t">${title}</div><div class="ph-s">${sub}</div></div>
  <div class="ph-r">${stats.map(([v, k, c]) => `<div class="ph-k ${c || ''}"><b>${v}</b><span>${k}</span></div>`).join('')}</div></div>
  <div class="pub-src">Sumber <a href="${esc(d.attribution.url)}" target="_blank" rel="noopener noreferrer">Cloudflare Radar</a> ·
  <a href="${esc(d.attribution.license_url)}" target="_blank" rel="noopener noreferrer">${esc(d.attribution.license)}</a> · snapshot ${tgl(d.generated_at)} ·
  pandangan dari luar jaringan operator, bukan data OSS internal</div>`;
const avg = (a) => { const x = a.filter(v => v != null); return x.length ? x.reduce((s, v) => s + v, 0) / x.length : null; };

const VIEWS = {
  'pub-outage'(d, el){
    const outs = d.outages.slice().sort((a, b) => new Date(b.startDate) - new Date(a.startDate));
    const anos = d.anomalies.slice().sort((a, b) => new Date(b.startDate) - new Date(a.startDate));
    const opsHit = new Set([...outs.flatMap(o => o.asns.filter(a => isOp(d, a))), ...anos.filter(a => isOp(d, a.asn)).map(a => a.asn)]);
    const months = {}; const mk = s => s ? s.slice(0, 7) : null;
    outs.forEach(o => { const m = mk(o.startDate); if(m) (months[m] ||= {o: 0, a: 0}).o++; });
    anos.forEach(a => { const m = mk(a.startDate); if(m) (months[m] ||= {o: 0, a: 0}).a++; });
    const M = Object.keys(months).sort();
    const causes = {}; outs.forEach(o => { const c = CAUSE[o.cause] || o.cause || 'Tidak diketahui'; causes[c] = (causes[c] || 0) + 1; });
    el.innerHTML = hero(d, 'Internet outage &amp; anomaly', 'Outage yang dikonfirmasi tim Radar dan penurunan traffic yang terdeteksi otomatis di Indonesia, 12 bulan terakhir', [
        [fmt(outs.length), 'outage tercatat', outs.length ? 'bad' : 'good'], [fmt(anos.length), 'traffic anomaly'],
        [fmt(opsHit.size) + '/' + Object.keys(d.asns).length, 'operator utama terdampak'],
        [outs[0] ? tglD(outs[0].startDate) : '–', 'outage terakhir' + (outs[0] ? ' · ' + esc(CAUSE[outs[0].cause] || outs[0].cause || '') : '')]]) + `
    <div class="grid2" style="margin-bottom:14px">
      <section class="card"><h3>Kejadian per bulan</h3><div class="chart" style="height:220px"><canvas id="p-month"></canvas></div></section>
      <section class="card"><h3>Penyebab outage <span>menurut catatan Radar</span></h3>${table([{l: 'Penyebab', k: 'c'}, {l: 'Jumlah', k: 'n', n: 1}],
        Object.entries(causes).sort((a, b) => b[1] - a[1]).map(([c, n]) => ({c, n})), 'Belum ada outage tercatat.')}</section></div>
    ${card('Outage internet (outage)', 'dikurasi tim Radar, dengan penyebab dan tautan sumber', table([
      {l: 'Mulai', h: r => tgl(r.startDate)}, {l: 'Durasi', h: r => dur(r.startDate, r.endDate)},
      {l: 'Cakupan', h: r => esc(TYPE[r.type] || r.type || '') + (r.scope ? `<br><small class="muted">${esc(r.scope)}</small>` : ''), w: 1},
      {l: 'Operator', h: r => r.asns.length ? r.asns.map(a => asnName(d, a)).join('<br>') : '<span class="muted">tidak spesifik</span>', w: 1},
      {l: 'Penyebab', h: r => esc(CAUSE[r.cause] || r.cause || '–')},
      {l: 'Keterangan', h: r => esc(r.description || '') + (r.linkedUrl ? ` <a href="${esc(r.linkedUrl)}" target="_blank" rel="noopener noreferrer">sumber</a>` : ''), w: 1}],
      outs, 'Tidak ada outage tercatat untuk Indonesia dalam 12 bulan terakhir.'))}
    ${card('Traffic anomaly', 'penurunan traffic yang terdeteksi otomatis; belum tentu dikonfirmasi sebagai outage', table([
      {l: 'Mulai', h: r => tgl(r.startDate)}, {l: 'Selesai', h: r => r.endDate ? tgl(r.endDate) : '<span class="opill warn">berlangsung</span>'},
      {l: 'Jenis', h: r => r.type === 'ASN' || r.type === 'AS' ? 'Operator (ASN)' : r.type === 'LOCATION' ? 'Wilayah' : esc(r.type)},
      {l: 'Operator / wilayah', h: r => r.asn ? asnName(d, r.asn) + (isOp(d, r.asn) ? '' : `<br><small class="muted">${esc(r.asn_name || '')}</small>`) : esc(r.location || 'Indonesia'), w: 1},
      {l: 'Status', h: r => esc(r.status || '')}],
      anos.slice(0, 80), 'Tidak ada traffic anomaly tercatat.'))}`;
    chart(document.getElementById('p-month'), {type: 'bar', data: {labels: M, datasets: [
      {label: 'Outage', data: M.map(m => months[m].o), backgroundColor: '#B3261E', stack: 's'},
      {label: 'Traffic anomaly', data: M.map(m => months[m].a), backgroundColor: '#C9901D', stack: 's'}]},
      options: {maintainAspectRatio: false, plugins: {legend: {position: 'bottom'}}, scales: {x: {stacked: true}, y: {stacked: true, ticks: {precision: 0}}}}});
  },

  'pub-traffic'(d, el){
    const keys = Object.keys(d.asns).filter(k => d.traffic[k] && (d.traffic[k].http || d.traffic[k].netflows));
    pickAsn = keys.includes(pickAsn) ? pickAsn : keys[0];
    const ser = k => d.traffic[k].http || d.traffic[k].netflows;
    const hourOf = t => (new Date(t).getUTCHours() + 7) % 24;
    const rows = keys.map(k => { const s = ser(k), n = s.v.length, w = Math.min(168, Math.floor(n / 2));
      const last = avg(s.v.slice(n - w)), prev = avg(s.v.slice(n - 2 * w, n - w)), gp = gaps(s), dr = drops(s).filter(x => !gp.has(x.t));
      const byH = Array.from({length: 24}, () => []); s.t.forEach((t, i) => { if(s.v[i] != null && !gp.has(t)) byH[hourOf(t)].push(s.v[i]); });
      const hv = byH.map(a => avg(a) || 0), peak = hv.indexOf(Math.max(...hv)), low = hv.indexOf(Math.min(...hv));
      return {k, label: d.asns[k].label, name: d.asns[k].name, change: last != null && prev ? (last / prev - 1) * 100 : null, drops: dr.length, gaps: gp.size,
              worst: dr.sort((a, b) => a.ratio - b.ratio)[0], peak, low, spark: s.v.slice(-168), src: d.traffic[k].http ? 'HTTP' : 'NetFlows'}; });
    const totalDrops = rows.reduce((a, r) => a + r.drops, 0), best = rows.slice().sort((a, b) => (b.change || -99) - (a.change || -99))[0];
    el.innerHTML = hero(d, 'Traffic per operator', 'Pola traffic per jam 5 operator besar selama 28 hari, dilihat dari jaringan Cloudflare', [
        [keys.length, 'operator dipantau'], [totalDrops, 'jam turun tidak normal', totalDrops ? 'bad' : 'good'],
        [best ? (best.change > 0 ? '+' : '') + fmt(best.change, 1) + '%' : '–', best ? 'tumbuh tertinggi · ' + esc(best.label) : '']]) +
    `<div class="pub-ops">${rows.map(r => `<button type="button" class="pub-op" data-k="${r.k}" aria-pressed="${r.k === pickAsn}" style="--oc:${opColor(r.label)}">
        <div class="po-h"><b>${esc(r.label)}</b><span>AS${r.k}</span></div>
        <div class="po-v ${r.change == null ? '' : r.change >= 0 ? 'pos' : 'neg'}">${r.change == null ? '–' : (r.change >= 0 ? '▲ ' : '▼ ') + fmt(Math.abs(r.change), 1) + '%'}<small>7 hari vs sebelumnya</small></div>
        ${spark(r.spark, opColor(r.label))}
        <div class="po-f"><span class="${r.drops ? 'bad' : 'ok'}">${r.drops ? r.drops + ' jam turun' : 'normal'}</span>${r.gaps ? `<span class="gap">${r.gaps} jam tanpa data</span>` : ''}
          <span>puncak ${String(r.peak).padStart(2, '0')}.00</span></div></button>`).join('')}</div>
    <section class="card pub-main"><div class="pm-h"><h3 id="p-tt"></h3>
        <div class="pub-seg" role="group" aria-label="Rentang">${[7, 14, 28].map(n => `<button type="button" data-n="${n}" aria-pressed="${n === 28}">${n} hari</button>`).join('')}</div></div>
      <div class="chart" style="height:320px"><canvas id="p-traffic"></canvas></div>
      <div class="pub-leg"><span><i class="ln"></i>operator terpilih</span><span><i class="ln dash"></i>Indonesia (semua jaringan)</span><span><i class="dot"></i>jam turun tidak normal</span></div></section>
    <section class="card" style="margin-top:14px"><h3>Peta panas 28 hari × 24 jam <span id="p-hm-s"></span></h3><div id="p-hm"></div>
      <div class="pub-leg"><span>sepi</span><span class="hm-scale"></span><span>ramai</span><span><i class="sq bad"></i>turun tidak normal</span><span><i class="sq gap"></i>tanpa data</span></div></section>
    <details class="pub-method"><summary>Cara membaca &amp; metode</summary><p>Radar menormalisasi traffic tiap jaringan ke 0–1 (0 = jam tersepi, 1 = jam teramai dalam periode),
      jadi yang dibandingkan adalah <b>pola</b>, bukan volume antar-operator. <b>Turun tidak normal</b>: nilai satu jam di bawah 60% median jam yang sama pada hari yang sama di minggu-minggu lain.
      <b>Tanpa data</b>: ≥ 6 jam berturut-turut bernilai hampir nol, kemungkinan celah pengukuran, tidak dihitung sebagai outage. Waktu dalam WIB.</p></details>`;
    let range = 28;
    const draw = () => {
      charts.splice(0).forEach(c => c.destroy());
      const s = ser(pickAsn), id = d.traffic.ID && ser('ID'), r = rows.find(x => x.k === pickAsn), col = opColor(r.label);
      const gp = gaps(s), n0 = Math.max(0, s.t.length - range * 24), T = s.t.slice(n0), V = s.v.slice(n0).map((v, i) => gp.has(T[i]) ? null : v), dr = new Set(drops(s).filter(x => !gp.has(x.t)).map(x => x.t));
      document.getElementById('p-tt').innerHTML = `${esc(r.label)} <span>AS${r.k} · ${esc(r.name)} · sumber ${r.src}</span>`;
      const lab = T.map(t => new Date(t).toLocaleString('id-ID', {weekday: 'short', day: '2-digit', month: 'short', hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Jakarta'}));
      const cv = document.getElementById('p-traffic'), g = cv.getContext('2d').createLinearGradient(0, 0, 0, 320);
      g.addColorStop(0, col + '55'); g.addColorStop(1, col + '05');
      chart(cv, {type: 'line', data: {labels: lab, datasets: [
        {label: r.label, data: V, borderColor: col, backgroundColor: g, fill: true, borderWidth: 1.6, tension: .25,
         pointRadius: T.map(t => dr.has(t) ? 4 : 0), pointBackgroundColor: '#E5383B', pointBorderColor: '#fff', pointBorderWidth: 1.5},
        ...(id ? [{label: 'Indonesia', data: T.map(t => { const j = id.t.indexOf(t); return j < 0 ? null : id.v[j]; }), borderColor: '#8FA1AC', borderDash: [4, 4], borderWidth: 1, pointRadius: 0, tension: .25}] : [])]},
        options: {maintainAspectRatio: false, interaction: {mode: 'index', intersect: false},
          plugins: {legend: {display: false}, tooltip: {backgroundColor: '#15212A', padding: 10, callbacks: {label: c => ` ${c.dataset.label}: ${fmt(c.parsed.y * 100)}% dari puncak`}}},
          scales: {x: {grid: {display: false}, ticks: {maxTicksLimit: range === 7 ? 7 : 10, autoSkip: true, callback: function(v){ return this.getLabelForValue(v).split(',')[0]; }}},
                   y: {min: 0, max: 1, grid: {color: '#EDF1F3'}, ticks: {callback: v => v * 100 + '%'}}}}});
      // peta panas: baris = hari, kolom = jam WIB
      const days = {}; s.t.forEach((t, i) => { const w = new Date(new Date(t).getTime() + 7 * 36e5), key = w.toISOString().slice(0, 10);
        (days[key] ||= Array(24).fill(undefined))[w.getUTCHours()] = {v: s.v[i], t}; });
      const shade = v => { const x = Math.max(0, Math.min(1, v)); return `hsl(${210 - x * 20},${45 + x * 30}%,${96 - x * 62}%)`; };
      document.getElementById('p-hm-s').textContent = `${r.label} · nilai 0–100% dari puncak`;
      document.getElementById('p-hm').innerHTML = `<div class="hm"><div class="hm-r hm-hd"><span></span>${Array.from({length: 24}, (_, h) => `<span>${h % 3 ? '' : String(h).padStart(2, '0')}</span>`).join('')}</div>` +
        Object.keys(days).sort().map(k => `<div class="hm-r"><span>${new Date(k + 'T00:00:00Z').toLocaleDateString('id-ID', {weekday: 'short', day: '2-digit', month: 'short', timeZone: 'UTC'})}</span>${days[k].map(c =>
          !c || c.v == null ? '<i class="na"></i>' : `<i class="${gp.has(c.t) ? 'gap' : dr.has(c.t) ? 'bad' : ''}" style="background:${gp.has(c.t) ? '' : shade(c.v)}" title="${tgl(c.t)}: ${fmt(c.v * 100)}%"></i>`).join('')}</div>`).join('') + '</div>';
      el.querySelectorAll('.pub-op').forEach(b => b.setAttribute('aria-pressed', b.dataset.k === pickAsn));
    };
    el.querySelectorAll('.pub-op').forEach(b => b.onclick = () => { pickAsn = b.dataset.k; draw(); });
    el.querySelectorAll('.pub-seg button').forEach(b => b.onclick = () => { range = +b.dataset.n;
      el.querySelectorAll('.pub-seg button').forEach(x => x.setAttribute('aria-pressed', x === b)); draw(); });
    if(pickAsn) draw();
  },

  'pub-region'(d, el){
    const geo = Object.fromEntries((d.geo || []).map(g => [String(g.geoId), g]));
    const share = k => { const s = ((d.adm1 || {})[k] || {}).summary_0 || {}; return Object.fromEntries(Object.entries(s).filter(([g]) => geo[g]).map(([g, v]) => [g, num(v)])); };
    const nat = share('ID'), ops = Object.keys(d.asns).filter(k => (d.adm1 || {})[k]), opShare = Object.fromEntries(ops.map(k => [k, share(k)]));
    const ts = (d.adm1_ts || {}).netflows || (d.adm1_ts || {}).http, tsSrc = (d.adm1_ts || {}).netflows ? 'NetFlows' : 'HTTP';
    const trend = g => { const v = ts && ts.s[g]; if(!v || v.length < 10) return null;
      const last = avg(v.slice(-7)), prev = avg(v.slice(0, -7)), med = median(v.slice(0, -1)), lo = Math.min(...v.filter(x => x != null));
      const iMin = v.indexOf(lo); return {change: prev ? (last / prev - 1) * 100 : null, minRatio: med ? lo / med : null, minT: ts.t[iMin]}; };
    const rows = Object.keys(geo).filter(g => nat[g] != null || ops.some(k => opShare[k][g] != null)).map(g => ({g, name: provName(geo[g].name), en: geo[g].name, nat: nat[g], tr: trend(g)}))
      .sort((a, b) => (b.nat || 0) - (a.nat || 0));
    if(!rows.length){ el.innerHTML = head(d) + '<div class="ointro">Data level provinsi belum tersedia di snapshot ini; akan terisi pada pengambilan berikutnya.</div>'; return; }
    pickGeo = rows.some(r => r.g === pickGeo) ? pickGeo : rows[0].g;
    const cell = (k, g) => { const v = opShare[k][g], n = nat[g]; if(v == null) return '–'; const idx = n ? v / n : null;
      return `<span title="indeks ${idx == null ? '–' : fmt(idx, 2)} terhadap porsi nasional" class="${idx > 1.3 ? 'pub-hi' : idx < .7 ? 'pub-lo' : ''}">${fmt(v, 1)}%</span>`; };
    const downN = rows.filter(r => r.tr && r.tr.change != null && r.tr.change <= -10).length;
    el.innerHTML = hero(d, 'Traffic per province', 'Porsi traffic internet tiap provinsi dan sebaran traffic tiap operator, 7 hari terakhir', [
        [rows.length, 'provinsi'], [downN, 'provinsi turun ≥ 10%', downN ? 'bad' : 'good'],
        [esc(rows[0].name), fmt(rows[0].nat, 1) + '% traffic nasional']]) + `<div class="ointro">Radar membagi traffic Indonesia per <b>provinsi</b> (ADM1, tersedia sejak September 2025). Angka = porsi traffic 7 hari terakhir.
      Kolom operator = porsi traffic operator itu yang berasal dari provinsi tersebut; <span class="pub-hi">hijau</span> berarti operator relatif lebih kuat di sana dibanding rata-rata nasional,
      <span class="pub-lo">merah</span> relatif lebih lemah. Level lebih kecil dari provinsi (kota, site, sel) tidak tersedia di data publik.</div>
    <div class="grid2" style="margin-bottom:14px">
      <section class="card"><h3>Peta porsi traffic <span>ukuran lingkaran = porsi</span></h3>
        <div class="pub-chips" role="group" aria-label="Pilih jaringan">${['ID', ...ops].map(k => `<button type="button" class="pub-chip" data-op="${k}" aria-pressed="${k === regOp}">${k === 'ID' ? 'Indonesia' : esc(d.asns[k].label)}</button>`).join('')}</div>
        <div id="p-map" style="height:360px;border-radius:8px;border:1px solid var(--rule)"></div>
        <p class="onote">Titik = pusat provinsi dari Radar, bukan lokasi BTS. Lingkaran merah = porsi provinsi turun ≥ 10% dalam 7 hari terakhir.</p></section>
      <section class="card"><h3 id="p-geo-t">Tren harian</h3><div class="chart" style="height:300px"><canvas id="p-geo"></canvas></div>
        <p class="onote">Porsi harian provinsi terhadap traffic Indonesia, 28 hari (${tsSrc}). Penurunan tajam satu hari biasanya tanda outage regional (listrik, kabel, cuaca).</p></section></div>
    ${card('Porsi traffic per province', `${rows.length} provinsi · klik baris untuk tren`, `<div class="tw"><table class="pub-reg"><thead><tr><th>Provinsi</th><th class="r">Porsi nasional</th>
      ${ops.map(k => `<th class="r">${esc(d.asns[k].label)}</th>`).join('')}<th class="r">Perubahan 7 hari</th><th>Hari terendah</th></tr></thead><tbody>
      ${rows.map(r => `<tr data-g="${r.g}" tabindex="0" aria-selected="${r.g === pickGeo}"><td title="${esc(r.en)}"><b>${esc(r.name)}</b></td><td class="r">${fmt(r.nat, 2)}%</td>
        ${ops.map(k => `<td class="r">${cell(k, r.g)}</td>`).join('')}
        <td class="r">${!r.tr || r.tr.change == null ? '–' : `<span class="${r.tr.change <= -10 ? 'up' : ''}">${r.tr.change > 0 ? '+' : ''}${fmt(r.tr.change, 1)}%</span>`}</td>
        <td>${r.tr && r.tr.minRatio != null ? `${tglD(r.tr.minT)} <small class="${r.tr.minRatio < .7 ? 'up' : 'muted'}">${fmt(r.tr.minRatio * 100)}% dari median</small>` : '–'}</td></tr>`).join('')}
      </tbody></table></div>`)}`;
    const drawTrend = () => {
      charts.splice(0).forEach(c => c.destroy());
      const r = rows.find(x => x.g === pickGeo); document.getElementById('p-geo-t').innerHTML = `Tren harian · ${esc(r.name)}`;
      el.querySelectorAll('tr[data-g]').forEach(tr => tr.setAttribute('aria-selected', tr.dataset.g === pickGeo));
      const H = (d.adm1_ts || {}).http, N = (d.adm1_ts || {}).netflows, lab = (N || H).t.map(t => tglD(t));
      chart(document.getElementById('p-geo'), {type: 'line', data: {labels: lab, datasets: [
        ...(N && N.s[pickGeo] ? [{label: 'NetFlows', data: N.s[pickGeo], borderColor: '#2E5E8C', pointRadius: 2, tension: .2}] : []),
        ...(H && H.s[pickGeo] ? [{label: 'HTTP', data: H.s[pickGeo], borderColor: '#C9901D', pointRadius: 2, tension: .2}] : [])]},
        options: {maintainAspectRatio: false, plugins: {legend: {position: 'bottom'}}, scales: {y: {ticks: {callback: v => v + '%'}}, x: {ticks: {maxTicksLimit: 8}}}}});
    };
    const drawMap = () => {
      if(!window.L) return;
      if(lmap){ lmap.remove(); lmap = null; }
      lmap = L.map('p-map', {preferCanvas: true, scrollWheelZoom: false}).setView([-2.5, 118], 4.3);
      L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 10, attribution: '&copy; OpenStreetMap contributors · data: Cloudflare Radar (CC BY-NC 4.0)'}).addTo(lmap);
      const src = regOp === 'ID' ? nat : opShare[regOp], mx = Math.max(...Object.values(src).filter(v => v != null), 1);
      rows.forEach(r => { const g = geo[r.g], v = src[r.g]; if(v == null || g.latitude == null) return;
        const down = r.tr && r.tr.change != null && r.tr.change <= -10;
        L.circleMarker([+g.latitude, +g.longitude], {radius: 4 + 22 * Math.sqrt(v / mx), color: down ? '#B3261E' : '#2E5E8C', weight: 1.5, fillOpacity: .35})
          .bindTooltip(`<b>${esc(r.name)}</b><br>${fmt(v, 2)}% ${regOp === 'ID' ? 'traffic Indonesia' : 'traffic ' + esc(d.asns[regOp].label)}`)
          .on('click', () => { pickGeo = r.g; drawTrend(); }).addTo(lmap); });
    };
    el.querySelectorAll('tr[data-g]').forEach(tr => { const go = () => { pickGeo = tr.dataset.g; drawTrend(); };
      tr.onclick = go; tr.onkeydown = e => { if(e.key === 'Enter'){ e.preventDefault(); go(); } }; });
    el.querySelectorAll('.pub-chip[data-op]').forEach(b => b.onclick = () => { regOp = b.dataset.op;
      el.querySelectorAll('.pub-chip[data-op]').forEach(x => x.setAttribute('aria-pressed', x.dataset.op === regOp)); drawMap(); });
    drawMap(); drawTrend();
  },

  'pub-cells'(_, el){
    loadCells().then(({c, g}) => { if(window.PUB_VIEWS.current === 'pub-cells') cellsView(c, g, el); }).catch(e => {
      el.innerHTML = `<div class="ointro"><strong>Data cell distribution belum tersedia</strong> (${esc(e.message)}). Data dibuat oleh workflow mingguan
        <code>opencellid.yml</code> setelah secret <code>OPENCELLID_KEY</code> diisi.</div>`; });
  },

  'pub-quality'(d, el){
    const sp = (d.speed_ops || []).map(x => ({...x, dl: num(x.bandwidthDownload), ul: num(x.bandwidthUpload), lat: num(x.latencyIdle), latL: num(x.latencyLoaded),
      jit: num(x.jitterIdle), loss: num(x.packetLoss)})).sort((a, b) => (a.key === 'ID') - (b.key === 'ID') || (b.dl || 0) - (a.dl || 0));
    const bg = Object.entries(d.bgp).map(([k, s]) => ({k, ...s}));
    const pctV = s => s.routes_total ? (s.routes_valid || 0) / s.routes_total * 100 : null;
    const nat = sp.find(x => x.key === 'ID'), rv = bg.map(pctV).filter(v => v != null);
    el.innerHTML = hero(d, 'Quality &amp; BGP routing', 'Kecepatan dari speed test pengguna dan kesehatan BGP routing operator Indonesia', [
        [nat ? fmt(nat.dl, 0) + ' Mbps' : '–', 'median unduh Indonesia'], [nat ? fmt(nat.lat, 0) + ' ms' : '–', 'median latensi'],
        [rv.length ? fmt(avg(rv), 1) + '%' : '–', 'route RPKI valid (rata-rata operator)'], [fmt(d.hijacks.length), 'BGP hijack terbaru', d.hijacks.length ? 'bad' : 'good']]) + `<div>
      ${card('Kecepatan per operator', 'speed test pengguna di speed.cloudflare.com, median 90 hari', table([
        {l: 'Jaringan', h: r => r.key === 'ID' ? '<b>Indonesia (semua jaringan)</b>' : `<b>${asnName(d, r.key)}</b>`, w: 1},
        {l: 'Unduh (Mbps)', n: 1, h: r => fmt(r.dl, 1)}, {l: 'Unggah (Mbps)', n: 1, h: r => fmt(r.ul, 1)},
        {l: 'Latensi (ms)', n: 1, h: r => fmt(r.lat, 0)}, {l: 'Latensi saat sibuk (ms)', n: 1, h: r => fmt(r.latL, 0)}, {l: 'Jitter (ms)', n: 1, h: r => fmt(r.jit, 1)},
        {l: 'Packet loss', n: 1, h: r => r.loss == null ? '–' : fmt(r.loss, 2) + '%'}],
        sp, 'Data speed test belum tersedia.'))}
      ${card('BGP routing per operator', 'prefix yang diumumkan dan validasi RPKI', table([
        {l: 'Operator', h: r => asnName(d, r.k)},
        {l: 'Prefix IPv4', n: 1, h: r => fmt(r.distinct_prefixes_ipv4)}, {l: 'Prefix IPv6', n: 1, h: r => fmt(r.distinct_prefixes_ipv6)},
        {l: 'Route', n: 1, h: r => fmt(r.routes_total)},
        {l: 'RPKI valid', n: 1, h: r => pctV(r) == null ? '–' : fmt(pctV(r), 1) + '%'},
        {l: 'RPKI invalid', n: 1, h: r => r.routes_invalid ? `<span class="opill crit">${fmt(r.routes_invalid)}</span>` : '0'}],
        bg, 'Statistik BGP belum tersedia.'))}</div>
    ${card('BGP hijack yang melibatkan Indonesia', `${d.hijacks.length} kejadian terbaru; deteksi otomatis, skor keyakinan dari Radar (makin tinggi makin yakin)`, table([
      {l: 'Waktu', h: r => tgl(r.min_hijack_ts ? r.min_hijack_ts.replace(' ', 'T') + (/Z|\+/.test(r.min_hijack_ts) ? '' : 'Z') : r.detected_ts)},
      {l: 'Pembajak', h: r => `AS${esc(r.hijacker_asn)}${r.hijacker_country ? ' · ' + esc(r.hijacker_country) : ''}`},
      {l: 'Korban', h: r => (r.victim_asns || []).map(a => isOp(d, a) ? `<b>${asnName(d, a)}</b>` : 'AS' + esc(a)).join(', '), w: 1},
      {l: 'Prefix', n: 1, h: r => fmt((r.prefixes || []).length)}, {l: 'Keyakinan', n: 1, h: r => fmt(r.confidence_score)},
      {l: 'Durasi', n: 1, h: r => r.duration != null ? fmt(r.duration / 60, 0) + ' mnt' : '–'}],
      d.hijacks.slice(0, 50), 'Tidak ada BGP hijack tercatat yang melibatkan Indonesia.'))}
    ${card('BGP route leak yang melibatkan Indonesia', `${d.leaks.length} kejadian terbaru`, table([
      {l: 'Waktu', h: r => tgl(r.min_ts ? r.min_ts.replace(' ', 'T') + (/Z|\+/.test(r.min_ts) ? '' : 'Z') : r.detected_ts)},
      {l: 'AS pembocor', h: r => isOp(d, r.leak_asn) ? `<b>${asnName(d, r.leak_asn)}</b>` : 'AS' + esc(r.leak_asn)},
      {l: 'Prefix', n: 1, h: r => fmt(r.prefix_count)}, {l: 'Origin', n: 1, h: r => fmt(r.origin_count)}, {l: 'Peer', n: 1, h: r => fmt(r.peer_count)},
      {l: 'Status', h: r => r.finished ? 'selesai' : '<span class="opill warn">berlangsung</span>'}],
      d.leaks.slice(0, 50), 'Tidak ada route leak tercatat yang melibatkan Indonesia.'))}`;
  }
};

function cellsView(c, g, el){
  const R4 = k => (k.radio['4G'] || 0) + (k.radio['5G'] || 0);
  const val = k => cOp ? (k.op[cOp] || 0) : k.total;
  const METRICS = {pop: ['Sel per 100 ribu penduduk', k => k.pend ? val(k) / k.pend * 1e5 : null, 1],
    area: ['Sel per 1.000 km²', k => k.luas ? val(k) / k.luas * 1e3 : null, 1],
    modern: ['Porsi 4G + 5G', k => { const t = cOp ? ['4G', '5G'].reduce((s, r) => s + (k.op_radio[cOp + '|' + r] || 0), 0) : R4(k); return val(k) ? t / val(k) * 100 : null; }, 0],
    total: ['Jumlah sel', k => val(k), 0]};
  const K = c.kab, byK = Object.fromEntries(K.map(k => [k.k, k])), provs = [...new Set(K.map(k => k.prov))].filter(Boolean).sort();
  const tot = c.cells_indonesia || Object.values(c.by_op).reduce((s, v) => s + v, 0), recent = K.reduce((s, k) => s + k.recent, 0), inK = K.reduce((s, k) => s + k.total, 0);
  const radio = c.by_radio, rT = Object.values(radio).reduce((s, v) => s + v, 0);
  const topOp = Object.entries(c.by_op).filter(([o]) => o !== 'Lainnya').sort((a, b) => b[1] - a[1])[0];
  el.innerHTML = `<div class="pub-hero"><div class="ph-l"><span class="ph-live"><i></i>DATA NYATA · DIPERBARUI MINGGUAN</span>
      <div class="ph-t">Cell distribution</div><div class="ph-s">Sel 2G–5G yang terekam ponsel relawan OpenCelliD, diringkas per kabupaten/kota</div></div>
    <div class="ph-r"><div class="ph-k"><b>${fmt(tot)}</b><span>sel tercatat</span></div>
      <div class="ph-k"><b>${fmt(K.filter(k => k.total).length)}/${K.length}</b><span>kab/kota punya data</span></div>
      <div class="ph-k"><b>${fmt(rT ? ((radio['4G'] || 0) + (radio['5G'] || 0)) / rT * 100 : 0)}%</b><span>sel 4G + 5G</span></div>
      <div class="ph-k"><b>${fmt(inK ? recent / inK * 100 : 0)}%</b><span>terlihat 12 bulan terakhir</span></div></div></div>
  <div class="pub-src">Sumber <a href="${esc(c.attribution.url)}" target="_blank" rel="noopener noreferrer">OpenCelliD</a> ·
    <a href="${esc(c.attribution.license_url)}" target="_blank" rel="noopener noreferrer">${esc(c.attribution.license)}</a> · batas wilayah ${esc(c.attribution.boundaries)} ·
    diperbarui ${tgl(c.generated_at)} · operator terbanyak ${topOp ? esc(topOp[0]) : '–'}</div>
  <div class="ointro">Posisi sel adalah <b>perkiraan dari pengukuran ponsel relawan</b>, bukan koordinat BTS resmi, sehingga hanya ditampilkan per kabupaten/kota.
    Wilayah yang jarang dilewati relawan bisa tampak lebih sedikit selnya daripada kenyataan; angka cocok untuk membandingkan pola, bukan menghitung BTS.</div>
  <section class="card" style="margin-bottom:14px"><h3>Peta per kabupaten/kota</h3>
    <div style="display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin-bottom:8px">
      <div class="pub-chips" role="group" aria-label="Operator">${['', ...c.ops.filter(o => o !== 'Lainnya')].map(o => `<button type="button" class="pub-chip" data-cop="${esc(o)}" aria-pressed="${o === cOp}">${o || 'Semua operator'}</button>`).join('')}</div>
      <label class="muted" style="font-size:.85rem">Ukuran <select id="c-metric" class="btn">${Object.entries(METRICS).map(([k, m]) => `<option value="${k}"${k === cMetric ? ' selected' : ''}>${m[0]}</option>`).join('')}</select></label></div>
    <div id="c-map" style="height:430px;border-radius:8px;border:1px solid var(--rule)"></div><div class="olegend" id="c-leg"></div></section>
  <section class="card"><h3>Tabel kabupaten/kota <span id="c-cnt"></span></h3>
    <div style="display:flex;flex-wrap:wrap;gap:10px;margin-bottom:8px"><select id="c-prov" class="btn"><option value="">Semua provinsi</option>${provs.map(p => `<option${p === cProv ? ' selected' : ''}>${esc(p)}</option>`).join('')}</select>
      <input id="c-q" class="btn" type="search" placeholder="cari kab/kota" value="${esc(cQ)}" style="min-width:200px"></div>
    <div class="tw" style="max-height:520px;overflow-y:auto"><table id="c-tab"></table></div>
    <p class="onote">Operator dipetakan dari kode MNC 510-xx (penomoran publik): Indosat 01/21, Telkomsel 10, XL Axiata 11/08, Tri 89, Smartfren 09/28.</p></section>`;
  const colors = ['#F1F4F6', '#D6E4F0', '#A9C6E0', '#6E9CC7', '#3F72A6', '#1F4C7A'];
  const drawMap = () => {
    if(cmap){ cmap.remove(); cmap = null; }
    if(!window.L) return;
    const [lab, fn, dg] = METRICS[cMetric], vals = K.map(fn).filter(v => v != null && v > 0).sort((a, b) => a - b);
    const q = [.2, .4, .6, .8, .95].map(p => vals[Math.floor(p * (vals.length - 1))] || 0);
    const col = v => v == null || v <= 0 ? colors[0] : colors[1 + q.slice(0, 4).filter(t => v > t).length];
    cmap = L.map('c-map', {preferCanvas: true, scrollWheelZoom: false}).setView([-2.5, 118], 4.6);
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 11, attribution: '&copy; OpenStreetMap · sel: OpenCelliD (CC BY-SA 4.0) · batas: cahyadsn/wilayah'}).addTo(cmap);
    L.geoJSON(g, {style: f => { const k = byK[f.properties.k]; return {weight: .4, color: '#8FA1AC', fillOpacity: .8, fillColor: col(k ? fn(k) : null)}; },
      onEachFeature: (f, ly) => { const k = byK[f.properties.k]; if(!k) return;
        ly.bindTooltip(`<b>${esc(k.nama)}</b>, ${esc(k.prov)}<br>${lab}: ${fmt(fn(k), dg)}<br>${fmt(val(k))} sel${cOp ? ' ' + esc(cOp) : ''}`); }}).addTo(cmap);
    document.getElementById('c-leg').innerHTML = `<span>${lab}${cOp ? ' · ' + esc(cOp) : ''}:</span>` + colors.map((c2, i) =>
      `<span><i style="background:${c2};border-radius:2px"></i>${i === 0 ? 'tidak ada data' : i === 1 ? '≤ ' + fmt(q[0], dg) : i === 5 ? '> ' + fmt(q[3], dg) : fmt(q[i - 2], dg) + '–' + fmt(q[i - 1], dg)}</span>`).join('');
  };
  const COLS = [['nama', 'Kab/kota'], ['prov', 'Provinsi'], ['total', 'Sel', 1], ...c.ops.filter(o => o !== 'Lainnya').map(o => ['op:' + o, o, 1]),
    ['r:2G', '2G', 1], ['r:3G', '3G', 1], ['r:4G', '4G', 1], ['r:5G', '5G', 1], ['pop', 'Per 100 rb penduduk', 1], ['recent', 'Terlihat 12 bln', 1]];
  const v = (k, key) => key.startsWith('op:') ? (k.op[key.slice(3)] || 0) : key.startsWith('r:') ? (k.radio[key.slice(2)] || 0)
    : key === 'pop' ? (k.pend ? k.total / k.pend * 1e5 : -1) : key === 'recent' ? (k.total ? k.recent / k.total : -1) : k[key];
  const drawTable = () => {
    const ql = cQ.toLowerCase(), list = K.filter(k => (!cProv || k.prov === cProv) && (!ql || k.nama.toLowerCase().includes(ql)));
    const [sk, sd] = cSort; list.sort((a, b) => { const x = v(a, sk), y = v(b, sk); return (x > y ? 1 : x < y ? -1 : 0) * sd; });
    document.getElementById('c-cnt').textContent = `${list.length} wilayah`;
    const t = document.getElementById('c-tab');
    t.innerHTML = `<thead><tr>${COLS.map(([k, l, n]) => `<th class="${n ? 'r' : ''}" data-k="${esc(k)}" style="cursor:pointer"${k === sk ? ` aria-sort="${sd < 0 ? 'descending' : 'ascending'}"` : ''}>${esc(l)}</th>`).join('')}</tr></thead><tbody>
      ${list.map(k => `<tr><td><b>${esc(k.nama)}</b></td><td class="muted">${esc(k.prov)}</td><td class="r">${fmt(k.total)}</td>
        ${c.ops.filter(o => o !== 'Lainnya').map(o => `<td class="r">${fmt(k.op[o] || 0)}</td>`).join('')}
        ${['2G', '3G', '4G', '5G'].map(r => `<td class="r">${fmt(k.radio[r] || 0)}</td>`).join('')}
        <td class="r">${k.pend ? fmt(k.total / k.pend * 1e5, 1) : '–'}</td><td class="r">${k.total ? fmt(k.recent / k.total * 100) + '%' : '–'}</td></tr>`).join('')}</tbody>`;
    t.querySelectorAll('th[data-k]').forEach(th => th.onclick = () => { const k = th.dataset.k; cSort = [k, cSort[0] === k ? -cSort[1] : (k === 'nama' || k === 'prov' ? 1 : -1)]; drawTable(); });
  };
  el.querySelectorAll('.pub-chip[data-cop]').forEach(b => b.onclick = () => { cOp = b.dataset.cop;
    el.querySelectorAll('.pub-chip[data-cop]').forEach(x => x.setAttribute('aria-pressed', x.dataset.cop === cOp)); drawMap(); });
  document.getElementById('c-metric').onchange = e => { cMetric = e.target.value; drawMap(); };
  document.getElementById('c-prov').onchange = e => { cProv = e.target.value; drawTable(); };
  let qt; document.getElementById('c-q').oninput = e => { clearTimeout(qt); qt = setTimeout(() => { cQ = e.target.value; drawTable(); }, 200); };
  drawMap(); drawTable();
}

window.PUB_VIEWS = {
  has: v => v in VIEWS,
  render(v, el){
    charts.splice(0).forEach(c => c.destroy()); if(lmap){ lmap.remove(); lmap = null; } if(cmap){ cmap.remove(); cmap = null; }
    document.querySelectorAll('.synthetic, main > footer').forEach(n => n.hidden = true);
    el.innerHTML = '<div class="empty">Memuat data Cloudflare Radar…</div>';
    if(v === 'pub-cells'){ VIEWS[v](null, el); const sn = document.getElementById('snap'); if(sn) sn.textContent = 'Data nyata · OpenCelliD (CC BY-SA 4.0) · diperbarui mingguan'; return; }
    load().then(d => { if(window.PUB_VIEWS.current !== v) return; const sn = document.getElementById('snap'); if(sn) sn.textContent = window.PUB_VIEWS.snapText(); VIEWS[v](d, el); }).catch(e => {
      el.innerHTML = `<div class="ointro"><strong>Data publik belum tersedia</strong> (${esc(e.message)}). Snapshot dibuat oleh GitHub Actions setelah secret
        <code>CF_RADAR_TOKEN</code> diisi; coba lagi beberapa saat lagi.</div>`; });
  },
  leave(){ charts.splice(0).forEach(c => c.destroy()); if(lmap){ lmap.remove(); lmap = null; } if(cmap){ cmap.remove(); cmap = null; } document.querySelectorAll('.synthetic, main > footer').forEach(n => n.hidden = false); },
  snapText: () => data ? `Data nyata · Cloudflare Radar (CC BY-NC 4.0) · snapshot ${tgl(data.generated_at)}` : 'Data nyata · Cloudflare Radar (CC BY-NC 4.0)'
};
})();
