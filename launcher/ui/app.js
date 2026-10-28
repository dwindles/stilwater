// Stilwater launcher UI. Talks to the launcher (Bridge.cs) through WebView2 messages: requests
// {id, method, args} answered by {id, result} or {id, error}, and events {event, data}. Opened in
// a plain browser it uses mock.js instead, for previewing the design.
"use strict";

const host = window.chrome && window.chrome.webview;
const waiting = new Map();
const listeners = {};
let nextId = 1;

function api(method, args = {}) {
  if (!host) return window.mock.call(method, args);
  const id = nextId++;
  host.postMessage({ id, method, args });
  return new Promise((resolve, reject) => waiting.set(id, { resolve, reject }));
}
function on(event, fn) { (listeners[event] = listeners[event] || []).push(fn); }
function emit(event, data) { (listeners[event] || []).forEach(fn => fn(data)); }
if (host) {
  host.addEventListener("message", e => {
    const m = e.data;
    if (m.event) return emit(m.event, m.data);
    const w = waiting.get(m.id);
    if (!w) return;
    waiting.delete(m.id);
    m.error ? w.reject(new Error(m.error)) : w.resolve(m.result);
  });
}

// --- helpers
const $ = sel => document.querySelector(sel);
const esc = text => String(text ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
function hue(text) { let h = 0; for (const c of String(text)) h = (h * 31 + c.charCodeAt(0)) % 360; return h; }
function avatar(person, size = "", status = null) {
  const style = person && person.avatar ? `background-image:url(${person.avatar})` : `background-color:hsl(${hue(person?.name)},22%,30%)`;
  const initials = person && !person.avatar ? esc((person.name || "?").replace(/[^A-Za-z0-9]/g, "").slice(0, 2).toUpperCase() || "?") : "";
  return `<span class="avatar ${size}" style="${style}"${status ? ` data-status="${status}"` : ""}>${initials}</span>`;
}
const statusOf = f => f.status === "playing" ? "playing" : f.status === "online" ? "online" : "offline";
function toast(text, kind = "", action = null) {
  const el = document.createElement("div");
  el.className = `toast ${kind}`;
  el.innerHTML = `<p>${esc(text)}</p>`;
  if (action) {
    const b = document.createElement("button");
    b.className = "button small accent";
    b.textContent = action.label;
    b.onclick = () => { action.run(); el.remove(); };
    el.appendChild(b);
  }
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), action ? 15000 : 5000);
}
async function run(task, done) {
  try {
    const result = await task();
    const text = typeof done === "function" ? done(result) : done;
    if (text) toast(text);
    return result;
  }
  catch (e) { toast(e.message, "bad"); }
}
function modal(html, wire) {
  $("#modal-body").innerHTML = html;
  $("#modal").hidden = false;
  const close = () => { $("#modal").hidden = true; };
  $("#modal-body").querySelectorAll("[data-close]").forEach(b => b.onclick = close);
  wire && wire(close);
}
document.addEventListener("click", e => {
  const link = e.target.closest("[data-url]");
  if (link) { e.preventDefault(); api("app.openUrl", { url: link.dataset.url }); }
});

// --- navigation
let page = "play";
function show(name) {
  page = name;
  document.querySelectorAll(".tab").forEach(b => b.classList.toggle("active", b.dataset.page === name));
  document.querySelectorAll(".page").forEach(p => p.hidden = p.id !== `page-${name}`);
  ({ play: renderPlay, friends: renderFriends, mods: loadMods, settings: loadSettings })[name]();
  $(".content").scrollTop = 0;
  pingLoop();
}
document.querySelectorAll(".tab").forEach(b => b.onclick = () => show(b.dataset.page));
$("#me").onclick = () => online.signedIn ? editProfile() : show("friends");

// --- state
let app = { checks: [] };
let online = { signedIn: false, friends: [], requests: [] };
let service = null;

