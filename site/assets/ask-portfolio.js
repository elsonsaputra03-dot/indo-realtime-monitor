// Kotak "Ask about my work": mengirim pertanyaan ke Worker portfolio-chat dan menampilkan jawaban beserta sumbernya.
// Isi pertanyaan tidak dicatat di analitik; hanya jumlah pemakaian (event 'ask-portfolio') yang dihitung GoatCounter.
(() => {
  const box = document.getElementById("ask-portfolio");
  if (!box) return;
  const API = box.dataset.endpoint;
  const $ = s => box.querySelector(s);
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const form = $("form"), input = $("input"), out = $(".ap-out"), btn = $("button[type=submit]");

  function render(d) {
    const cite = t => esc(t).replace(/\[(\d+)\]/g, (m, n) => `<sup><a href="#ap-src-${n}">[${n}]</a></sup>`);
    let html = `<p class="ap-answer">${cite(d.answer)}</p>`;
    if (d.excerpts) html += d.excerpts.map((e, i) => `<blockquote>${esc(e)}</blockquote>`).join("");
    if (d.sources?.length) {
      html += `<ol class="ap-sources">${d.sources.map(s => `<li id="ap-src-${s.n}"><a href="${esc(s.url)}" target="_blank" rel="noopener noreferrer">${esc(s.title)}</a></li>`).join("")}</ol>`;
    }
    out.innerHTML = html;
  }

  async function ask(q) {
    q = q.trim();
    if (!q) return;
    btn.disabled = true; out.innerHTML = '<p class="ap-wait">Looking through the portfolio…</p>';
    try {
      const r = await fetch(API + "/ask", { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ question: q }) });
      const d = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(d.error || `HTTP ${r.status}`);
      render(d);
      if (window.goatcounter?.count) window.goatcounter.count({ path: "ask-portfolio", title: "Ask about my work", event: true });
    } catch (e) {
      out.innerHTML = `<p class="ap-err">${esc(e.message === "Failed to fetch" ? "The assistant is unreachable right now." : e.message)}</p>`;
    } finally { btn.disabled = false; }
  }

  form.addEventListener("submit", e => { e.preventDefault(); ask(input.value); });
  box.querySelectorAll(".ap-chip").forEach(b => b.addEventListener("click", () => { input.value = b.textContent; ask(b.textContent); }));
})();
