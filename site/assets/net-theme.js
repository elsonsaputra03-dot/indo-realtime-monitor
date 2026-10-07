/* Network KPI Monitor: kerangka tampilan (pita judul, ikon menu, status data). Tidak mengubah data atau logika laporan. */
(function(){
'use strict';
const ICON = {summary: 'speedometer', map: 'location-pin', wpc: 'warning', '2G': 'chart-line', '4G': 'chart-line', '5G': 'chart-line',
  'oss-alarm': 'bell', 'oss-inc': 'people', 'oss-sleep': 'clock', 'oss-sla': 'check-circle', 'oss-prov': 'list-rich',
  'pub-outage': 'warning', 'pub-traffic': 'chart', 'pub-region': 'globe-alt', 'pub-cells': 'lan', 'pub-towers': 'location-pin', 'pub-quality': 'share-all'};
const GROUP = {Laporan: 'g-lap', Report: 'g-lap', Teknologi: 'g-tek', Technology: 'g-tek', Assurance: 'g-ass'};
function svg(n){ const d = (window.CUI_ICONS || {})[n]; return d ? `<svg class="ni" viewBox="${d[0]}" aria-hidden="true" fill="currentColor">${d[1]}</svg>` : ''; }

function init(){
  document.querySelectorAll('.rail h2').forEach(h => { const t = h.textContent.trim(); h.classList.add(GROUP[t] || (/Internet/.test(t) ? 'g-pub' : 'g-lap')); });
  document.querySelectorAll('.rail a[data-view]').forEach(a => { if(!a.querySelector('.ni')) a.insertAdjacentHTML('afterbegin', svg(ICON[a.dataset.view] || 'chart')); });
  const back = document.querySelector('.rail .back a'); if(back && !back.querySelector('.ni')) back.insertAdjacentHTML('afterbegin', svg('account-logout'));

  const head = document.querySelector('main > .head'), syn = document.querySelector('main > .synthetic');
  if(head && !head.closest('.net-hero')){
    const hero = document.createElement('section'); hero.className = 'net-hero';
    head.before(hero); hero.appendChild(head);
    const r = document.createElement('div'); r.className = 'nh-r';
    r.innerHTML = `<span class="nh-badge"><i></i>DATA SINTETIS · REGION KALIMANTAN</span>` +
      (syn ? `<details class="nh-about"><summary>Tentang data ini</summary><p>${syn.innerHTML}</p></details>` : '');
    hero.appendChild(r);
  }
  const sync = () => document.body.classList.toggle('pub-active', location.hash.slice(1).startsWith('pub-'));
  addEventListener('hashchange', sync);
  const t = document.getElementById('title'); if(t) new MutationObserver(sync).observe(t, {childList: true, characterData: true, subtree: true});
  sync();
}
if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', init); else init();
})();