function renderMe() {
  const me = online.signedIn ? { name: online.nick, avatar: online.avatar } : null;
  $("#me-avatar").outerHTML = me ? avatar(me, "small").replace("class=\"avatar", "id=\"me-avatar\" class=\"avatar") : `<span class="avatar small" id="me-avatar">?</span>`;
  $("#me-name").textContent = me ? me.name : "Not signed in";
  $("#me-status").textContent = me ? (online.bio || "Online") : "Sign in";
  const badge = $("#friends-badge");
  badge.hidden = !online.requests.length;
  badge.textContent = online.requests.length;
}

// --- Play
async function loadApp() {
  app = await api("app.state");
  $("#version").textContent = `v${app.version}`;
  $("#upload-button").hidden = !app.staff;
  if (app.art) {
    const art = $("#art"), picture = new Image();
    picture.onload = () => { art.style.backgroundImage = `url("${app.art}")`; art.classList.add("loaded"); };
    picture.src = app.art;
  } else { $("#hero").className = "hero plain"; $("#hero").textContent = "Saints Row 2"; }
  renderPlay();
  api("app.update").then(update => {
    if (!update) return;
    const b = $("#update-button");
    b.textContent = `Update to ${update.version}`;
    b.hidden = false;
  });
  api("app.release").then(release => {
    if (!release) { $("#notes").innerHTML = `<p class="muted">No releases yet.</p>`; return; }
    const lines = release.notes.split(/\r?\n/).map(l => l.trim()).filter(Boolean);
    const items = lines.filter(l => l.startsWith("- ")).map(l => `<li>${esc(l.slice(2))}</li>`).join("");
    const text = lines.filter(l => !l.startsWith("- ") && !/^Install:/.test(l)).map(l => `<p>${esc(l)}</p>`).join("");
    $("#notes").innerHTML = `<p class="when"><b>${esc(release.version)}</b>${release.date ? ` · ${esc(release.date)}` : ""}</p>${text}${items ? `<ul>${items}</ul>` : ""}`;
  });
  api("online.check").then(s => { service = s; renderService(); });
}

function renderPlay() {
  const checks = app.checks || [];
  // The path detail is cut from the left, so the end of the path stays visible.
  $("#checks").innerHTML = checks.map(c => `
    <li class="${c.ok ? "ok" : "no"}" title="${esc(c.detail)}">
      <svg viewBox="0 0 24 24">${c.ok ? '<path d="M5 12.5l4.5 4.5L19 7.5"/>' : '<path d="M6 6l12 12M18 6L6 18"/>'}</svg>
      <b>${esc(c.name)}</b><span><bdi>${esc(c.detail)}</bdi></span>
    </li>`).join("");
  $("#play-button").disabled = !app.canPlay;
  if (!app.canPlay && app.problem) setPlayStatus(app.problem, true);

  const on = online.friends.filter(f => f.status !== "offline");
  $("#online-count").textContent = online.signedIn ? `${on.length} online` : "";
  $("#online-friends").innerHTML = !online.signedIn
    ? `<p class="empty">Sign in to see who's online.</p><button class="button small" onclick="show('friends')">Sign in</button>`
    : on.length ? on.map(f => `
      <div class="friend">${avatar(f, "small", statusOf(f))}
        <div class="row-text"><b>${esc(f.name)}</b><span>${esc(f.activity || "Online")}</span></div>
        <button class="button small" data-invite="${f.id}">Invite</button>
      </div>`).join("")
    : `<p class="empty">${online.friends.length ? "No one's online." : "No friends added yet."}</p>`;
  document.querySelectorAll("[data-invite]").forEach(b => b.onclick = () => invite(+b.dataset.invite));
  renderService();
}

function renderService() {
  if (!service) return;
  $("#service-dot").className = `dot ${service.ok ? "good" : "bad"}`;
  $("#service-name").textContent = app.serviceName || "Server";
  $("#service-text").textContent = service.ok ? `Up · ${service.server}` : `Down: ${service.problem}`;
}

function setPlayStatus(text, bad = false) {
  const s = $("#play-status");
  s.textContent = text;
  s.className = `play-status ${bad ? "bad" : ""}`;
}

