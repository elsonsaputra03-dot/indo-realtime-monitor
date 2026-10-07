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
const CAUSE = {POWER_OUTAGE: 'Listrik padam', CABLE_CUT: 'Kabel putus', WEATHER: 'Cuaca', GOVERNMENT_DIRECTED: 'Perintah pemerintah',
  TECHNICAL_PROBLEM: 'Masalah teknis', MAINTENANCE: 'Pemeliharaan', EARTHQUAKE: 'Gempa bumi', FIRE: 'Kebakaran', CYBERATTACK: 'Serangan siber',
  MILITARY_ACTION: 'Aksi militer', UNKNOWN: 'Tidak diketahui'};
const TYPE = {NATIONWIDE: 'Nasional', REGIONAL: 'Regional', NETWORK: 'Jaringan operator', PLATFORM: 'Platform'};
const COLORS = ['#B3261E', '#2E5E8C', '#C9901D', '#3E8E5E', '#8F3F97', '#1D8A99'];
let data = null, loading = null, charts = [], pickAsn = null;

const kpi = (v, k, sub = '') => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div>${sub ? `<div class="d" style="color:var(--muted)">${sub}</div>` : ''}</div>`;
const table = (cols, rows, empty) => rows.length ? `<div class="tw"><table><thead><tr>${cols.map(c => `<th class="${c.n ? 'r' : ''}">${esc(c.l)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c.n ? 'r' : ''}${c.w ? ' wrap' : ''}">${c.h ? c.h(r) : esc(r[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`
  : `<p class="onote">${empty}</p>`;
const card = (title, sub, body) => `<section class="card" style="margin-bottom:14px"><h3>${title}${sub ? ` <span>${sub}</span>` : ''}</h3>${body}</section>`;
const asnName = (d, asn) => { const a = d.asns[String(asn)]; return a ? `${a.label} <span class="muted">AS${asn}</span>` : `AS${esc(asn)}`; };
const isOp = (d, asn) => !!d.asns[String(asn)];
const head = d => `<div class="ointro pub-real"><strong>Data nyata, publik.</strong> Sumber <a href="${esc(d.attribution.url)}" target="_blank" rel="noopener noreferrer">Cloudflare Radar</a>,
  lisensi <a href="${esc(d.attribution.license_url)}" target="_blank" rel="noopener noreferrer">${esc(d.attribution.license)}</a>. Diambil otomatis oleh GitHub Actions
  (snapshot ${tgl(d.generated_at)}). Ini pandangan dari luar jaringan operator (trafik yang melewati Cloudflare), bukan data OSS internal operator.</div>`;
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
    el.innerHTML = head(d) + `<div class="kpis" style="grid-template-columns:repeat(auto-fill,minmax(170px,1fr))">
      ${kpi(fmt(outs.length), 'gangguan tercatat', '12 bulan, Indonesia')}
      ${kpi(fmt(anos.length), 'anomali trafik', 'deteksi otomatis Radar')}
      ${kpi(fmt(opsHit.size), 'operator utama terdampak', 'dari ' + Object.keys(d.asns).length + ' yang dipantau')}
      ${kpi(outs[0] ? tglD(outs[0].startDate) : '–', 'gangguan terakhir', outs[0] ? esc(CAUSE[outs[0].cause] || outs[0].cause || '') : '')}
    </div>
    <div class="grid2" style="margin-bottom:14px">
      <section class="card"><h3>Kejadian per bulan</h3><div class="chart" style="height:220px"><canvas id="p-month"></canvas></div></section>
      <section class="card"><h3>Penyebab gangguan <span>menurut catatan Radar</span></h3>${table([{l: 'Penyebab', k: 'c'}, {l: 'Jumlah', k: 'n', n: 1}],
        Object.entries(causes).sort((a, b) => b[1] - a[1]).map(([c, n]) => ({c, n})), 'Belum ada gangguan tercatat.')}</section></div>
    ${card('Gangguan internet (outage)', 'dikurasi tim Radar, dengan penyebab dan tautan sumber', table([
      {l: 'Mulai', h: r => tgl(r.startDate)}, {l: 'Durasi', h: r => dur(r.startDate, r.endDate)},
      {l: 'Cakupan', h: r => esc(TYPE[r.type] || r.type || '') + (r.scope ? `<br><small class="muted">${esc(r.scope)}</small>` : ''), w: 1},
      {l: 'Operator', h: r => r.asns.length ? r.asns.map(a => asnName(d, a)).join('<br>') : '<span class="muted">tidak spesifik</span>', w: 1},
      {l: 'Penyebab', h: r => esc(CAUSE[r.cause] || r.cause || '–')},
      {l: 'Keterangan', h: r => esc(r.description || '') + (r.linkedUrl ? ` <a href="${esc(r.linkedUrl)}" target="_blank" rel="noopener noreferrer">sumber</a>` : ''), w: 1}],
      outs, 'Tidak ada gangguan tercatat untuk Indonesia dalam 12 bulan terakhir.'))}
    ${card('Anomali trafik', 'penurunan trafik yang terdeteksi otomatis; belum tentu dikonfirmasi sebagai gangguan', table([
      {l: 'Mulai', h: r => tgl(r.startDate)}, {l: 'Selesai', h: r => r.endDate ? tgl(r.endDate) : '<span class="opill warn">berlangsung</span>'},
      {l: 'Jenis', h: r => r.type === 'ASN' ? 'Operator (ASN)' : r.type === 'LOCATION' ? 'Wilayah' : esc(r.type)},
      {l: 'Operator / wilayah', h: r => r.asn ? asnName(d, r.asn) + (isOp(d, r.asn) ? '' : `<br><small class="muted">${esc(r.asn_name || '')}</small>`) : esc(r.location || 'Indonesia'), w: 1},
      {l: 'Status', h: r => esc(r.status || '')}],
      anos.slice(0, 80), 'Tidak ada anomali trafik tercatat.'))}`;
    chart(document.getElementById('p-month'), {type: 'bar', data: {labels: M, datasets: [
      {label: 'Gangguan', data: M.map(m => months[m].o), backgroundColor: '#B3261E', stack: 's'},
      {label: 'Anomali trafik', data: M.map(m => months[m].a), backgroundColor: '#C9901D', stack: 's'}]},
      options: {maintainAspectRatio: false, plugins: {legend: {position: 'bottom'}}, scales: {x: {stacked: true}, y: {stacked: true, ticks: {precision: 0}}}}});
  },

  'pub-traffic'(d, el){
    const keys = Object.keys(d.asns).filter(k => d.traffic[k] && (d.traffic[k].http || d.traffic[k].netflows));
    pickAsn = keys.includes(pickAsn) ? pickAsn : keys[0];
    const rows = keys.map(k => { const s = d.traffic[k].http || d.traffic[k].netflows, n = s.v.length, w = Math.min(168, Math.floor(n / 2));
      const last = avg(s.v.slice(n - w)), prev = avg(s.v.slice(n - 2 * w, n - w)), dr = drops(s);
      return {k, label: d.asns[k].label, name: d.asns[k].name, change: last != null && prev ? (last / prev - 1) * 100 : null, drops: dr.length,
              worst: dr.sort((a, b) => a.ratio - b.ratio)[0], src: d.traffic[k].http ? 'HTTP' : 'NetFlows'}; });
    el.innerHTML = head(d) + `<div class="ointro">Trafik dinormalisasi oleh Radar (0 = terendah, 1 = tertinggi dalam periode), jadi yang dibandingkan adalah <b>pola</b>, bukan volume
      antar-operator. Penurunan tidak normal dihitung di sini: nilai satu jam di bawah 60% median jam yang sama pada hari yang sama di minggu-minggu lain.</div>
    ${card('Ringkasan per operator', '28 hari terakhir, per jam', table([
      {l: 'Operator', h: r => `<b>${esc(r.label)}</b> <span class="muted">AS${r.k}</span><br><small class="muted">${esc(r.name)}</small>`, w: 1},
      {l: 'Perubahan 7 hari terakhir', n: 1, h: r => r.change == null ? '–' : `<span class="${r.change < -10 ? 'up' : ''}">${r.change > 0 ? '+' : ''}${fmt(r.change, 1)}%</span>`},
      {l: 'Jam turun tidak normal', n: 1, h: r => r.drops ? `<span class="opill crit">${r.drops}</span>` : '0'},
      {l: 'Penurunan terdalam', h: r => r.worst ? `${tgl(r.worst.t)}<br><small class="muted">${fmt(r.worst.ratio * 100)}% dari normal</small>` : '–'},
      {l: 'Sumber', k: 'src'}], rows, 'Data trafik belum tersedia.'))}
    <section class="card"><h3>Pola trafik per jam <span>operator vs Indonesia</span></h3>
      <div class="pub-chips" role="group" aria-label="Pilih operator">${keys.map(k => `<button type="button" class="pub-chip" data-k="${k}" aria-pressed="${k === pickAsn}">${esc(d.asns[k].label)}</button>`).join('')}</div>
      <div class="chart" style="height:300px"><canvas id="p-traffic"></canvas></div>
      <p class="onote">Titik merah = jam dengan penurunan tidak normal. Waktu dalam WIB.</p></section>`;
    const draw = () => {
      charts.splice(0).forEach(c => c.destroy());
      const s = d.traffic[pickAsn].http || d.traffic[pickAsn].netflows, id = d.traffic.ID && (d.traffic.ID.http || d.traffic.ID.netflows);
      const dr = new Set(drops(s).map(x => x.t)), lab = s.t.map(t => new Date(t).toLocaleString('id-ID', {day: '2-digit', month: 'short', hour: '2-digit', timeZone: 'Asia/Jakarta'}));
      chart(document.getElementById('p-traffic'), {type: 'line', data: {labels: lab, datasets: [
        {label: d.asns[pickAsn].label, data: s.v, borderColor: '#2E5E8C', borderWidth: 1.4, pointRadius: s.t.map(t => dr.has(t) ? 3.5 : 0), pointBackgroundColor: '#B3261E', tension: .2},
        ...(id ? [{label: 'Indonesia (semua)', data: s.t.map(t => { const j = id.t.indexOf(t); return j < 0 ? null : id.v[j]; }), borderColor: '#B7C4CC', borderWidth: 1, pointRadius: 0, tension: .2}] : [])]},
        options: {maintainAspectRatio: false, interaction: {mode: 'index', intersect: false}, plugins: {legend: {position: 'bottom'}},
          scales: {x: {ticks: {maxTicksLimit: 10}}, y: {min: 0, max: 1}}}});
      el.querySelectorAll('.pub-chip').forEach(b => b.setAttribute('aria-pressed', b.dataset.k === pickAsn));
    };
    el.querySelectorAll('.pub-chip').forEach(b => b.onclick = () => { pickAsn = b.dataset.k; draw(); });
    if(pickAsn) draw();
  },

  'pub-quality'(d, el){
    const sp = d.speed.map(x => ({...x, dl: num(x.bandwidthDownload), ul: num(x.bandwidthUpload), lat: num(x.latencyIdle), latL: num(x.latencyLoaded), jit: num(x.jitterIdle)}));
    const bg = Object.entries(d.bgp).map(([k, s]) => ({k, ...s}));
    const pctV = s => s.routes_total ? (s.routes_valid || 0) / s.routes_total * 100 : null;
    el.innerHTML = head(d) + `<div class="grid2" style="margin-bottom:14px">
      ${card('Kecepatan per jaringan', 'speed test pengguna (Cloudflare speed.cloudflare.com), median 90 hari, Indonesia', table([
        {l: 'Jaringan', h: r => isOp(d, r.clientASN) ? `<b>${asnName(d, r.clientASN)}</b>` : `${esc(r.clientASName)} <span class="muted">AS${esc(r.clientASN)}</span>`, w: 1},
        {l: 'Unduh (Mbps)', n: 1, h: r => fmt(r.dl, 1)}, {l: 'Unggah (Mbps)', n: 1, h: r => fmt(r.ul, 1)},
        {l: 'Latensi (ms)', n: 1, h: r => fmt(r.lat, 0)}, {l: 'Latensi saat sibuk (ms)', n: 1, h: r => fmt(r.latL, 0)}, {l: 'Jitter (ms)', n: 1, h: r => fmt(r.jit, 1)}],
        sp, 'Data speed test belum tersedia.'))}
      ${card('Routing BGP per operator', 'prefix yang diumumkan dan validasi RPKI', table([
        {l: 'Operator', h: r => asnName(d, r.k)},
        {l: 'Prefix IPv4', n: 1, h: r => fmt(r.distinct_prefixes_ipv4)}, {l: 'Prefix IPv6', n: 1, h: r => fmt(r.distinct_prefixes_ipv6)},
        {l: 'Route', n: 1, h: r => fmt(r.routes_total)},
        {l: 'RPKI valid', n: 1, h: r => pctV(r) == null ? '–' : fmt(pctV(r), 1) + '%'},
        {l: 'RPKI invalid', n: 1, h: r => r.routes_invalid ? `<span class="opill crit">${fmt(r.routes_invalid)}</span>` : '0'}],
        bg, 'Statistik BGP belum tersedia.'))}</div>
    ${card('BGP hijack yang melibatkan Indonesia', '12 bulan; deteksi otomatis, skor keyakinan dari Radar', table([
      {l: 'Waktu', h: r => tgl(r.min_hijack_ts ? r.min_hijack_ts.replace(' ', 'T') + (/Z|\+/.test(r.min_hijack_ts) ? '' : 'Z') : r.detected_ts)},
      {l: 'Pembajak', h: r => `AS${esc(r.hijacker_asn)}${r.hijacker_country ? ' · ' + esc(r.hijacker_country) : ''}`},
      {l: 'Korban', h: r => (r.victim_asns || []).map(a => isOp(d, a) ? `<b>${asnName(d, a)}</b>` : 'AS' + esc(a)).join(', '), w: 1},
      {l: 'Prefix', n: 1, h: r => fmt((r.prefixes || []).length)}, {l: 'Keyakinan', n: 1, h: r => fmt(r.confidence_score)},
      {l: 'Durasi', n: 1, h: r => r.duration != null ? fmt(r.duration / 60, 0) + ' mnt' : '–'}],
      d.hijacks.slice(0, 50), 'Tidak ada BGP hijack tercatat yang melibatkan Indonesia.'))}
    ${card('BGP route leak yang melibatkan Indonesia', '12 bulan', table([
      {l: 'Waktu', h: r => tgl(r.min_ts ? r.min_ts.replace(' ', 'T') + (/Z|\+/.test(r.min_ts) ? '' : 'Z') : r.detected_ts)},
      {l: 'AS pembocor', h: r => isOp(d, r.leak_asn) ? `<b>${asnName(d, r.leak_asn)}</b>` : 'AS' + esc(r.leak_asn)},
      {l: 'Prefix', n: 1, h: r => fmt(r.prefix_count)}, {l: 'Origin', n: 1, h: r => fmt(r.origin_count)}, {l: 'Peer', n: 1, h: r => fmt(r.peer_count)},
      {l: 'Status', h: r => r.finished ? 'selesai' : '<span class="opill warn">berlangsung</span>'}],
      d.leaks.slice(0, 50), 'Tidak ada route leak tercatat yang melibatkan Indonesia.'))}`;
  }
};

window.PUB_VIEWS = {
  has: v => v in VIEWS,
  render(v, el){
    charts.splice(0).forEach(c => c.destroy());
    document.querySelectorAll('.synthetic, main > footer').forEach(n => n.hidden = true);
    el.innerHTML = '<div class="empty">Memuat data Cloudflare Radar…</div>';
    load().then(d => { if(window.PUB_VIEWS.current !== v) return; const sn = document.getElementById('snap'); if(sn) sn.textContent = window.PUB_VIEWS.snapText(); VIEWS[v](d, el); }).catch(e => {
      el.innerHTML = `<div class="ointro"><strong>Data publik belum tersedia</strong> (${esc(e.message)}). Snapshot dibuat oleh GitHub Actions setelah secret
        <code>CF_RADAR_TOKEN</code> diisi; coba lagi beberapa saat lagi.</div>`; });
  },
  leave(){ charts.splice(0).forEach(c => c.destroy()); document.querySelectorAll('.synthetic, main > footer').forEach(n => n.hidden = false); },
  snapText: () => data ? `Data nyata · Cloudflare Radar (CC BY-NC 4.0) · snapshot ${tgl(data.generated_at)}` : 'Data nyata · Cloudflare Radar (CC BY-NC 4.0)'
};
})();
