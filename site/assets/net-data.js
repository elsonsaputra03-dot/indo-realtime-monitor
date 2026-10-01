/* Network KPI Monitor: mesin data SINTETIS.
 * Geografi Kalimantan publik (assets/kalimantan.js); site, cell, dan semua counter dibangkitkan acak berbiji tetap.
 * KPI dihitung dari counter: Σ pembilang ÷ Σ penyebut pada level yang ditampilkan (cell, site, kabupaten, cluster, branch, region). */
(() => {
'use strict';
function rng(seed){ return () => { seed |= 0; seed = seed + 0x6D2B79F5 | 0; let t = Math.imul(seed ^ seed >>> 15, 1 | seed);
  t = t + Math.imul(t ^ t >>> 7, 61 | t) ^ t; return ((t ^ t >>> 14) >>> 0) / 4294967296; }; }
const R = rng(30082026);
const between = (a, b) => a + R() * (b - a);
const gauss = () => Math.sqrt(-2 * Math.log(R() || 1e-9)) * Math.cos(2 * Math.PI * R());
const DAYS = 14, DAY = 864e5, LAST = new Date('2026-08-31T00:00:00Z');
const dates = Array.from({length: DAYS}, (_, i) => new Date(+LAST - (DAYS - 1 - i) * DAY));

// ------------------------------------------------------------------ topologi
// Branch berbasis kota (format laporan count site); pembagian kabupaten ke branch & vendor per branch FIKTIF.
const KALI = window.KALI;
const BRANCH_OF = k => k.startsWith('61.') ? 'PONTIANAK' : ['62.01', '62.02', '62.07', '62.08', '62.09'].includes(k) ? 'PANGKALAN BUN'
  : k.startsWith('62.') ? 'PALANGKARAYA' : k.startsWith('63.') ? 'BANJARMASIN' : ['64.01', '64.07', '64.09', '64.11', '64.71'].includes(k) ? 'BALIKPAPAN'
  : k.startsWith('64.') ? 'SAMARINDA' : 'TARAKAN';
const BRANCH_VENDOR = {PONTIANAK: 'ZTE', 'PANGKALAN BUN': 'ZTE', PALANGKARAYA: 'ZTE', BANJARMASIN: 'EID', BALIKPAPAN: 'EID', SAMARINDA: 'EID', TARAKAN: 'EID'};
const KABS = KALI.kabs.map(k => ({...k, prov: k.p, p: BRANCH_OF(k.k), v: BRANCH_VENDOR[BRANCH_OF(k.k)]}));
// cluster: 1-2 kelompok per branch menurut bujur
[...new Set(KABS.map(k => k.p))].forEach(b => { const ks = KABS.filter(k => k.p === b).sort((x, y) => x.lng - y.lng), n = ks.length >= 6 ? 2 : 1, size = Math.ceil(ks.length / n);
  for(let i = 0; i < n; i++){ const g = ks.slice(i * size, (i + 1) * size); if(!g.length) continue;
    const a = g.find(x => x.n.startsWith('Kota')) || g[0], name = `${b.replace(' ', '')}-0${i + 1} ${a.n.replace('Kabupaten ', '').replace('Kota ', '')}`; g.forEach(x => x.c = name); } });
const VENDOR_OF = Object.fromEntries(KABS.map(k => [k.pk, k.v]));          // kompatibilitas lama (tidak dipakai untuk pembagian)
const KAB_IDX = Object.fromEntries(KABS.map((k, i) => [k.k, i]));
const BRANCH_ORDER = ['BALIKPAPAN', 'BANJARMASIN', 'PALANGKARAYA', 'PANGKALAN BUN', 'PONTIANAK', 'SAMARINDA', 'TARAKAN'];
const BRANCHES = BRANCH_ORDER.map(name => ({name, vendor: BRANCH_VENDOR[name], clusters: [...new Set(KABS.filter(k => k.p === name).map(k => k.c))].sort()}));
const SITES = KALI.sites.map(([kk, lat, lng, urban, dprov], i) => { const k = KABS[KAB_IDX[kk]];
  return {i, id: 'SYN-' + String(i + 1).padStart(4, '0'), branch: k.p, vendor: k.v, cluster: k.c, kab: k.n, kabKode: kk, kabI: KAB_IDX[kk],
    lat, lng, urban: !!urban, dprov, txIssue: R() < .025 ? {start: Math.floor(between(0, DAYS - 1))} : null, down: R() < .006, cells: [],
    type: urban && R() < .08 ? 'Indoor' : R() < .05 ? 'Micro' : 'Macro'}; });

const CELLS = {'2G': [], '4G': [], '5G': []};
const BAND_TECH = {GSM: '2G', DCS: '2G', L9: '4G', L18: '4G', L21: '4G', L23: '4G', NR21: '5G', NR23: '5G'};
const BAND_CODE = {GSM: 'MG', DCS: 'MD', L9: 'ML', L18: 'MT', L21: 'MR', L23: 'ME', NR21: 'NR', NR23: 'NE'};
function mkIssue(){ if(R() > .045) return null;
  return {type: ['avail', 'intf', 'cov', 'cap'][Math.floor(R() * 4)], start: R() < .45 ? Math.floor(between(DAYS - 3, DAYS)) : Math.floor(between(0, DAYS - 3)), sev: between(.5, 1)}; }
const shortKab = n => n.replace('Kabupaten ', '').replace('Kota ', '').toUpperCase().replace(/\s+/g, '').slice(0, 10);
for(const s of SITES){
  const add = band => { const tech = BAND_TECH[band]; for(let k = 1; k <= 3; k++){
    const c = {tech, site: s, band, sector: k, issue: mkIssue(), load: Math.min(3, Math.exp(gauss() * .5) * (s.urban ? 1.4 : .8))};
    c.id = `${s.id.replace('-', '')}_${band}_${k}`; c.bts = `${s.id.replace('-', '')}${BAND_CODE[band]}1_${shortKab(s.kab)}_${k}`;
    c.ci = tech === '2G' ? String(10000 + Math.floor(R() * 89999)) : String({L9: 30, L18: 20, L21: 10, L23: 40, NR21: 60, NR23: 50}[band] + k);
    c.i = CELLS[tech].length; CELLS[tech].push(c); s.cells.push(c); } };
  if(R() < .7) add('GSM');
  if(R() < .93) add('DCS');
  if(R() < .7) add('L9');
  if(R() < .97) add('L18');
  if(R() < (s.urban ? .97 : .9)) add('L21');
  if(R() < (s.urban ? .7 : .4)) add('L23');
  if(s.urban && R() < .14) add('NR23');
  if(s.urban && R() < .003) add('NR21');
  s.bands = [...new Set(s.cells.map(c => c.band))];
  s.has = {'2G': s.cells.some(c => c.tech === '2G'), '4G': s.cells.some(c => c.tech === '4G'), '5G': s.cells.some(c => c.tech === '5G')};
  s.techs = ['2G', '4G', '5G'].filter(t => s.has[t]);
}

// ------------------------------------------------------------------ counter per teknologi (nama mengikuti laporan harian EID/ZTE yang digabung)
const C = {
  '2G': ['avail_n', 'avail_d', 'cssr_n', 'cssr_d', 'ccsr_n', 'ccsr_d', 'sdsr_n', 'sdsr_d', 'sdb_n', 'sdb_d', 'tchb_n', 'tchb_d', 'tchd_n', 'tchd_d',
    'ho_n', 'ho_d', 'tbfe_n', 'tbfe_d', 'tbfc_n', 'tbfc_d', 'tbfu_n', 'tbfu_d', 'gprs_k', 'gprs_s', 'edge_k', 'edge_s', 'dlq_n', 'dlq_d', 'ulq_n', 'ulq_d',
    'icm_n', 'icm_d', 'pl_n', 'pl_d', 'tch_erl', 'sd_erl', 'payload'],
  '4G': ['avail_n', 'avail_d', 'cssr_n', 'cssr_d', 'rrc_n', 'rrc_d', 'erab_n', 'erab_d', 'drop_n', 'drop_d', 'ifho_n', 'ifho_d', 'iefho_n', 'iefho_d',
    'udl_k', 'udl_s', 'uul_k', 'uul_s', 'cdl_k', 'cdl_s', 'cul_k', 'cul_s', 'prbdl_n', 'prbdl_d', 'prbul_n', 'prbul_d', 'cqi_n', 'cqi_d', 'cqi7_n', 'cqi7_d',
    'se_n', 'se_d', 'ulint_n', 'ulint_d', 'vcssr_n', 'vcssr_d', 'verab_n', 'verab_d', 'vcdr_n', 'vcdr_d', 'pl_n', 'pl_d', 'dl_mb', 'ul_mb', 'volte_erl',
    'rrc_max', 'rrc_avg', 'act_user'],
  '5G': ['avail_n', 'avail_d', 'sn_n', 'sn_d', 'ret_n', 'ret_d', 'udl_k', 'udl_s', 'uul_k', 'uul_s', 'cdl_k', 'cdl_s', 'prbdl_n', 'prbdl_d', 'prbul_n', 'prbul_d',
    'iho_n', 'iho_d', 'eho_n', 'eho_d', 'cqi_n', 'cqi_d', 'se_n', 'se_d', 'lat_n', 'lat_d', 'pl_n', 'pl_d', 'ulint_n', 'ulint_d', 'dl_mb', 'ul_mb', 'rrc_max', 'rrc_avg']};
const CI = Object.fromEntries(Object.entries(C).map(([t, a]) => [t, Object.fromEntries(a.map((k, i) => [k, i]))]));

function counters(c, d, out){
  const r = rng((c.i * 7919 + d * 104729 + c.sector * 31) ^ (c.site.i * 2654435761) ^ (c.tech.charCodeAt(0) * 97));
  const n = () => 1 + (r() - .5) * .08;
  const iss = c.issue && d >= c.issue.start ? c.issue : null, sev = iss ? iss.sev : 0, t = iss && iss.type;
  const tx = c.site.txIssue && d >= c.site.txIssue.start;
  const load = c.load * ([0, 6].includes(dates[d].getUTCDay()) ? .93 : 1) * n();
  const outage = c.site.down && d >= DAYS - 2 ? .6 + r() * .4 : t === 'avail' ? .03 + sev * .3 : r() < .0015 ? r() * .08 : 0, up = 1 - outage;
  const I = CI[c.tech], set = (k, v) => { out[I[k]] = v; };
  const zte = c.site.vendor === 'ZTE', vb = (e, z) => zte ? z : e;       // karakter vendor fiktif: sedikit berbeda antar-vendor
  set('avail_n', 86400 * up); set('avail_d', 86400);
  if(c.tech === '2G'){
    const att = Math.round(900 * load * up), sd = Math.round(att * 1.6);
    const tchB = t === 'cap' ? .03 + sev * .08 : .002 * n(), sdB = t === 'cap' ? .01 + sev * .03 : .0012 * n();
    const sdF = (t === 'intf' ? .02 + sev * .05 : .004 * n()) * vb(.85, 1.3), dropR = (t === 'cov' ? .015 + sev * .04 : t === 'intf' ? .01 + sev * .02 : .005 * n()) * vb(.9, 1.25);
    set('sdb_d', sd); set('sdb_n', Math.round(sd * sdB)); set('sdsr_d', sd); set('sdsr_n', Math.round(sd * (1 - sdF)));
    set('tchb_d', att); set('tchb_n', Math.round(att * tchB)); set('tchd_d', Math.round(att * (1 - tchB))); set('tchd_n', Math.round(att * (1 - tchB) * dropR));
    set('cssr_d', att); set('cssr_n', Math.round(att * (1 - sdB) * (1 - sdF) * (1 - tchB)));
    set('ccsr_d', att); set('ccsr_n', Math.round(att * (1 - sdB) * (1 - sdF) * (1 - tchB) * (1 - dropR)));
    const ho = Math.round(att * .8); set('ho_d', ho); set('ho_n', Math.round(ho * (t === 'cov' ? .9 - sev * .1 : .975 + r() * .02)));
    const tbf = Math.round(2400 * load * up); set('tbfe_d', tbf); set('tbfe_n', Math.round(tbf * (t === 'intf' ? .93 : .99 + r() * .008)));
    set('tbfc_d', tbf); set('tbfc_n', Math.round(tbf * (t === 'cov' ? .92 : .985 + r() * .01))); set('tbfu_d', tbf); set('tbfu_n', Math.round(tbf * (.985 + r() * .012)));
    set('gprs_s', 3600 * up); set('gprs_k', (28 + r() * 10) * 3600 * up); set('edge_s', 3600 * up); set('edge_k', (t === 'intf' ? 80 : 150 + r() * 60) * 3600 * up);
    const q = Math.round(5e4 * up); set('dlq_d', q); set('dlq_n', Math.round(q * (t === 'intf' ? .9 - sev * .08 : .975 + r() * .02)));
    set('ulq_d', q); set('ulq_n', Math.round(q * (t === 'intf' ? .92 - sev * .06 : .98 + r() * .015)));
    set('icm_d', 1e4); set('icm_n', t === 'intf' ? 800 + sev * 1500 : 60 + r() * 150);
    const pk = Math.round(3e5 * load); set('pl_d', pk); set('pl_n', Math.round(pk * (tx ? .004 + r() * .01 : .0002 * n())));
    set('tch_erl', 18 * load * up); set('sd_erl', 2.2 * load * up); set('payload', 900 * load * up);
    return out;
  }
  if(c.tech === '4G'){
    const bandF = {L9: .7, L18: 1.2, L21: 1, L23: 1.3}[c.band];
    const rrc = Math.round(52000 * load * bandF * up * vb(1.04, .93)), erab = Math.round(rrc * 1.05);
    const rrcF = (t === 'intf' ? .015 + sev * .05 : t === 'cap' ? .005 + sev * .02 : .0015 * n()) * vb(.85, 1.35), erabF = (t === 'intf' ? .008 + sev * .03 : .001 * n()) * vb(.9, 1.3);
    const dropR = (t === 'cov' ? .012 + sev * .03 : t === 'intf' ? .006 + sev * .015 : .0022 * n()) * vb(.9, 1.22);
    set('rrc_d', rrc); set('rrc_n', Math.round(rrc * (1 - rrcF))); set('erab_d', erab); set('erab_n', Math.round(erab * (1 - erabF)));
    set('cssr_d', rrc); set('cssr_n', Math.round(rrc * (1 - rrcF) * (1 - erabF)));
    set('drop_d', erab); set('drop_n', Math.round(erab * dropR));
    const ho = Math.round(rrc * .35); set('ifho_d', ho); set('ifho_n', Math.round(ho * (t === 'cov' ? .9 - sev * .12 : vb(.987, .979) + r() * .01)));
    const ie = Math.round(rrc * .12); set('iefho_d', ie); set('iefho_n', Math.round(ie * (t === 'cov' ? .88 - sev * .1 : .97 + r() * .02)));
    const prb = Math.min(.99, t === 'cap' ? .78 + sev * .2 : Math.max(.05, (.16 * load * bandF + .05) * vb(.96, 1.07) + (r() - .5) * .04));
    const prbu = Math.min(.95, prb * (.45 + r() * .2));
    set('prbdl_d', 1e4 * up); set('prbdl_n', prb * 1e4 * up); set('prbul_d', 1e4 * up); set('prbul_n', prbu * 1e4 * up);
    const udl = Math.max(.8, (t === 'cap' ? 2.4 - sev * 1.2 : 17 * (1 - prb * .75) * bandF * vb(1.06, .9)) * (t === 'intf' ? .6 : 1) * n());
    set('udl_s', 3600 * up); set('udl_k', udl * 1000 * 3600 * up); set('uul_s', 3600 * up); set('uul_k', udl * (.12 + r() * .05) * 1000 * 3600 * up);
    set('cdl_s', 3600 * up); set('cdl_k', udl * (2.2 + prb * 2) * 1000 * 3600 * up); set('cul_s', 3600 * up); set('cul_k', udl * .35 * 1000 * 3600 * up);
    const cqi = (t === 'intf' ? 6.3 - sev : 9.4 + (r() - .5) * 1.2) + vb(.12, -.35);
    set('cqi_d', 1e3 * up); set('cqi_n', cqi * 1e3 * up); set('cqi7_d', 1e3 * up); set('cqi7_n', Math.min(.98, (cqi - 4) / 6.5) * 1e3 * up);
    set('se_d', 1e3 * up); set('se_n', (t === 'intf' ? .9 : 1.6 + r() * .6) * 1e3 * up);
    set('ulint_d', 1); set('ulint_n', t === 'intf' ? -98 + sev * 6 : -112 + r() * 5);
    const v = Math.round(1800 * load * up); set('vcssr_d', v); set('vcssr_n', Math.round(v * (t === 'intf' ? .96 : .993 + r() * .006)));
    set('verab_d', v); set('verab_n', Math.round(v * (t === 'intf' ? .97 : .995 + r() * .004))); set('vcdr_d', v); set('vcdr_n', Math.round(v * (t === 'cov' ? .02 + sev * .02 : (.003 + r() * .003) * vb(.9, 1.35))));
    const pk = Math.round(8e5 * load); set('pl_d', pk); set('pl_n', Math.round(pk * (tx ? .004 + r() * .01 : .0002 * n())));
    const vol = 26000 * load * bandF * up * n(); set('dl_mb', vol * .88); set('ul_mb', vol * .12); set('volte_erl', 6 * load * up);
    set('rrc_max', 90 * load * bandF * up); set('rrc_avg', 35 * load * bandF * up); set('act_user', 14 * load * bandF * up);
    return out;
  }
  const att = Math.round(9000 * load * up), f = t === 'intf' ? .02 + sev * .06 : .004 * n(), ret = t === 'cov' ? .015 + sev * .04 : .003 * n();
  const prb = Math.min(.99, t === 'cap' ? .8 + sev * .18 : .12 * load + .04);
  const tput = Math.max(15, (t === 'cap' ? 45 - sev * 20 : 260 * (1 - prb * .6) * vb(1.05, .9)) * (t === 'intf' ? .55 : 1) * n());
  set('sn_d', att); set('sn_n', Math.round(att * (1 - f))); set('ret_d', att); set('ret_n', Math.round(att * (1 - ret)));
  set('udl_s', 3600 * up); set('udl_k', tput * 1000 * 3600 * up); set('uul_s', 3600 * up); set('uul_k', tput * .11 * 1000 * 3600 * up);
  set('cdl_s', 3600 * up); set('cdl_k', tput * 2.4 * 1000 * 3600 * up);
  set('prbdl_d', 1e4 * up); set('prbdl_n', prb * 1e4 * up); set('prbul_d', 1e4 * up); set('prbul_n', prb * .4 * 1e4 * up);
  const h = Math.round(att * .3); set('iho_d', h); set('iho_n', Math.round(h * (t === 'cov' ? .9 : .985 + r() * .012)));
  set('eho_d', Math.round(h * .5)); set('eho_n', Math.round(h * .5 * (t === 'cov' ? .88 : .97 + r() * .02)));
  const cqi = t === 'intf' ? 7.5 - sev : 10.8 + (r() - .5) * 1.5; set('cqi_d', 1e3 * up); set('cqi_n', cqi * 1e3 * up);
  set('se_d', 1e3 * up); set('se_n', (t === 'intf' ? 2.2 : 4.2 + r() * 1.2) * 1e3 * up);
  set('lat_d', 1e3); set('lat_n', (tx ? 28 : 11 + r() * 4) * 1e3);
  const pk = Math.round(4e5 * load); set('pl_d', pk); set('pl_n', Math.round(pk * (tx ? .004 + r() * .01 : .0002 * n())));
  set('ulint_d', 1); set('ulint_n', t === 'intf' ? -100 + sev * 6 : -113 + r() * 5);
  const vol = 60000 * load * up * n(); set('dl_mb', vol * .9); set('ul_mb', vol * .1); set('rrc_max', 60 * load * up); set('rrc_avg', 22 * load * up);
  return out;
}

// ------------------------------------------------------------------ definisi KPI (rumus = Σ num ÷ Σ den)
const pct = (a, b) => b ? a / b * 100 : NaN, div = (a, b) => b ? a / b : NaN;
const K = (k, l, u, f, tgt, dir, fam, minDen) => ({k, l, u, f, tgt, dir, fam, minDen});
const KPI = {
  '2G': [
    K('avail', 'Availability', '%', s => pct(s.avail_n, s.avail_d), 99, 'min', 'Availability'),
    K('cssr', 'CSSR', '%', s => pct(s.cssr_n, s.cssr_d), 98.5, 'min', 'Accessibility', ['cssr_d', 50]),
    K('sdsr', 'SDSR', '%', s => pct(s.sdsr_n, s.sdsr_d), 98, 'min', 'Accessibility', ['sdsr_d', 50]),
    K('sdb', 'SD blocking', '%', s => pct(s.sdb_n, s.sdb_d), .5, 'max', 'Accessibility', ['sdb_d', 50]),
    K('tchb', 'TCH blocking', '%', s => pct(s.tchb_n, s.tchb_d), 2, 'max', 'Accessibility', ['tchb_d', 50]),
    K('ccsr', 'CCSR', '%', s => pct(s.ccsr_n, s.ccsr_d), 98, 'min', 'Retainability', ['ccsr_d', 50]),
    K('tchd', 'TCH drop', '%', s => pct(s.tchd_n, s.tchd_d), 1.5, 'max', 'Retainability', ['tchd_d', 50]),
    K('hosr', 'HOSR', '%', s => pct(s.ho_n, s.ho_d), 97, 'min', 'Mobility', ['ho_d', 50]),
    K('tbfe', 'TBF establishment SR', '%', s => pct(s.tbfe_n, s.tbfe_d), 98, 'min', 'Data', ['tbfe_d', 50]),
    K('tbfc', 'TBF completion SR', '%', s => pct(s.tbfc_n, s.tbfc_d), 97, 'min', 'Data', ['tbfc_d', 50]),
    K('tbfu', 'TBF UL establishment SR', '%', s => pct(s.tbfu_n, s.tbfu_d), 98, 'min', 'Data', ['tbfu_d', 50]),
    K('gprs', 'GPRS throughput', 'kbps', s => div(s.gprs_k, s.gprs_s), null, null, 'Data'),
    K('edge', 'EDGE throughput', 'kbps', s => div(s.edge_k, s.edge_s), 100, 'min', 'Data', ['edge_s', 60]),
    K('dlq', 'DL RX Qual 0–5', '%', s => pct(s.dlq_n, s.dlq_d), 97, 'min', 'Kualitas', ['dlq_d', 100]),
    K('ulq', 'UL RX Qual 0–5', '%', s => pct(s.ulq_n, s.ulq_d), 97, 'min', 'Kualitas', ['ulq_d', 100]),
    K('icm', 'ICM band 3–5', '%', s => pct(s.icm_n, s.icm_d), 5, 'max', 'Kualitas'),
    K('pl', 'Packet loss', '%', s => pct(s.pl_n, s.pl_d), .1, 'max', 'Kualitas', ['pl_d', 1000]),
    K('tch_erl', 'TCH traffic', 'Erl', s => s.tch_erl, null, null, 'Trafik'),
    K('sd_erl', 'SDCCH traffic', 'Erl', s => s.sd_erl, null, null, 'Trafik'),
    K('payload', 'Payload', 'GB', s => s.payload / 1024, null, null, 'Trafik')],
  '4G': [
    K('avail', 'Availability', '%', s => pct(s.avail_n, s.avail_d), 99, 'min', 'Availability'),
    K('cssr', 'Accessibility (CSSR)', '%', s => pct(s.cssr_n, s.cssr_d), 99, 'min', 'Accessibility', ['cssr_d', 100]),
    K('rrc', 'RRC setup SR', '%', s => pct(s.rrc_n, s.rrc_d), 99, 'min', 'Accessibility', ['rrc_d', 100]),
    K('erab', 'E-RAB setup SR', '%', s => pct(s.erab_n, s.erab_d), 99, 'min', 'Accessibility', ['erab_d', 100]),
    K('ret', 'Retainability', '%', s => pct(s.drop_d - s.drop_n, s.drop_d), 99.3, 'min', 'Retainability', ['drop_d', 100]),
    K('drop', 'Service drop rate', '%', s => pct(s.drop_n, s.drop_d), .7, 'max', 'Retainability', ['drop_d', 100]),
    K('ifho', 'Mobility (intra-freq HOSR)', '%', s => pct(s.ifho_n, s.ifho_d), 97, 'min', 'Mobility', ['ifho_d', 50]),
    K('iefho', 'Inter-freq HOSR', '%', s => pct(s.iefho_n, s.iefho_d), 95, 'min', 'Mobility', ['iefho_d', 50]),
    K('udl', 'User DL throughput', 'Mbps', s => div(s.udl_k, s.udl_s) / 1000, 5, 'min', 'Integrity', ['udl_s', 60]),
    K('uul', 'User UL throughput', 'Mbps', s => div(s.uul_k, s.uul_s) / 1000, .5, 'min', 'Integrity', ['uul_s', 60]),
    K('cdl', 'Cell DL throughput', 'Mbps', s => div(s.cdl_k, s.cdl_s) / 1000, null, null, 'Integrity'),
    K('cul', 'Cell UL throughput', 'Mbps', s => div(s.cul_k, s.cul_s) / 1000, null, null, 'Integrity'),
    K('prbdl', 'PRB DL utilization', '%', s => pct(s.prbdl_n, s.prbdl_d), 80, 'max', 'Utilisasi'),
    K('prbul', 'PRB UL utilization', '%', s => pct(s.prbul_n, s.prbul_d), 70, 'max', 'Utilisasi'),
    K('cqi', 'CQI rata-rata', '', s => div(s.cqi_n, s.cqi_d), 7, 'min', 'Kualitas'),
    K('cqi7', 'CQI ≥ 7', '%', s => pct(s.cqi7_n, s.cqi7_d), 70, 'min', 'Kualitas'),
    K('se', 'Spectral efficiency', 'bps/Hz', s => div(s.se_n, s.se_d), null, null, 'Kualitas'),
    K('ulint', 'UL interference', 'dBm', s => div(s.ulint_n, s.ulint_d), -105, 'max', 'Kualitas'),
    K('vcssr', 'VoLTE CSSR', '%', s => pct(s.vcssr_n, s.vcssr_d), 98.5, 'min', 'VoLTE', ['vcssr_d', 30]),
    K('verab', 'VoLTE E-RAB SSR', '%', s => pct(s.verab_n, s.verab_d), 99, 'min', 'VoLTE', ['verab_d', 30]),
    K('vcdr', 'VoLTE call drop rate', '%', s => pct(s.vcdr_n, s.vcdr_d), 1, 'max', 'VoLTE', ['vcdr_d', 30]),
    K('pl', 'Packet loss', '%', s => pct(s.pl_n, s.pl_d), .1, 'max', 'Kualitas', ['pl_d', 1000]),
    K('payload', 'Payload', 'TB', s => (s.dl_mb + s.ul_mb) / 1048576, null, null, 'Trafik'),
    K('volte_erl', 'VoLTE traffic', 'Erl', s => s.volte_erl, null, null, 'Trafik'),
    K('rrc_max', 'Max RRC conn. user', 'user', s => s.rrc_max, null, null, 'Trafik'),
    K('rrc_avg', 'Avg RRC conn. user', 'user', s => s.rrc_avg, null, null, 'Trafik'),
    K('act_user', 'Active user', 'user', s => s.act_user, null, null, 'Trafik')],
  '5G': [
    K('avail', 'Availability', '%', s => pct(s.avail_n, s.avail_d), 99, 'min', 'Availability'),
    K('sn', 'SgNB setup SR', '%', s => pct(s.sn_n, s.sn_d), 98, 'min', 'Accessibility', ['sn_d', 50]),
    K('ret', 'NR retainability', '%', s => pct(s.ret_n, s.ret_d), 99, 'min', 'Retainability', ['ret_d', 50]),
    K('iho', 'Intra HOSR', '%', s => pct(s.iho_n, s.iho_d), 97, 'min', 'Mobility', ['iho_d', 30]),
    K('eho', 'Inter HOSR', '%', s => pct(s.eho_n, s.eho_d), 95, 'min', 'Mobility', ['eho_d', 30]),
    K('udl', 'User DL throughput', 'Mbps', s => div(s.udl_k, s.udl_s) / 1000, 50, 'min', 'Integrity', ['udl_s', 60]),
    K('uul', 'User UL throughput', 'Mbps', s => div(s.uul_k, s.uul_s) / 1000, 5, 'min', 'Integrity', ['uul_s', 60]),
    K('cdl', 'Cell DL throughput', 'Mbps', s => div(s.cdl_k, s.cdl_s) / 1000, null, null, 'Integrity'),
    K('prbdl', 'PRB DL utilization', '%', s => pct(s.prbdl_n, s.prbdl_d), 80, 'max', 'Utilisasi'),
    K('prbul', 'PRB UL utilization', '%', s => pct(s.prbul_n, s.prbul_d), 70, 'max', 'Utilisasi'),
    K('cqi', 'CQI rata-rata', '', s => div(s.cqi_n, s.cqi_d), 9, 'min', 'Kualitas'),
    K('se', 'Spectral efficiency', 'bps/Hz', s => div(s.se_n, s.se_d), null, null, 'Kualitas'),
    K('lat', 'Latency DL', 'ms', s => div(s.lat_n, s.lat_d), 20, 'max', 'Kualitas'),
    K('pl', 'Packet loss', '%', s => pct(s.pl_n, s.pl_d), .1, 'max', 'Kualitas', ['pl_d', 1000]),
    K('ulint', 'UL interference', 'dBm', s => div(s.ulint_n, s.ulint_d), -105, 'max', 'Kualitas'),
    K('payload', 'Payload', 'TB', s => (s.dl_mb + s.ul_mb) / 1048576, null, null, 'Trafik'),
    K('rrc_max', 'Max RRC conn. user', 'user', s => s.rrc_max, null, null, 'Trafik'),
    K('rrc_avg', 'Avg RRC conn. user', 'user', s => s.rrc_avg, null, null, 'Trafik')]};

// ------------------------------------------------------------------ satu kali lintas: jumlah per kabupaten per hari + counter cell hari terakhir & kemarin
const NK = KABS.length, KAB_DAY = {}, CELL_LAST = {}, CELL_PREV = {};
for(const tech of ['2G', '4G', '5G']){
  const n = C[tech].length, kd = new Float64Array(NK * DAYS * n), cl = new Float64Array(CELLS[tech].length * n), cp = new Float64Array(CELLS[tech].length * n), tmp = new Float64Array(n);
  CELLS[tech].forEach((c, ci) => { for(let d = 0; d < DAYS; d++){ tmp.fill(0); counters(c, d, tmp);
    const o = (c.site.kabI * DAYS + d) * n; for(let j = 0; j < n; j++) kd[o + j] += tmp[j];
    if(d === DAYS - 1) cl.set(tmp, ci * n); if(d === DAYS - 2) cp.set(tmp, ci * n); } });
  KAB_DAY[tech] = kd; CELL_LAST[tech] = cl; CELL_PREV[tech] = cp;
}
const toObj = (tech, arr, off) => { const o = {}, a = C[tech]; for(let j = 0; j < a.length; j++) o[a[j]] = arr[off + j]; return o; };
function sumKab(tech, kabSet, d){ const n = C[tech].length, out = new Float64Array(n), kd = KAB_DAY[tech];
  for(let k = 0; k < NK; k++) if(!kabSet || kabSet.has(k)){ const o = (k * DAYS + d) * n; for(let j = 0; j < n; j++) out[j] += kd[o + j]; }
  return toObj(tech, out, 0); }
function sumCells(tech, cells, prev){ const n = C[tech].length, out = new Float64Array(n), src = prev ? CELL_PREV[tech] : CELL_LAST[tech];
  for(const c of cells){ const o = c.i * n; for(let j = 0; j < n; j++) out[j] += src[o + j]; } return toObj(tech, out, 0); }
const cellObj = (tech, c) => toObj(tech, CELL_LAST[tech], c.i * C[tech].length);

// ------------------------------------------------------------------ TWAMP per site per jam (hari terakhir)
const DIURNAL = Array.from({length: 24}, (_, h) => .25 + .9 * Math.exp(-((h - 20.5) ** 2) / 10) + .45 * Math.exp(-((h - 12) ** 2) / 8) + (h < 6 ? -.12 : 0));
SITES.forEach(s => { const pk = Math.max(...DIURNAL); s.twL = DIURNAL.map((w, h) => { const r = rng(s.i * 7349 + h * 13), tx = s.txIssue, busy = w / pk;
  const base = 4 + Math.min(12, s.dprov / 40) + r() * 3;
  return {lat: base * (1 + (tx ? .9 * busy + .3 : .12 * busy)) + (r() < .01 ? r() * 30 : 0), jit: (tx ? 4 + busy * 6 : .6 + busy * 1.2) * (1 + r() * .4),
    loss: tx ? (.05 + busy * .9) * r() * 2 : r() < .03 ? r() * .08 : 0}; }); });

// ------------------------------------------------------------------ productivity & availability: site harian Jan–Agu (diringkas per bulan & per branch-hari)
const P_START = new Date('2026-01-01T00:00:00Z'), P_DAYS = Math.round((LAST - P_START) / DAY) + 1;
const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'Mei', 'Jun', 'Jul', 'Agu'];
const PROD = [
  {k: 'tch2g', l: '2G TCH traffic', u: 'Erl', agg: 'sum', tech: '2G'}, {k: 'volte', l: '4G VoLTE traffic', u: 'Erl', agg: 'sum', tech: '4G'},
  {k: 'pay2g', l: '2G total payload', u: 'GB', agg: 'sum', tech: '2G', sc: 1 / 1024}, {k: 'pay4g', l: '4G total payload', u: 'TB', agg: 'sum', tech: '4G', sc: 1 / 1048576},
  {k: 'pay5g', l: '5G payload', u: 'TB', agg: 'sum', tech: '5G', sc: 1 / 1048576},
  {k: 'av2g', l: '2G availability', u: '%', agg: 'avg', tech: '2G', tgt: 99, dir: 'min'}, {k: 'av4g', l: '4G availability', u: '%', agg: 'avg', tech: '4G', tgt: 99, dir: 'min'},
  {k: 'av5g', l: '5G availability', u: '%', agg: 'avg', tech: '5G', tgt: 99, dir: 'min'},
  {k: 'rrcmax4', l: '4G max RRC conn. user', u: 'user', agg: 'sum', tech: '4G'}, {k: 'rrcavg4', l: '4G avg RRC conn. user', u: 'user', agg: 'sum', tech: '4G'},
  {k: 'rrcmax5', l: '5G max RRC conn. user', u: 'user', agg: 'sum', tech: '5G'}, {k: 'rrcavg5', l: '5G avg RRC conn. user', u: 'user', agg: 'sum', tech: '5G'},
  {k: 'act4', l: '4G active user', u: 'user', agg: 'sum', tech: '4G'}, {k: 'pl4', l: '4G packet loss', u: '%', agg: 'avg', tech: '4G', tgt: .1, dir: 'max'},
  {k: 'prbdl', l: 'Avg of max DL PRB utilization', u: '%', agg: 'avg', tech: '4G', tgt: 80, dir: 'max'},
  {k: 'prbul', l: 'Avg of max UL PRB utilization', u: '%', agg: 'avg', tech: '4G', tgt: 70, dir: 'max'}];
const NP = PROD.length, NB = BRANCHES.length, B_IDX = Object.fromEntries(BRANCHES.map((b, i) => [b.name, i]));
const P_SITE_M = new Float64Array(SITES.length * 8 * NP), P_SITE_MC = new Float32Array(SITES.length * 8 * NP);    // jumlah & hitungan (untuk rata-rata)
const P_BR_D = new Float64Array(NB * P_DAYS * NP), P_BR_DC = new Float32Array(NB * P_DAYS * NP);
(function genProd(){
  const eid = new Date('2026-03-20T00:00:00Z');                                           // libur Idul Fitri: pola trafik bergeser
  for(const s of SITES){
    const r = rng(s.i * 99991 + 7), c4 = s.cells.filter(c => c.tech === '4G'), c2 = s.cells.filter(c => c.tech === '2G').length, c5 = s.cells.filter(c => c.tech === '5G').length;
    const load4 = c4.reduce((a, c) => a + c.load, 0), bad = r() < .03 ? {from: Math.floor(r() * P_DAYS), len: 3 + Math.floor(r() * 25)} : null;
    const plBad = s.txIssue ? {from: Math.floor(r() * P_DAYS)} : null, bi = B_IDX[s.branch];
    for(let d = 0; d < P_DAYS; d++){
      const date = new Date(+P_START + d * DAY), m = date.getUTCMonth(), growth = 1 + .012 * m, wk = [0, 6].includes(date.getUTCDay()) ? .94 : 1;
      const hol = Math.abs(date - eid) / DAY < 5 ? (s.urban ? .82 : 1.12) : 1, nz = 1 + (r() - .5) * .07, L = growth * wk * hol * nz;
      const out = bad && d >= bad.from && d < bad.from + bad.len ? .05 + r() * .5 : r() < .004 ? r() * .2 : 0;
      const prb = Math.min(99, (18 + load4 * 3.2) * growth * (1 + (r() - .5) * .1) + (r() < .01 ? 25 : 0));
      const v = {tch2g: c2 ? 54 * c2 / 3 * L * (1 - out) : NaN, volte: c4.length ? 6 * load4 * L * (1 - out) : NaN, pay2g: c2 ? 900 * c2 / 3 * L * (1 - out) : NaN,
        pay4g: c4.length ? 26000 * load4 * L * (1 - out) : NaN, pay5g: c5 ? 60000 * c5 * L * (1 - out) : NaN,
        av2g: c2 ? 100 * (1 - out) : NaN, av4g: c4.length ? 100 * (1 - out) : NaN, av5g: c5 ? 100 * (1 - out * (1 + r())) : NaN,
        rrcmax4: c4.length ? 90 * load4 * L : NaN, rrcavg4: c4.length ? 35 * load4 * L : NaN, rrcmax5: c5 ? 60 * c5 * L : NaN, rrcavg5: c5 ? 22 * c5 * L : NaN,
        act4: c4.length ? 14 * load4 * L : NaN, pl4: c4.length ? (plBad && d >= plBad.from ? .2 + r() * .9 : r() < .02 ? r() * .3 : .01 + r() * .03) : NaN,
        prbdl: c4.length ? prb : NaN, prbul: c4.length ? prb * (.45 + r() * .15) : NaN};
      PROD.forEach((p, j) => { const x = v[p.k]; if(!isFinite(x)) return;
        const so = (s.i * 8 + m) * NP + j; P_SITE_M[so] += x; P_SITE_MC[so] += 1;
        const bo = (bi * P_DAYS + d) * NP + j; P_BR_D[bo] += x; P_BR_DC[bo] += 1; });
    }
  }
})();

const cellDay = (c, d) => toObj(c.tech, counters(c, d, new Float64Array(C[c.tech].length)), 0);
window.NET = {rng, DAYS, LAST, dates, KABS, KAB_IDX, BRANCHES, VENDOR_OF, BRANCH_VENDOR, SITES, CELLS, C, KPI, sumKab, sumCells, cellObj, cellDay, DIURNAL,
  PROD, MONTHS, P_START, P_DAYS, P_SITE_M, P_SITE_MC, P_BR_D, P_BR_DC, B_IDX, NP};
})();