$("#play-button").onclick = async () => {
  $("#play-button").disabled = true;
  setPlayStatus("Starting Saints Row 2…");
  document.body.classList.add("launching");
  try {
    const r = await api("app.play");
    setPlayStatus(r.message, !r.ok);
    if (r.ok) setGameRunning(true); else $("#play-button").disabled = false;
  }
  catch (e) { setPlayStatus(e.message, true); $("#play-button").disabled = false; }
  finally { document.body.classList.remove("launching"); }
};
on("gameExited", () => { setPlayStatus("Saints Row 2 closed."); $("#play-button").disabled = !app.canPlay; setGameRunning(false); refreshLog(); });

// While the game runs the launcher sits minimized, so the art and the ping graph stop.
let gameRunning = false;
function setGameRunning(running) {
  gameRunning = running;
  document.body.classList.toggle("game-running", running);
  pingLoop();
}

// --- server ping: a round trip to the server every second, scrolling right to left
const PING_EVERY = 1000, PING_SAMPLES = 60;
const pings = [];
let pingTimer = null;
function pingLoop() {
  const want = page === "play" && !gameRunning && !document.hidden;
  if (want && !pingTimer) { pingTick(); pingTimer = setInterval(pingTick, PING_EVERY); }
  if (!want && pingTimer) { clearInterval(pingTimer); pingTimer = null; }
}
document.addEventListener("visibilitychange", pingLoop);
async function pingTick() {
  let ms = null;
  try { ms = await api("online.ping"); } catch { }
  pings.push(ms);
  if (pings.length > PING_SAMPLES + 1) pings.shift();
  const value = $("#ping-value");
  value.textContent = ms === null ? "No reply" : `${ms} ms`;
  value.className = `ping ${ms === null ? "bad" : ms < 80 ? "good" : ms < 160 ? "fair" : "bad"}`;
  drawPing();
}
// Each new sample is drawn one step past the right edge and the line slides left by one step
// over the next interval, so it moves continuously instead of jumping.
function drawPing() {
  const svg = $("#ping-graph"), w = svg.clientWidth, h = svg.clientHeight;
  if (!w) return;
  const step = w / (PING_SAMPLES - 1);
  const heard = pings.filter(p => p !== null);
  const top = Math.max(40, Math.ceil(Math.max(0, ...heard) * 1.3 / 20) * 20);
  const x = i => ((PING_SAMPLES - (pings.length - 1 - i)) * step).toFixed(1);
  const y = ms => (h - 3 - (ms / top) * (h - 8)).toFixed(1);
  let line = "", area = "", lost = "";
  let run = [];
  const flush = () => {
    if (run.length) {
      const points = run.map(i => `${x(i)},${y(pings[i])}`).join(" ");
      line += `<polyline class="line" points="${points}"/>`;
      area += `<polygon class="area" points="${x(run[0])},${h} ${points} ${x(run[run.length - 1])},${h}"/>`;
    }
    run = [];
  };
  pings.forEach((ms, i) => {
    if (ms === null) { flush(); lost += `<rect class="lost" x="${(x(i) - step / 2).toFixed(1)}" y="0" width="${step.toFixed(1)}" height="${h}"/>`; }
    else run.push(i);
  });
  flush();
  svg.setAttribute("viewBox", `0 0 ${w} ${h}`);
  svg.innerHTML = `<line class="grid" x1="0" x2="${w}" y1="${y(top / 2)}" y2="${y(top / 2)}"/><g>${lost}${area}${line}</g>`;
  const g = svg.lastChild;
  g.style.transition = "none";
  g.style.transform = "translateX(0)";
  g.getBoundingClientRect();
  g.style.transition = `transform ${PING_EVERY}ms linear`;
  g.style.transform = `translateX(${-step}px)`;
}
on("progress", text => setPlayStatus(text));

$("#update-button").onclick = () => modal(`
  <h2>Update Stilwater</h2>
  <p class="muted">${esc($("#update-button").textContent)}. The launcher closes, installs the update and opens again. Close Saints Row 2 first.</p>
  <div class="modal-buttons"><button class="button ghost" data-close>Not now</button><button class="button accent" id="do-update">Update</button></div>`,
  close => $("#do-update").onclick = () => { close(); setPlayStatus("Downloading the update…"); run(() => api("app.installUpdate")); });

