/* Kerangka bersama Data Governance: sidebar ikon, header, breadcrumb, footer, dan kartu KPI berikon.
   Ikon: CoreUI Icons Free (CC BY 4.0), lihat assets/cui-icons.js. */
(() => {
'use strict';
const ICONS = window.CUI_ICONS || {};
const icon = (n, cls = 'ci') => {
  const d = ICONS[n]; if(!d) return '';
  return `<svg class="${cls}" viewBox="${d[0]}" aria-hidden="true" focusable="false">${d[1]}</svg>`;
};
window.cuiIcon = icon;

// urutan ikon mengikuti rail referensi: speedometer, dollar, share, contact, apps-settings, dollar, people, tag, apps
const NAV = [
  {grp: 'Real BigQuery'},
  {href: 'bq-live.html', ic: 'speedometer', t: 'BigQuery live', s: 'real project', c: '#3399FF'},
  {grp: 'Cost & storage'},
  {href: 'governance.html', ic: 'dollar', t: 'Storage & cost', c: '#5856D6'},
  {grp: 'Metadata'},
  {href: 'lineage.html', ic: 'share-all', t: 'Data lineage', c: '#3399FF'},
  {href: 'dictionary.html', ic: 'contact', t: 'Data dictionary', c: '#2EB85C'},
  {grp: 'Data quality'},
  {href: 'anomaly.html', ic: 'apps-settings', t: 'Anomaly & missing', c: '#E55353'},
  {grp: 'Compute & usage'},
  {href: 'pipeline.html', ic: 'dollar', t: 'Pipeline cost', c: '#F9B115'},
  {href: 'users.html', ic: 'people', t: 'User analytics', c: '#5856D6'},
  {href: 'usage.html', ic: 'tag', t: 'Table usage', c: '#2EB85C'},
  {grp: 'App data'},
  {href: 'crawler.html', ic: 'apps', t: 'App crawler', c: '#3399FF'},
];
const here = (location.pathname.split('/').pop() || 'index.html').toLowerCase();
const cur = NAV.find(n => n.href === here) || {};

function buildRail(rail){
  rail.setAttribute('aria-label', 'Modul Data Governance');
  rail.innerHTML = `<a class="brand" href="governance.html" aria-label="Data Governance, beranda modul">
      <span class="logo">DG</span><span><b>Data Governance</b><small>Elson Saputra portfolio</small></span></a>
    <div class="nav">${NAV.map(n => n.grp ? `<div class="grp">${n.grp}</div>`
      : `<a href="${n.href}" title="${n.t}"${n.href === here ? ' aria-current="page"' : ''}>${icon(n.ic)}<span>${n.t}</span>${n.s ? `<small>${n.s}</small>` : ''}</a>`).join('')}</div>
    <div class="foot"><a href="index.html" title="Back to portfolio">${icon('account-logout')}<span>Back to portfolio</span></a></div>`;
}

function buildTop(main){
  const title = (main.querySelector('.head h1')?.textContent || cur.t || document.title).trim();
  const top = document.createElement('header');
  top.className = 'topbar';
  top.innerHTML = `<div class="row1">
      <button class="ib" type="button" id="rail-toggle" aria-label="Buka atau tutup menu" aria-expanded="false">${icon('menu')}</button>
      <div class="grow"></div>
      <a class="ib" href="anomaly.html" title="Alert anomaly & missing" aria-label="Alert anomaly">${icon('bell')}<span class="dot" aria-hidden="true"></span></a>
      <a class="ib" href="dictionary.html" title="Data dictionary" aria-label="Data dictionary">${icon('list')}</a>
      <a class="ib" href="mailto:elsonsaputra02@gmail.com" title="Email Elson" aria-label="Email Elson">${icon('envelope-closed')}</a>
      <span class="vr" aria-hidden="true"></span>
      <a href="index.html" title="Portofolio Elson Saputra"><img class="avatar" src="assets/elson.jpg" alt="Elson Saputra"></a>
    </div>
    <nav class="row2" aria-label="Breadcrumb"><a href="index.html">Home</a><span class="sep">/</span>
      <a href="governance.html">Data Governance</a><span class="sep">/</span><span aria-current="page">${title.replace(/</g, '&lt;')}</span></nav>`;
  return top;
}

const KC = ['#5856D6', '#3399FF', '#F9B115', '#2EB85C'];
function kpiIcon(label, i){
  const l = label.toLowerCase();
  if(/\$|cost|cost|usd|hemat|saving/.test(l)) return 'dollar';
  if(/tb|pb|gb|storage|size|size|byte/.test(l)) return 'storage';
  if(/anomal|missing|alert|gagal|fail|warn|telat|late/.test(l)) return 'warning';
  if(/user|user|developer|requester/.test(l)) return 'people';
  if(/job|pipeline|query|run/.test(l)) return 'bolt';
  if(/edge|relasi|lineage/.test(l)) return 'share-all';
  if(/column|column|describ|deskrip|dokumen/.test(l)) return 'contact';
  if(/app|app/.test(l)) return 'apps';
  if(/rating|review|reviews/.test(l)) return 'star';
  if(/negara|country|region/.test(l)) return 'globe-alt';
  if(/sukses|success|sehat|health|pass/.test(l)) return 'check-circle';
  if(/category|categor|genre/.test(l)) return 'list-rich';
  if(/rows|row/.test(l)) return 'speedometer';
  if(/table|table|object|dataset|project/.test(l)) return 'layers';
  return ['layers', 'storage', 'chart', 'speedometer'][i % 4];
}
function decorateKpis(root){
  root.querySelectorAll('.kpis').forEach(box => {
    [...box.children].forEach((k, i) => {
      if(!k.classList.contains('kpi') || k.classList.contains('has-ic')) return;
      const v = k.querySelector('.v'), lab = k.querySelector('.k');
      if(!v) return;
      if(lab && lab.compareDocumentPosition(v) & Node.DOCUMENT_POSITION_FOLLOWING) k.insertBefore(v, lab);   // angka di atas label
      const c = k.dataset.c || KC[i % 4];
      k.style.setProperty('--kc', c);
      const ic = document.createElement('div');
      ic.className = 'kic'; ic.setAttribute('aria-hidden', 'true');
      ic.innerHTML = icon(k.dataset.ic || kpiIcon((lab?.textContent || '') + ' ' + v.textContent, i));
      k.prepend(ic); k.classList.add('has-ic');
    });
  });
}

function init(){
  const shell = document.querySelector('.shell'); if(!shell) return;
  const rail = shell.querySelector('.rail'), main = shell.querySelector('main');
  if(rail) buildRail(rail);
  if(main && !main.querySelector('.topbar')){
    const wrap = document.createElement('div'); wrap.className = 'content';
    while(main.firstChild) wrap.appendChild(main.firstChild);
    main.append(buildTop(wrap), wrap);
    const foot = document.createElement('div'); foot.className = 'appfoot';
    foot.innerHTML = `<span>Data Governance · dibuat oleh <a href="index.html">Elson Saputra</a></span>
      <span>Tampilan bergaya <a href="https://coreui.io" target="_blank" rel="noopener noreferrer">CoreUI</a> (open source) · ikon CoreUI Icons, CC BY 4.0</span>`;
    main.append(foot);
  }
  // ikon judul halaman
  const h1 = document.querySelector('.head h1');
  if(h1 && !h1.querySelector('.pic') && cur.ic){
    const s = document.createElement('span'); s.className = 'pic'; s.style.setProperty('--pc', cur.c); s.innerHTML = icon(cur.ic);
    h1.prepend(s);
  }
  const tg = document.getElementById('rail-toggle');
  // layar lebar: sidebar berlabel (atau ikon saja jika dipilih); < 1200px: ikon saja; HP: menu geser
  const KEY = 'gov-rail'; let saved = (() => { try { return localStorage.getItem(KEY); } catch(e){ return null; } })();
  const mode = () => saved || (innerWidth >= 1200 ? 'wide' : 'narrow');
  let rm = mode();
  const apply = () => { document.body.classList.toggle('rail-wide', rm === 'wide'); document.body.classList.toggle('rail-narrow', rm === 'narrow'); };
  apply();
  addEventListener('resize', () => { if(!saved){ rm = mode(); apply(); } });
  tg?.addEventListener('click', () => {
    if(innerWidth <= 820){ const o = document.body.classList.toggle('rail-open'); tg.setAttribute('aria-expanded', o); return; }
    rm = rm === 'wide' ? 'narrow' : 'wide'; apply(); tg.setAttribute('aria-expanded', rm === 'wide');
    saved = rm; try { localStorage.setItem(KEY, rm); } catch(e){}
    setTimeout(() => dispatchEvent(new Event('resize')), 50);   // grafik menyesuaikan lebar baru
  });
  document.addEventListener('click', e => {
    if(document.body.classList.contains('rail-open') && !e.target.closest('.rail') && !e.target.closest('#rail-toggle')){
      document.body.classList.remove('rail-open'); tg?.setAttribute('aria-expanded', 'false'); }
  });
  document.addEventListener('keydown', e => { if(e.key === 'Escape') document.body.classList.remove('rail-open'); });
  decorateKpis(document);
  new MutationObserver(() => decorateKpis(document)).observe(document.body, {childList: true, subtree: true});
}
if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
