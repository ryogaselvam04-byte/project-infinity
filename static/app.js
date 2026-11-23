const $ = s => document.querySelector(s), $$ = s => document.querySelectorAll(s);
async function api(url, o = {}) {
  if (o.body && !(o.body instanceof FormData)) { o.headers = { "Content-Type": "application/json" }; o.body = JSON.stringify(o.body); }
  const r = await fetch(url, o), d = await r.json().catch(() => ({}));
  if (!r.ok) { if (r.status === 401 && url !== "/api/login") showAuth(); throw new Error(d.error || "Something went wrong"); }
  return d;
}
const busy = (b, on, t) => { b.disabled = on; if (t) b.textContent = on ? "Working..." : t; };

// ---------- auth ----------
let reg = false;
const showAuth = () => { $("#app").classList.add("hidden"); $("#auth").classList.remove("hidden"); };
const showApp = name => { $("#auth").classList.add("hidden"); $("#app").classList.remove("hidden"); $("#uname").textContent = "👤 " + name; loadChat(); };
function setMode() {
  $$(".reg-only").forEach(e => e.style.display = reg ? "" : "none");
  $("#a-btn").textContent = reg ? "Create Account" : "Login";
  $("#a-toggle").textContent = reg ? "Have an account? Login" : "New here? Create account";
}
$("#a-toggle").onclick = () => { reg = !reg; setMode(); };
$("#a-btn").onclick = async () => {
  try {
    const d = await api(reg ? "/api/register" : "/api/login", { method: "POST", body: { name: $("#a-name").value, email: $("#a-email").value, password: $("#a-pass").value } });
    $("#a-err").textContent = ""; showApp(d.name);
  } catch (e) { $("#a-err").textContent = e.message; }
};
$("#logout").onclick = async () => { await api("/api/logout", { method: "POST" }); $("#msgs").innerHTML = ""; showAuth(); };
setMode();
api("/api/me").then(d => showApp(d.name)).catch(() => showAuth());

// ---------- tabs ----------
$$("nav button").forEach(b => b.onclick = () => {
  $$("nav button").forEach(x => x.classList.remove("active")); b.classList.add("active");
  $$(".panel").forEach(p => p.classList.remove("show")); $("#" + b.dataset.tab).classList.add("show");
  if (b.dataset.tab === "notes") loadNotes();
  if (b.dataset.tab === "dash") loadDash();
});

// ---------- chat + voice ----------
let speakOn = false;
function addMsg(text, who) {
  const m = document.createElement("div"); m.className = "msg " + who; m.textContent = text;
  $("#msgs").append(m); $("#msgs").scrollTop = 1e9; return m;
}
async function loadChat() {
  if ($("#msgs").children.length) return;
  try { (await api("/api/chat/history")).forEach(h => { addMsg(h.user_message, "u"); addMsg(h.ai_response, "a"); }); } catch {}
  if (!$("#msgs").children.length) addMsg("Hi! I'm Infinity. Ask me anything, or tap 🎤 to talk.", "a");
}
async function send() {
  const t = $("#c-in").value.trim(); if (!t) return;
  $("#c-in").value = ""; addMsg(t, "u");
  const w = addMsg("", "a"); w.innerHTML = '<span class="dots"><span></span><span></span><span></span></span>';
  try {
    const d = await api("/api/chat", { method: "POST", body: { message: t } });
    w.textContent = d.reply;
    if (speakOn) { speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(d.reply)); }
  } catch (e) { w.textContent = "⚠️ " + e.message; }
  $("#msgs").scrollTop = 1e9;
}
$("#c-send").onclick = send;
$("#c-in").onkeydown = e => e.key === "Enter" && send();
$("#speak").onclick = () => { speakOn = !speakOn; $("#speak").textContent = speakOn ? "🔊" : "🔇"; if (!speakOn) speechSynthesis.cancel(); };
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
$("#mic").onclick = () => {
  if (!SR) return alert("Voice input works in Chrome or Edge.");
  const r = new SR(); r.lang = "en-IN";
  r.onstart = () => $("#mic").classList.add("on");
  r.onend = () => $("#mic").classList.remove("on");
  r.onresult = e => { $("#c-in").value = e.results[0][0].transcript; send(); };
  r.start();
};