$("#upload-button").onclick = async () => {
  const version = await api("app.nextVersion");
  modal(`
    <h2>Upload a release</h2>
    <p class="muted small">Builds everything, commits and pushes the repo, and publishes it on GitHub. Players get it from the Update button.</p>
    <div class="field"><label>Version</label><input class="input" id="rel-version" value="${esc(version)}"></div>
    <div class="field"><label>What's new</label><textarea class="input" id="rel-notes" placeholder="- One change per line"></textarea></div>
    <div class="modal-buttons"><button class="button ghost" data-close>Cancel</button><button class="button accent" id="do-upload">Upload</button></div>`,
    close => $("#do-upload").onclick = () => {
      close();
      run(() => api("app.upload", { version: $("#rel-version").value.trim(), notes: $("#rel-notes").value.trim() }),
          "Uploading: the release window shows how it goes.");
    });
};

async function refreshLog() {
  const text = await api("app.log");
  if (text) { $("#log").textContent = text; $("#log").scrollTop = 1e9; }
}

// --- Friends
async function invite(id) {
  const f = online.friends.find(x => x.id === id);
  await run(() => api("online.invite", { id }), `Invited ${f ? f.name : "your friend"}. Start the game and host co-op.`);
}

function renderFriends() {
  renderMe();
  if (!online.signedIn) return renderSignIn();
  $("#account").innerHTML = `
    <div class="list profile">
      <button class="avatar-edit" id="pick-avatar" title="Change picture">${avatar({ name: online.nick, avatar: online.avatar }, "big")}</button>
      <div class="row-text"><b>${esc(online.nick)}</b>${online.bio ? `<span>${esc(online.bio)}</span>` : ""}</div>
      <button class="button" id="edit-profile">Edit profile</button>
      <button class="button ghost" id="sign-out">Sign out</button>
    </div>`;
  $("#pick-avatar").onclick = pickAvatar;
  $("#edit-profile").onclick = editProfile;
  $("#sign-out").onclick = () => run(() => api("online.signOut"));

  const requests = online.requests.map(r => `
    <div class="row">${avatar(r, "small")}
      <div class="row-text"><b>${esc(r.name)}</b></div>
      <div class="actions"><button class="button small accent" data-accept="${r.id}">Accept</button>
        <button class="button small ghost" data-ignore="${r.id}">Ignore</button></div>
    </div>`).join("");
  const sorted = [...online.friends].sort((a, b) => (a.status === "offline") - (b.status === "offline") || a.name.localeCompare(b.name));
  $("#friends-body").innerHTML = `
    ${requests ? `<section class="block"><div class="block-head"><h2>Requests</h2></div><div class="list">${requests}</div></section>` : ""}
    <section class="block">
      <div class="block-head"><h2>Friends</h2>
        <div class="add-friend"><input class="input" id="add-nick" placeholder="Add by nick" maxlength="20"><button class="button small" id="add-send">Send request</button></div>
      </div>
      ${sorted.length ? `<div class="list">${sorted.map(f => `
        <div class="row">${avatar(f, "", statusOf(f))}
          <div class="row-text"><b>${esc(f.name)}</b><span>${esc(f.status === "offline" ? "Offline" : f.activity || "Online")}</span></div>
          <div class="actions">${f.status !== "offline" ? `<button class="button small" data-invite="${f.id}">Invite</button>` : ""}
            <button class="button small ghost" data-remove="${f.id}">Remove</button></div>
        </div>`).join("")}</div>` : `<p class="empty">No friends added yet.</p>`}
    </section>`;
  $("#add-send").onclick = () => {
    const nick = $("#add-nick").value.trim();
    if (nick) run(() => api("online.addFriend", { nick }), `Friend request sent to ${nick}.`).then(() => $("#add-nick") && ($("#add-nick").value = ""));
  };
  $("#add-nick").onkeydown = e => { if (e.key === "Enter") $("#add-send").click(); };
  document.querySelectorAll("[data-accept]").forEach(b => b.onclick = () => run(() => api("online.accept", { id: +b.dataset.accept })));
  document.querySelectorAll("[data-ignore]").forEach(b => b.onclick = () => run(() => api("online.ignore", { id: +b.dataset.ignore })));
  document.querySelectorAll("[data-invite]").forEach(b => b.onclick = () => invite(+b.dataset.invite));
  document.querySelectorAll("[data-remove]").forEach(b => b.onclick = () => {
    const f = online.friends.find(x => x.id === +b.dataset.remove);
    modal(`<h2>Remove ${esc(f.name)}?</h2><p class="muted">You can add each other again later.</p>
      <div class="modal-buttons"><button class="button ghost" data-close>Cancel</button><button class="button danger" id="do-remove">Remove</button></div>`,
      close => $("#do-remove").onclick = () => { close(); run(() => api("online.remove", { id: f.id })); });
  });
}

