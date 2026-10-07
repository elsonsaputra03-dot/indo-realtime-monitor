/* Tampilan "Assurance" di Network KPI Monitor: alarm -> insiden, dampak pelanggan, sel tidur senyap, SLA, provisioning.
   Data: published/dashboard.json dari repo telco-oss-assurance (jaringan sintetis yang SAMA: ID site SYN-xxxx sama dengan peta). */
(function(){
const SRC = 'https://raw.githubusercontent.com/elsonsaputra03-dot/telco-oss-assurance/main/published/dashboard.json';
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = (v, d = 0) => v == null ? '' : Number(v).toLocaleString('id-ID', {maximumFractionDigits: d, minimumFractionDigits: d});
const pct = (a, b) => b ? Math.round(100 * a / b) : 0;
const TYPE = {transport_cut: 'Transmisi putus', power_outage: 'Catu daya padam', link_flapping: 'Link flapping',
              concurrent_cut: 'Dua gangguan bertingkat berselang menit', vswr: 'VSWR (RF)', cell_sleeping: 'Sel tidur (ada alarm)'};
const ROOT = {transport_link: 'Link transmisi', power: 'Catu daya'};
const NET = ['transport_cut', 'power_outage', 'link_flapping', 'concurrent_cut'];
let data = null, loading = null, map = null;

function load(){ return data ? Promise.resolve(data) : (loading ||= fetch(SRC, {cache: 'no-store'})
  .then(r => { if(!r.ok) throw new Error('HTTP ' + r.status); return r.json(); }).then(d => (data = d))); }
const table = (cols, rows) => `<div class="tw"><table><thead><tr>${cols.map(c => `<th class="${c.n ? 'r' : ''}">${esc(c.l)}</th>`).join('')}</tr></thead>
  <tbody>${rows.map(r => `<tr>${cols.map(c => `<td class="${c.n ? 'r' : ''}">${c.h ? c.h(r) : esc(r[c.k])}</td>`).join('')}</tr>`).join('')}</tbody></table></div>`;
const sev = s => `<span class="opill ${s === 'Critical' ? 'crit' : 'warn'}">${esc(s)}</span>`;
const bar = p => `<div class="obar" title="${p}%"><i style="width:${p}%"></i></div>`;
const note = t => `<p class="onote">${t}</p>`;
const intro = t => `<div class="ointro">${t}</div>`;
const kpi = (v, k, sub = '') => `<div class="kpi"><div class="v">${v}</div><div class="k">${k}</div>${sub ? `<div class="d" style="color:var(--muted)">${sub}</div>` : ''}</div>`;
function netAcc(d){ const v = NET.map(k => d.accuracy[k]).filter(Boolean); return pct(v.reduce((s, x) => s + x.correct, 0), v.reduce((s, x) => s + x.scenarios, 0)); }

const VIEWS = {
  'oss-alarm'(d){
    const a = d.alarms, nd = d.network_daily, gold = d.sla_by_tier.find(r => r.sla_tier === 'Gold');
    const orders = d.order_funnel.find(r => r.step === 'RECEIVED').orders, rej = (d.order_funnel.find(r => r.step === 'REJECTED') || {orders: 0}).orders;
    return intro(`Seminggu operasi pada jaringan sintetis yang sama dengan Ringkasan dan Peta: alarm dari 2 vendor (nama alarm mengikuti referensi publik),
      dikorelasikan memakai topologi transmisi dan urutan waktu. Korelator tidak pernah membaca label skenario; label hanya dipakai untuk menilai akurasinya.`) +
    `<div class="kpis" style="grid-template-columns:repeat(auto-fill,minmax(145px,1fr))">
      ${kpi(fmt(a.alarms), 'alarm dalam 7 hari', `${fmt(a.critical)} critical`)}
      ${kpi(fmt(a.network_incidents), 'insiden jaringan', `${netAcc(d)}% akar masalah benar`)}
      ${kpi(fmt(nd.reduce((s, r) => s + r.availability_pct, 0) / nd.length, 2) + '%', 'availability minggu ini')}
      ${kpi(d.kpi_detection.silent_detected_as_silent, 'sel tidur senyap', 'tanpa alarm, dari KPI')}
      ${kpi(`${gold.breached}/${gold.affected}`, 'layanan Gold lewat jatah SLA', 'dari yang terdampak')}
      ${kpi(pct(rej, orders) + '%', 'order ditolak', `${rej} dari ${orders}`)}
    </div>
    <div class="oflow">
      <div class="onode"><b>${fmt(a.alarms)}</b><span>alarm (30% alarm akar hilang, jam NE selisih ±3 menit)</span></div><div class="oarrow">→</div>
      <div class="onode"><b>${fmt(a.incidents)}</b><span>insiden, ${fmt(a.network_incidents)} di antaranya gangguan jaringan</span></div><div class="oarrow">→</div>
      <div class="onode"><b>${netAcc(d)}%</b><span>gangguan jaringan dengan akar masalah benar</span></div>
    </div>
    <div class="grid2">
      <div class="card"><h3>Akurasi per skenario <span>data sulit</span></h3>${table([
        {l: 'Skenario', h: r => esc(TYPE[r.k] || r.k)}, {l: 'Benar', n: 1, h: r => `${r.correct} / ${r.scenarios}`},
        {l: '', h: r => bar(pct(r.correct, r.scenarios))}, {l: 'Terpecah', n: 1, k: 'split'}, {l: 'Tercampur', n: 1, k: 'merged'}],
        Object.entries(d.accuracy).map(([k, v]) => ({k, ...v})))}
        ${note('Batas yang diketahui: dua gangguan di subtree yang sama berselang beberapa menit, dengan selisih jam sebesar itu, tetap ambigu bila hanya dari alarm.')}</div>
      <div class="card"><h3>Alarm paling sering <span>asal nama: referensi publik atau generik</span></h3>${table([
        {l: 'Vendor', h: r => r.vendor === 'EID' ? 'EID (Ericsson)' : esc(r.vendor)}, {l: 'Alarm', k: 'alarm_name'}, {l: 'Severity', h: r => sev(r.severity)},
        {l: 'Nama', h: r => `<span style="color:var(--muted)">${esc(r.name_source)}</span>`}, {l: 'Jumlah', n: 1, h: r => fmt(r.n)}], d.alarm_names)}</div>
    </div>`;
  },

  'oss-inc'(d){
    return intro(`Diurutkan menurut menit layanan pelanggan yang putus, dibobot menurut SLA (Gold 3x, Silver 2x, Bronze 1x), bukan menurut jumlah alarm. Pilih insiden untuk melihat
      pohon korelasinya dan site-nya di peta.`) +
    `<div class="ogrid3">
      <div class="card" style="padding:6px 0"><div class="oinc">${d.top_incidents.map(i => `<button type="button" data-id="${esc(i.incident_id)}" aria-pressed="false">
        <div class="t"><span>${esc(i.incident_id)} · ${esc(ROOT[i.root_type] || i.root_type)}</span><span>${fmt(i.weighted_impact)} mnt berbobot</span></div>
        <div class="s">${esc(i.branch)} · ${i.sites_affected} site · ${i.services} layanan (${i.gold_services} Gold), ${fmt(i.service_down_min)} mnt · ${fmt(i.alarm_count)} alarm</div></button>`).join('')}</div></div>
      <div class="card"><div id="o-head" style="font-size:.9rem;margin-bottom:8px"></div>
        <div id="o-map" role="region" aria-label="Peta site pada insiden terpilih"></div>
        <div class="olegend"><span><i style="background:#8E2A22"></i>site mati teratas (akar)</span><span><i style="background:#B3261E"></i>site korban</span>
          <span><i style="background:#3E8E5E"></i>site hulu, hidup</span><span>garis putus-putus = microwave</span></div>
        <div class="grid2"><div><h3 style="font-size:.95rem;margin:6px 0">Pohon korelasi</h3><div class="otree" id="o-tree"></div></div>
          <div><h3 style="font-size:.95rem;margin:6px 0">Alarm yang digabung ke insiden ini</h3><div id="o-mix"></div></div></div></div>
    </div>`;
  },

  'oss-sleep'(d){
    const k = d.kpi_detection, sl = d.sleeping_cells;
    return intro(`Sel yang <b>available</b> tetapi hampir tidak membawa trafik (di bawah 5% dari normal sel itu pada jam yang sama, minimal 3 jam berturut-turut),
      dari counter PM per jam. Precision ${fmt(100 * k.precision)}%, recall ${fmt(100 * k.recall)}%, dan <b>${k.silent_detected_as_silent} dari ${k.silent_truth}</b>
      sel yang sama sekali tidak memunculkan alarm ditemukan dan dilabeli senyap.`) +
    `<div class="card">${table([{l: 'Cell', k: 'cell_id'}, {l: 'Branch', k: 'branch'}, {l: 'Teknologi', k: 'tech'}, {l: 'Mulai', k: 'started_at'},
      {l: 'Jam', n: 1, k: 'hours'}, {l: 'Alarm', h: r => r.has_alarm ? '<span class="opill warn">ada alarm</span>' : '<span class="opill crit">senyap</span>'}], sl)}
      ${note(`${sl.length} temuan, yang senyap ditampilkan lebih dulu. Kongesti (PRB > 85% minimal 3 jam sehari): ${fmt(d.congestion.cells)} sel, ${fmt(d.congestion.cell_days)} sel-hari.`)}</div>`;
  },

  'oss-sla'(d){
    const at = d.sla_attribution;
    return intro(`${fmt(d.sla_by_tier.reduce((s, r) => s + r.services, 0))} layanan korporat sintetis menumpang di site jaringan ini. Downtime <b>diukur dari counter KPI</b>
      site-nya dan dilacak ke insiden penyebabnya (${fmt(100 - 100 * at.unattributed_min / at.down_min, 1)}% terlacak). SLA kontrak bersifat bulanan, jadi minggu ini
      dinilai terhadap jatah downtime sebulan.`) +
    `<div class="grid2">
      <div class="card"><h3>Per tier</h3>${table([{l: 'Tier', k: 'sla_tier'}, {l: 'SLA', n: 1, h: r => r.sla_pct + '%'},
        {l: 'Jatah / bulan', n: 1, h: r => fmt(r.budget_min, 0) + ' mnt'}, {l: 'Layanan', n: 1, k: 'services'}, {l: 'Terdampak', n: 1, k: 'affected'},
        {l: 'Lewat jatah', n: 1, h: r => `<b>${r.breached}</b>`}], d.sla_by_tier)}
        ${note('Setiap layanan Gold yang terdampak menghabiskan jatah 43 menit sebulannya: gangguan berlangsung 20 menit sampai 6 jam dan setiap layanan hanya punya satu jalur. 99,9% butuh jalur cadangan.')}</div>
      <div class="card"><h3>Jatah bulanan paling banyak terpakai</h3>${table([{l: 'Layanan', k: 'service_id'}, {l: 'Tier', k: 'sla_tier'}, {l: 'Sektor', k: 'sector'},
        {l: 'Mnt putus', n: 1, h: r => fmt(r.down_min)}, {l: 'Jatah terpakai', n: 1, h: r => fmt(r.budget_used_pct, 0) + '%'}, {l: 'Insiden', k: 'incident_ids'}],
        d.sla_worst.slice(0, 12))}</div>
    </div>`;
  },

  'oss-prov'(d){
    const orders = d.order_funnel.find(r => r.step === 'RECEIVED').orders;
    return intro(`<b>Simulasi</b> alur order layanan korporat. Kelayakan memeriksa setiap link di jalur site ke core: puncak backhaul seluler di belakang link itu
      (dari counter KPI) ditambah layanan korporat aktif, dibandingkan dengan kapasitasnya.`) +
    `<div class="grid2">
      <div class="card"><h3>Alur order</h3>${table([{l: 'Langkah', k: 'step'}, {l: 'Order', n: 1, k: 'orders'}, {l: '', h: r => bar(pct(r.orders, orders))}], d.order_funnel)}</div>
      <div class="card"><h3>Link yang paling sering menolak order <span>kandidat upgrade</span></h3>${table([{l: 'Link', k: 'link_id'}, {l: 'Jenis', k: 'link_type'},
        {l: 'Kapasitas Mbps', n: 1, h: r => fmt(r.capacity_mbps)}, {l: 'Utilisasi', n: 1, h: r => fmt(r.util_pct, 0) + '%'}, {l: 'Ditolak', n: 1, k: 'rejected_orders'}],
        d.bottlenecks)}</div>
    </div>`;
  },
};

function drawIncident(inc){
  document.querySelectorAll('.oinc button').forEach(b => b.setAttribute('aria-pressed', b.dataset.id === inc.incident_id));
  const sites = inc.sites, byId = Object.fromEntries(sites.map(s => [s.site_id, s]));
  const top = byId[inc.top_site], reporter = top ? top.parent : null, rep = reporter && byId[reporter], kids = {};
  sites.forEach(s => { if(s.site_id !== reporter && s.site_id !== inc.top_site) (kids[s.parent] ||= []).push(s); });
  const node = (s, depth) => { const ch = (kids[s.site_id] || []).sort((a, b) => a.site_id.localeCompare(b.site_id));
    return `<li><span class="${s.site_id === inc.top_site ? 'root' : ''}">${esc(s.site_id)}</span><span style="color:var(--muted)"> · ${fmt(s.alarms)} alarm
      ${s.services ? ` · ${s.services} layanan` : ''}${s.link_type === 'microwave' && depth ? ' · MW' : ''}</span>${ch.length ? `<ul>${ch.map(c => node(c, depth + 1)).join('')}</ul>` : ''}</li>`; };
  document.getElementById('o-head').innerHTML = `<b>${esc(inc.incident_id)}</b> · ${esc(ROOT[inc.root_type] || inc.root_type)} <code>${esc(inc.root_object)}</code> ·
    ${esc(inc.branch)} · ${esc(inc.started_at)} – ${esc(inc.ended_at.slice(11))} (${fmt(inc.minutes)} mnt)<br><span style="color:var(--muted)">${fmt(inc.alarm_count)} alarm → 1 insiden ·
    ${inc.sites_affected} site mati · ${inc.services} layanan dari ${inc.customers} pelanggan (${inc.gold_services} Gold) · bukti: ${esc(inc.evidence)}</span>`;
  document.getElementById('o-tree').innerHTML = `<ul>${rep ? `<li><span>${esc(rep.site_id)}</span> <span class="opill">hidup · melaporkan alarm link</span>
    <ul>${top ? node(top, 0) : ''}</ul></li>` : top ? node(top, 0) : ''}</ul>`;
  document.getElementById('o-mix').innerHTML = table([{l: 'Alarm', h: r => `${esc(r.alarm_name)}${r.severity === 'Critical' ? ' <span class="opill crit">C</span>' : ''}`}, {l: 'Jumlah', n: 1, h: r => fmt(r.n)}], inc.alarm_mix);
  if(!window.L) return;
  if(!map){
    map = L.map('o-map', {preferCanvas: true});
    L.tileLayer('https://tile.openstreetmap.org/{z}/{x}/{y}.png', {maxZoom: 14, attribution: '&copy; OpenStreetMap contributors · site sintetis'}).addTo(map);
    map._ossLayer = L.layerGroup().addTo(map);
  }
  const layer = map._ossLayer; layer.clearLayers();
  sites.forEach(s => { const p = byId[s.parent]; if(p && s.site_id !== reporter)
    L.polyline([[p.lat, p.lon], [s.lat, s.lon]], {color: '#5D6D78', weight: 1.5, opacity: .7, dashArray: s.link_type === 'microwave' ? '4 4' : null}).addTo(layer); });
  sites.forEach(s => { const isTop = s.site_id === inc.top_site, isRep = s.site_id === reporter;
    L.circleMarker([s.lat, s.lon], {radius: isTop ? 9 : isRep ? 7 : 5, color: '#fff', weight: 2, fillOpacity: 1, fillColor: isRep ? '#3E8E5E' : isTop ? '#8E2A22' : '#B3261E'})
      .bindTooltip(`${s.site_id}${isTop ? ' (site mati teratas)' : isRep ? ' (hulu, hidup)' : ''}<br>${s.alarms} alarm`).addTo(layer); });
  map.fitBounds(L.latLngBounds(sites.map(s => [s.lat, s.lon])).pad(.25));
}

window.OSS_VIEWS = {
  has: v => v in VIEWS,
  render(v, el){
    if(map){ map.remove(); map = null; }
    el.innerHTML = '<div class="empty">Memuat data OSS…</div>';
    load().then(d => {
      if(window.OSS_VIEWS.current !== v) return;                       // pengguna sudah pindah tampilan
      el.innerHTML = VIEWS[v](d) + `<p class="onote">Data diekspor ${esc(d.generated_at)} dari repo
        <a href="https://github.com/elsonsaputra03-dot/telco-oss-assurance" target="_blank" rel="noopener noreferrer">telco-oss-assurance</a>.</p>`;
      if(v === 'oss-inc'){
        const byId = Object.fromEntries(d.top_incidents.map(i => [i.incident_id, i]));
        el.querySelectorAll('.oinc button').forEach(b => b.onclick = () => drawIncident(byId[b.dataset.id]));
        drawIncident(d.top_incidents[0]);
      }
    }).catch(e => { el.innerHTML = `<div class="empty">Data OSS tidak bisa dimuat (${esc(e.message)}).</div>`; });
  },
  leave(){ if(map){ map.remove(); map = null; } },
};
})();
