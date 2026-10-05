// "Ask any question": tombol mengambang + popup percakapan yang memanggil Worker portfolio-chat.
// Isi pertanyaan tidak dicatat di analitik; hanya jumlah pemakaian (event 'ask-portfolio') yang dihitung GoatCounter.
(() => {
  const dlg = document.getElementById("ap-dialog");
  if (!dlg) return;
  const API = dlg.dataset.endpoint;
  const $ = s => dlg.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const log = $(".ap-log"), form = $("form"), input = $("input"), send = $("button[type=submit]");
  let turn = 0, opener = null;

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
      if (window.goatcounter?.count) window.goatcounter.count({ path: "ask-portfolio", title: "Ask any question", event: true });
    } catch (e) {
      wait.classList.remove("ap-wait"); wait.classList.add("ap-err");
      wait.textContent = e.message === "Failed to fetch" ? "The assistant is unreachable right now. Please try again later." : e.message;
    } finally { send.disabled = false; input.focus(); log.scrollTop = log.scrollHeight; }
  }

  form.addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
  dlg.querySelectorAll(".ap-chip").forEach(b => b.addEventListener("click", () => ask(b.textContent)));
})();