// ---------- analyzer ----------
const drop = $("#drop"), file = $("#file");
file.onchange = () => $("#dtxt").textContent = file.files[0] ? "📎 " + file.files[0].name : "📎 Click or drop a PDF / image here";
drop.ondragover = e => { e.preventDefault(); drop.classList.add("over"); };
drop.ondragleave = () => drop.classList.remove("over");
drop.ondrop = e => { e.preventDefault(); drop.classList.remove("over"); file.files = e.dataTransfer.files; file.onchange(); };
function show(el, text) { el.classList.remove("fade"); void el.offsetWidth; el.textContent = text; el.classList.add("fade"); }
$("#an-btn").onclick = async () => {
  if (!file.files[0]) return show($("#an-out"), "Please choose a file first.");
  const fd = new FormData(); fd.append("file", file.files[0]);
  busy($("#an-btn"), true, "Analyze");
  try { show($("#an-out"), (await api("/api/analyze", { method: "POST", body: fd })).result); }
  catch (e) { show($("#an-out"), "⚠️ " + e.message); }
  busy($("#an-btn"), false, "Analyze");
};

// ---------- code checker ----------
$("#code-btn").onclick = async () => {
  busy($("#code-btn"), true, "Check Code");
  try { show($("#code-out"), (await api("/api/code", { method: "POST", body: { code: $("#code-in").value, language: $("#lang").value } })).result); }
  catch (e) { show($("#code-out"), "⚠️ " + e.message); }
  busy($("#code-btn"), false, "Check Code");
};

// ---------- notes ----------
let editId = null;
async function loadNotes() {
  const list = $("#n-list"); list.innerHTML = "";
  (await api("/api/notes")).forEach(n => {
    const d = document.createElement("div"); d.className = "note";
    const t = document.createElement("b"), p = document.createElement("p"), act = document.createElement("div");
    t.textContent = n.title; p.textContent = n.content;
    const ed = document.createElement("button"), del = document.createElement("button");
    ed.className = del.className = "ghost"; ed.textContent = "Edit"; del.textContent = "Delete";
    ed.onclick = () => { editId = n.note_id; $("#n-title").value = n.title; $("#n-body").value = n.content; $("#n-save").textContent = "Update Note"; };
    del.onclick = async () => { await api("/api/notes/" + n.note_id, { method: "DELETE" }); loadNotes(); };
    act.append(ed, del); d.append(t, p, act); list.append(d);
  });
}
$("#n-save").onclick = async () => {
  const body = { title: $("#n-title").value, content: $("#n-body").value };
  try {
    await api(editId ? "/api/notes/" + editId : "/api/notes", { method: editId ? "PUT" : "POST", body });
    editId = null; $("#n-title").value = $("#n-body").value = ""; $("#n-save").textContent = "Save Note"; loadNotes();
  } catch (e) { alert(e.message); }
};

// ---------- dashboard ----------
async function loadDash() {
  const d = await api("/api/dashboard");
  let n = 0; const step = Math.max(1, Math.ceil(d.total / 30));
  const iv = setInterval(() => { n = Math.min(d.total, n + step); $("#total").textContent = n; if (n >= d.total) clearInterval(iv); }, 30);
  const max = Math.max(1, ...Object.values(d.tools)), bars = $("#bars"); bars.innerHTML = "";
  Object.entries(d.tools).forEach(([k, v]) => {
    bars.insertAdjacentHTML("beforeend", `<div class="bar"><span>${k}</span><i data-w="${v / max * 100}"></i><b>${v}</b></div>`);
  });
  setTimeout(() => $$(".bar i").forEach(i => i.style.width = i.dataset.w + "%"), 50);
  const ul = $("#recent"); ul.innerHTML = "";
  d.recent.forEach((r, i) => { const li = document.createElement("li"); li.style.animationDelay = i * 60 + "ms"; li.textContent = r.tool_name + " — " + (r.action || ""); const s = document.createElement("small"); s.textContent = "  " + r.created_at; li.append(s); ul.append(li); });
  if (!d.recent.length) ul.innerHTML = "<li>No activity yet. Try the other tools!</li>";
}
