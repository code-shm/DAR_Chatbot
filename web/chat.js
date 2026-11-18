const chat = document.getElementById("chat");
const form = document.getElementById("form");
const input = document.getElementById("input");
const send = document.getElementById("send");
const suggestBox = document.getElementById("suggest");
const modeNote = document.getElementById("modeNote");
const seg = document.getElementById("sourceSeg");

let history = [];   // [{role, content}]
let source = "both";
let busy = false;

function el(tag, cls, html) {
  const e = document.createElement(tag);
  if (cls) e.className = cls;
  if (html !== undefined) e.innerHTML = html;
  return e;
}
const esc = (s) => s.replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

// minimal, safe markdown: bold + [n] citation styling + newlines
function md(s) {
  return esc(s)
    .replace(/\*\*(.+?)\*\*/g, "<b>$1</b>")
    .replace(/\[(\d+)\]/g, '<b>[$1]</b>');
}

function addMsg(role, html, cls = "") {
  const m = el("div", `msg ${role} ${cls}`);
  m.innerHTML = html;
  chat.appendChild(m);
  chat.scrollTop = chat.scrollHeight;
  return m;
}

function addSources(msgEl, sources) {
  if (!sources || !sources.length) return;
  const box = el("div", "srcs");
  for (const s of sources) {
    const a = el("a");
    a.href = s.url; a.target = "_blank"; a.rel = "noopener";
    a.innerHTML = `<span class="tag">[${s.n}] ${s.source === "darglobal" ? "DarGlobal" : "Wasalt"}</span> ${esc((s.title || s.url).slice(0, 60))}`;
    box.appendChild(a);
  }
  msgEl.appendChild(box);
}

async function ask(q) {
  if (busy || !q.trim()) return;
  busy = true; send.disabled = true; suggestBox.style.display = "none";
  addMsg("user", esc(q));
  input.value = "";
  const typing = addMsg("bot", '<span class="typing"><i></i><i></i><i></i></span>');
  try {
    const r = await fetch("/api/chat", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({message: q, history: history.slice(-10), source}),
    });
    if (!r.ok) throw new Error((await r.json().catch(() => ({}))).detail || `HTTP ${r.status}`);
    const data = await r.json();
    typing.innerHTML = md(data.answer);
    addSources(typing, data.sources);
    history.push({role: "user", content: q}, {role: "assistant", content: data.answer});
  } catch (e) {
    typing.classList.add("err");
    typing.textContent = `Something went wrong: ${e.message}. Please try again.`;
  } finally {
    busy = false; send.disabled = false; input.focus();
    chat.scrollTop = chat.scrollHeight;
  }
}

form.addEventListener("submit", (e) => { e.preventDefault(); ask(input.value); });

seg.addEventListener("click", (e) => {
  const b = e.target.closest("button"); if (!b) return;
  seg.querySelectorAll("button").forEach(x => x.classList.toggle("on", x === b));
  source = b.dataset.v;
});

document.getElementById("clearBtn").addEventListener("click", () => {
  history = []; chat.innerHTML = ""; greet(); suggestBox.style.display = "flex";
});

function greet() {
  addMsg("bot",
    "Welcome! I answer questions about <b>DarGlobal</b> luxury developments and " +
    "<b>Wasalt</b> property listings in Saudi Arabia, using public data with source " +
    "links. What would you like to know?");
}

async function init() {
  greet();
  try {
    const [s, h] = await Promise.all([
      fetch("/api/suggestions").then(r => r.json()),
      fetch("/api/health").then(r => r.json()),
    ]);
    for (const q of s.suggestions) {
      const b = el("button", "", esc(q));
      b.onclick = () => ask(q);
      suggestBox.appendChild(b);
    }
    const n = h.corpus?.total_docs ?? "?";
    modeNote.textContent =
      `Knowledge base: ${n} documents · LLM: ${h.llm_mode === "mock"
        ? "demo mode (no API key yet)" : h.model} · Information may be outdated — always verify on the linked source page.`;
  } catch { modeNote.textContent = "Backend unreachable."; }
  input.focus();
}
init();