async function renderSignIn() {
  const saved = await api("online.savedLogin");
  $("#account").innerHTML = `
    <section class="block">
      <div class="block-head"><h2>Sign in to ${esc(app.serviceName || "Stilwater Online")}</h2></div>
      <div class="list sign-in">
        <div class="field"><label>Nick</label><input class="input" id="si-nick" maxlength="20" value="${esc(saved.nick)}"></div>
        <div class="field"><label>Email</label><input class="input" id="si-email" value="${esc(saved.email)}"></div>
        <div class="field"><label>Password</label><input class="input" id="si-password" type="password" placeholder="${saved.hasPassword ? "Saved" : ""}"></div>
        <div class="buttons">
          <button class="button accent" id="si-go">Sign in</button>
          <button class="button" id="si-create">Create account</button>
          <span class="muted small">The game uses this account too.</span>
        </div>
      </div>
    </section>`;
  $("#friends-body").innerHTML = "";
  const login = () => ({ nick: $("#si-nick").value.trim(), email: $("#si-email").value.trim(), password: $("#si-password").value });
  $("#si-go").onclick = () => run(() => api("online.signIn", login()), "Signed in.");
  $("#si-create").onclick = () => run(() => api("online.createAccount", login()), "Account created and signed in.");
  $("#si-password").onkeydown = e => { if (e.key === "Enter") $("#si-go").click(); };
}

function pickAvatar() { run(() => api("profile.pickAvatar"), picked => picked ? "Profile picture updated." : null); }
function editProfile() {
  modal(`
    <h2>Your profile</h2>
    <p class="muted small">Friends see your picture and bio in their launcher.</p>
    <div style="display:flex;align-items:center;gap:16px;margin-top:16px">${avatar({ name: online.nick, avatar: online.avatar }, "big")}
      <div style="display:flex;flex-direction:column;gap:8px"><button class="button" id="m-pick">Choose picture…</button>
      ${online.avatar ? `<button class="button ghost small" id="m-clear">Remove picture</button>` : ""}</div></div>
    <div class="field"><label>Bio</label><input class="input" id="m-bio" maxlength="120" value="${esc(online.bio || "")}" placeholder="A line about you"></div>
    <div class="modal-buttons"><button class="button ghost" data-close>Cancel</button><button class="button accent" id="m-save">Save</button></div>`,
    close => {
      $("#m-pick").onclick = () => { close(); pickAvatar(); };
      if ($("#m-clear")) $("#m-clear").onclick = () => { close(); run(() => api("profile.clearAvatar"), "Picture removed."); };
      $("#m-save").onclick = () => { close(); run(() => api("profile.setBio", { bio: $("#m-bio").value.trim() }), "Profile saved."); };
    });
}

on("online", data => { online = data; renderMe(); if (page === "friends") renderFriends(); if (page === "play") renderPlay(); });
on("notice", text => toast(text, "bad"));
on("invite", data => {
  toast(`${data.name} invited you to co-op.`, "invite", { label: "Play", run: () => { show("play"); $("#play-button").click(); } });
});

