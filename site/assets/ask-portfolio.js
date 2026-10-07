// "Ask any question": tombol mengambang + popup percakapan yang memanggil Worker portfolio-chat.
// Isi pertanyaan tidak dicatat di analitik; hanya jumlah pemakaian (event 'ask-portfolio') yang dihitung GoatCounter.
(() => {
  const dlg = document.getElementById("ap-dialog");
  if (!dlg) return;
  const API = dlg.dataset.endpoint;
  const $ = s => dlg.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const log = $(".ap-log"), form = $(".ap-form"), input = $(".ap-form input"), send = $(".ap-form button[type=submit]");
  let turn = 0, opener = null, lastQ = "", lastA = "";

  function open(from) {
    opener = from || document.activeElement;
    if (!dlg.open) dlg.showModal();
    document.documentElement.classList.add("ap-lock");
    setTimeout(() => input.focus(), 30);
  }
  function close() { dlg.close(); }
  dlg.addEventListener("close", () => { document.documentElement.classList.remove("ap-lock"); opener?.focus?.(); });
  dlg.addEventListener("click", e => { if (e.target === dlg) close(); });            // klik di luar panel
  $(".ap-close").addEventListener("click", close);
  document.querySelectorAll("[data-ap-open]").forEach(b => b.addEventListener("click", () => open(b)));
  if (location.hash === "#ask") open();

  function bubble(cls, html) {
    const el = document.createElement("div");
    el.className = `ap-msg ${cls}`; el.innerHTML = html;
    log.appendChild(el); log.scrollTop = log.scrollHeight;
    return el;
  }

  function answerHtml(d, t) {
    const cite = s => esc(s).replace(/\[(\d+)\]/g, (m, n) => `<sup><a href="#ap-${t}-${n}">[${n}]</a></sup>`);
    let h = `<p>${cite(d.answer)}</p>`;
    if (d.excerpts) h += d.excerpts.map(e => `<blockquote>${esc(e)}</blockquote>`).join("");
    if (d.sources?.length)
      h += `<ol class="ap-src">${d.sources.map(s => `<li id="ap-${t}-${s.n}"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`).join("")}</ol>`;
    return h;
  }

  async function ask(q) {
    q = q.trim();
    if (!q || send.disabled) return;
    const t = ++turn;
    $(".ap-intro")?.remove();
    bubble("ap-q", esc(q));
    const wait = bubble("ap-a ap-wait", '<span class="ap-dots"><i></i><i></i><i></i></span>');
    input.value = ""; send.disabled = true;
    try {
      const r = await fetch(API + "/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      wait.classList.remove("ap-wait"); wait.innerHTML = answerHtml(d, t);
      lastQ = q; lastA = d.mode === "llm" ? d.answer : "";
      if (d.mode !== "llm") {                                   // tidak ada di portofolio / ditolak: tawarkan bertanya langsung
        const b = document.createElement("button"); b.type = "button"; b.className = "ap-link"; b.textContent = "Ask Elson directly →";
        b.addEventListener("click", () => openDirect(q)); wait.appendChild(b);
      }
      if (window.goatcounter?.count) window.goatcounter.count({ path: "ask-portfolio", title: "Ask any question", event: true });
    } catch (e) {
      wait.classList.remove("ap-wait"); wait.classList.add("ap-err");
      wait.textContent = e.message === "Failed to fetch" ? "The assistant is unreachable right now. Please try again later." : e.message;
    } finally { send.disabled = false; input.focus(); log.scrollTop = log.scrollHeight; }
  }

  // ---- pertanyaan langsung ke Elson (diteruskan ke Telegram, tidak disimpan)
  const panel = $(".ap-direct"), dform = $(".ap-dform"), dstat = $(".ap-dstatus");
  function openDirect(prefill) {
    panel.hidden = false; dstat.textContent = ""; dstat.className = "ap-dstatus";
    if (prefill && !dform.question.value) dform.question.value = prefill;
    (dform.question.value ? dform.contact : dform.question).focus();
  }
  dlg.querySelectorAll("[data-ap-direct]").forEach(b => b.addEventListener("click", () => openDirect(lastQ)));
  $(".ap-dcancel").addEventListener("click", () => { panel.hidden = true; input.focus(); });
  dform.addEventListener("submit", async e => {
    e.preventDefault();
    const f = dform, btn = f.querySelector("button[type=submit]");
    const fail = m => { dstat.textContent = m; dstat.className = "ap-dstatus err"; };
    if (f.question.value.trim().length < 5) return fail("Please write your question.");
    if (!f.contact.value.trim()) return fail("Please enter your email or WhatsApp number so Elson can reply.");
    if (!f.consent.checked) return fail("Please tick the box to agree to send your contact to Elson.");
    btn.disabled = true; dstat.className = "ap-dstatus"; dstat.textContent = "Sending…";
    try {
      const r = await fetch(API + "/contact", { method: "POST", headers: { "content-type": "application/json" },
        body: JSON.stringify({ question: f.question.value.trim(), name: f.name.value.trim(), contact: f.contact.value.trim(),
                               consent: true, website: f.website.value, aiAnswer: lastA, page: location.href.split("#")[0] }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(r.status === 404 ? "direct messages are not available yet, please use the Contact section" : d.error || `HTTP ${r.status}`);
      $(".ap-intro")?.remove();
      bubble("ap-a ap-ok", `<p>Sent. Elson will reply to <b>${esc(f.contact.value.trim())}</b> as soon as he can.</p>`);
      if (window.goatcounter?.count) window.goatcounter.count({ path: "ask-portfolio-direct", title: "Ask Elson directly", event: true });
      f.reset(); panel.hidden = true;
    } catch (err) {
      fail(err.message === "Failed to fetch" ? "Could not reach the server. Please try again later." : err.message.charAt(0).toUpperCase() + err.message.slice(1) + ".");
    } finally { btn.disabled = false; }
  });

  form.addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
  dlg.querySelectorAll(".ap-chip").forEach(b => b.addEventListener("click", () => ask(b.textContent)));
})();
