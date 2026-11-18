const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const suggestBox = document.getElementById("suggest");
const modeNote = document.getElementById("modeNote");
const statusLine = document.getElementById("statusLine");
const seg = document.getElementById("sourceSeg");

const BOT_ICON = '<svg viewBox="0 0 24 24"><path d="M3 21V9l6-4v4l6-4v5h6v11z"/></svg>';
const YOU_ICON = '<svg viewBox="0 0 24 24"><path d="M12 12a5 5 0 1 0-5-5 5 5 0 0 0 5 5m0 2c-4 0-9 2-9 5v3h18v-3c0-3-5-5-9-5"/></svg>';

let history = [];
let source = "both";
let busy = false;

const esc = (s) => String(s).replace(/[&<>"']/g, c =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

const now = () => new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });

/** Minimal, escaped-first markdown: tables, bold, links, citations, lists. */
function md(src) {
  const lines = esc(src).split("\n");
  const out = [];
  let i = 0;
  while (i < lines.length) {
    // table: header | --- | rows
    if (/\|/.test(lines[i]) && /^\s*\|?[\s:|-]+\|[\s:|-]*$/.test(lines[i + 1] || "")) {
      const cells = (l) => l.trim().replace(/^\||\|$/g, "").split("|").map(c => c.trim());
      const head = cells(lines[i]);
      i += 2;
      const rows = [];
      while (i < lines.length && lines[i].includes("|")) rows.push(cells(lines[i++]));
      out.push(
        "<table><thead><tr>" + head.map(h => `<th>${h}</th>`).join("") +
        "</tr></thead><tbody>" +
        rows.map(r => "<tr>" + r.map(c => `<td>${c}</td>`).join("") + "</tr>").join("") +
        "</tbody></table>");
      continue;
    }
    out.push(lines[i++]);
  }
  return out.join("\n")
    .replace(/^###\s*(.+)$/gm, "<b>$1</b>")
    .replace(/^\s*[-*]\s+/gm, "• ")
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g,
      '<a href="$2" target="_blank" rel="noopener">$1</a>')
    .replace(/\[(\d+)\]/g, '<span class="cite">[$1]</span>')
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^/, "<p>").replace(/$/, "</p>");
}

function addMsg(role, bodyHtml, { error = false } = {}) {
  const wrap = document.createElement("div");
  wrap.className = `msg ${role}`;
  const isBot = role === "bot";
  wrap.innerHTML =
    `<div class="meta">
       <span class="avatar sm">${isBot ? BOT_ICON : YOU_ICON}</span>
       <span class="who">${isBot ? "Property Assistant" : "You"}</span>
       <span class="time">${now()}</span>
     </div>
     <div class="bubble${error ? " err" : ""}">${bodyHtml}</div>`;
  chat.appendChild(wrap);
  chat.scrollTop = chat.scrollHeight;
  return wrap;
}

function addSources(wrap, sources) {
  if (!sources || !sources.length) return;
  const box = document.createElement("div");
  box.className = "srcs";
  box.innerHTML = sources.map(s =>
    `<a href="${esc(s.url)}" target="_blank" rel="noopener">
       <span class="tag">[${s.n}] ${s.source === "darglobal" ? "DarGlobal" : "Wasalt"}</span>
       <span class="ttl">${esc((s.title || s.url).slice(0, 70))}</span>
     </a>`).join("");
  wrap.appendChild(box);
}

async function ask(q) {
  q = (q || "").trim();
  if (busy || !q) return;
  busy = true;
  send.disabled = true;
  suggestBox.style.display = "none";
  addMsg("user", esc(q));
  input.value = "";

  const pending = addMsg("bot", '<span class="typing"><i></i><i></i><i></i></span>');
  const bubble = pending.querySelector(".bubble");
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message: q, history: history.slice(-10), source }),
    });
    if (!r.ok) {
      const e = await r.json().catch(() => ({}));
      throw new Error(e.detail || `HTTP ${r.status}`);
    }
    const data = await r.json();
    bubble.innerHTML = md(data.answer);
    addSources(pending, data.sources);
    history.push({ role: "user", content: q },
                 { role: "assistant", content: data.answer });
  } catch (e) {
    bubble.classList.add("err");
    bubble.textContent = `Something went wrong: ${e.message}. Please try again.`;
  } finally {
    busy = false;
    send.disabled = false;
    input.focus();
    chat.scrollTop = chat.scrollHeight;
  }
}

form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });

seg.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  seg.querySelectorAll("button").forEach(x => {
    const on = x === b;
    x.classList.toggle("on", on);
    x.setAttribute("aria-checked", String(on));
  });
  source = b.dataset.v;
});

document.getElementById("clearBtn").addEventListener("click", () => {
  history = [];
  chat.innerHTML = "";
  greet();
  suggestBox.style.display = "flex";
});

function greet() {
  addMsg("bot",
    "<p>Welcome. I answer questions about <b>DarGlobal</b> luxury developments " +
    "and <b>Wasalt</b> property listings in Saudi Arabia, using public data — " +
    "every answer links the sources it came from.</p>" +
    "<p>What would you like to know?</p>");
}

async function init() {
  greet();
  try {
    const [s, h] = await Promise.all([
      fetch("/api/suggestions").then(r => r.json()),
      fetch("/api/health").then(r => r.json()),
    ]);
    for (const q of s.suggestions) {
      const b = document.createElement("button");
      b.textContent = q;
      b.onclick = () => ask(q);
      suggestBox.appendChild(b);
    }
    const n = h.corpus?.total_docs ?? "?";
    const live = h.llm_mode !== "mock";
    statusLine.textContent = live
      ? `Online · ${n} documents indexed`
      : `Demo mode · ${n} documents indexed`;
    modeNote.textContent =
      `${live ? h.model : "no API key — showing source excerpts"} · ` +
      "Information may be outdated — always verify on the linked source page.";
  } catch {
    statusLine.textContent = "Backend unreachable";
    modeNote.textContent = "Could not reach the server.";
  }
  input.focus();
}
init();