// --- Mods
let mods = null;
async function loadMods() {
  mods = await api("mods.list");
  renderMods();
  $("#mods-code").textContent = "…";
  api("mods.code").then(code => $("#mods-code").textContent = code);
}
function renderMods() {
  const group = (title, list) => list.length ? `
    <div class="section"><h2>${title}</h2><span>${list.filter(m => m.enabled).length} of ${list.length} on</span></div>
    <div class="list">${list.map(m => `
      <div class="row mod ${m.enabled ? "" : "off"}">
        <div class="row-text"><b>${esc(m.display)}</b><span>${m.files} files · ${m.mb.toFixed(1)} MB</span></div>
        <label class="switch"><input type="checkbox" data-mod="${esc(m.name)}" ${m.enabled ? "checked" : ""}><span></span></label>
      </div>`).join("")}</div>` : "";
  $("#mods-body").innerHTML =
    group("Stilwater", mods.mods.filter(m => !m.core)) +
    group("Juiced Patch", mods.mods.filter(m => m.core));
  document.querySelectorAll("[data-mod]").forEach(box => box.onchange = async () => {
    const name = box.dataset.mod;
    try {
      await api("mods.set", { name, enabled: box.checked });
      mods.mods.find(m => m.name === name).enabled = box.checked;
      renderMods();
      api("mods.code").then(code => $("#mods-code").textContent = code);
    } catch (e) { box.checked = !box.checked; toast(e.message, "bad"); }
  });
}
$("#open-mods").onclick = () => api("app.openFolder", { which: "mods" });
$("#copy-code").onclick = () => { navigator.clipboard.writeText($("#mods-code").textContent); toast("Mods code copied."); };

// --- Settings
let settings = null, changes = {};
async function loadSettings() {
  settings = await api("settings.list");
  changes = {};
  renderSettings();
}
function control(item) {
  const v = item.id in changes ? changes[item.id] : item.value;
  switch (item.kind) {
    case "toggle": return `<label class="switch"><input type="checkbox" data-set="${item.id}" ${v === "1" ? "checked" : ""}><span></span></label>`;
    case "number": return `<div class="range"><input type="range" data-set="${item.id}" min="${item.min}" max="${item.max}" step="${item.step}" value="${esc(v)}"><output>${(+v).toFixed(item.decimals)}</output></div>`;
    case "choice": return `<select class="select" data-set="${item.id}">${item.choices.map(c => `<option value="${esc(c.value)}" ${c.value === v ? "selected" : ""}>${esc(c.text)}</option>`).join("")}</select>`;
    case "button": return `<button class="button" data-action="${item.id}">${esc(item.value)}</button>`;
    default: return `<input class="input" data-set="${item.id}" value="${esc(v)}">`;
  }
}
function renderSettings() {
  $("#settings-body").innerHTML = settings.sections.map(s => `
    <section class="settings-section"><h2>${esc(s.title)}</h2><div class="list">${s.items.map(item => `
      <div class="row"><div class="row-text"><b>${esc(item.label)}</b>${item.help ? `<span>${esc(item.help)}</span>` : ""}</div>
        <div class="control">${control(item)}</div></div>`).join("")}</div></section>`).join("");
  document.querySelectorAll("[data-set]").forEach(input => {
    const update = () => {
      const item = settings.sections.flatMap(s => s.items).find(i => i.id === input.dataset.set);
      const value = input.type === "checkbox" ? (input.checked ? "1" : "0") : input.value;
      if (input.type === "range") input.nextElementSibling.textContent = (+value).toFixed(item.decimals);
      if (value === item.value) delete changes[item.id]; else changes[item.id] = value;
      $("#save-bar").hidden = !Object.keys(changes).length;
    };
    input.oninput = update;
    input.onchange = update;
  });
  document.querySelectorAll("[data-action]").forEach(b => b.onclick = () => run(() => api("settings.action", { id: b.dataset.action }), r => r));
  $("#save-bar").hidden = !Object.keys(changes).length;
}
$("#save").onclick = () => run(async () => { await api("settings.save", { values: changes }); await loadSettings(); }, "Saved. Applies next time the game starts.");
$("#discard").onclick = () => { changes = {}; renderSettings(); };

// --- start
async function start() {
  if (!host) await new Promise(resolve => { const s = document.createElement("script"); s.src = "mock.js"; s.onload = resolve; document.head.appendChild(s); });
  online = await api("online.status");
  renderMe();
  await loadApp();
  refreshLog();
  const first = location.hash.slice(1);
  if (["friends", "mods", "settings"].includes(first)) show(first);
  else pingLoop();
}
start();
