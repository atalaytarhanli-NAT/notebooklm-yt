const TOKEN_KEY = "nlm_yt_token";
const $ = (s) => document.querySelector(s);
const $$ = (s) => document.querySelectorAll(s);

let token = localStorage.getItem(TOKEN_KEY) || "";
const selected = new Map(); // url -> { title, channel, thumbnail }
let notebooksCache = [];
let currentNotebookId = null;
let pollers = new Map(); // artifact_id -> intervalId

// ---------- helpers ----------
function showToast(msg, ms = 2500) {
  const t = $("#toast");
  t.textContent = msg;
  t.classList.remove("hidden");
  clearTimeout(showToast._h);
  showToast._h = setTimeout(() => t.classList.add("hidden"), ms);
}

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", Authorization: `Bearer ${token}`, ...(opts.headers || {}) };
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401) {
    showAuth("Token geçersiz");
    throw new Error("unauthorized");
  }
  const ct = res.headers.get("content-type") || "";
  if (!res.ok) {
    let detail = res.statusText;
    if (ct.includes("application/json")) {
      try { detail = (await res.json()).detail || detail; } catch {}
    }
    throw new Error(detail);
  }
  return ct.includes("application/json") ? res.json() : res.blob();
}

function fmtViews(n) {
  if (!n && n !== 0) return "—";
  if (n >= 1_000_000) return (n / 1_000_000).toFixed(1).replace(".0", "") + "M";
  if (n >= 1_000) return (n / 1_000).toFixed(1).replace(".0", "") + "K";
  return String(n);
}

// ---------- auth ----------
function showAuth(err) {
  $("#auth-screen").classList.remove("hidden");
  if (err) {
    const e = $("#token-error");
    e.textContent = err;
    e.classList.remove("hidden");
  }
}
function hideAuth() {
  $("#auth-screen").classList.add("hidden");
  $("#token-error").classList.add("hidden");
}

$("#token-submit").addEventListener("click", async () => {
  const v = $("#token-input").value.trim();
  if (!v) return;
  token = v;
  try {
    const r = await fetch("/api/health", { headers: { Authorization: `Bearer ${token}` } });
    if (!r.ok) throw new Error();
    // sanity check token via /api/notebooks
    const nb = await fetch("/api/notebooks", { headers: { Authorization: `Bearer ${token}` } });
    if (nb.status === 401) throw new Error("Token reddedildi");
    localStorage.setItem(TOKEN_KEY, token);
    hideAuth();
    init();
  } catch (e) {
    showAuth(e.message || "Doğrulama başarısız");
  }
});

$("#token-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") $("#token-submit").click();
});

$("#logout").addEventListener("click", () => {
  localStorage.removeItem(TOKEN_KEY);
  token = "";
  showAuth();
});

// ---------- tabs ----------
function activateTab(name) {
  $$(".tab-btn").forEach((b) => {
    const active = b.dataset.tab === name;
    b.classList.toggle("bg-brand-600", active);
    b.classList.toggle("text-white", active);
    b.classList.toggle("text-slate-600", !active);
    b.classList.toggle("hover:bg-slate-100", !active);
  });
  $$("[data-tab-panel]").forEach((p) => p.classList.toggle("hidden", p.dataset.tabPanel !== name));
  if (name === "notebook" || name === "generate") loadNotebooks();
  if (name === "generate" && currentNotebookId) loadArtifacts(currentNotebookId);
}
$$(".tab-btn").forEach((b) => b.addEventListener("click", () => activateTab(b.dataset.tab)));

// ---------- search ----------
async function doSearch() {
  const q = $("#search-input").value.trim();
  if (!q) return;
  const withDates = $("#search-dates").checked;
  $("#search-status").textContent = "Aranıyor…";
  $("#search-results").innerHTML = "";
  const t0 = performance.now();
  try {
    const data = await api(`/api/youtube/search?q=${encodeURIComponent(q)}&n=12&dates=false`);
    const dt = ((performance.now() - t0) / 1000).toFixed(1);
    $("#search-status").textContent = `${data.count} sonuç · ${dt}s`;
    renderResults(data.results);
    if (withDates) {
      enrichDatesInBackground(data.results);
    }
  } catch (e) {
    $("#search-status").textContent = "Hata: " + e.message;
  }
}

// Fetch dates in background, throttled, update DOM as they arrive
async function enrichDatesInBackground(items) {
  const concurrency = 4;
  const queue = items.filter((it) => it.id && !it.upload_date).map((it) => it.id);
  const totalToFetch = queue.length;
  let done = 0;
  $("#search-status").textContent = `${items.length} sonuç · tarihler yükleniyor…`;

  let consecutiveFails = 0;
  let aborted = false;

  async function worker() {
    while (queue.length && !aborted) {
      const id = queue.shift();
      try {
        const r = await api(`/api/youtube/dates/${encodeURIComponent(id)}`);
        if (r.upload_date) {
          consecutiveFails = 0;
          const el = document.querySelector(`[data-video-date="${id}"]`);
          if (el) {
            el.textContent = r.upload_date;
            el.classList.remove("text-slate-300");
            el.classList.add("text-slate-500", "font-medium");
          }
        } else {
          consecutiveFails++;
        }
      } catch {
        consecutiveFails++;
      }
      done++;
      if (consecutiveFails >= 5) {
        aborted = true;
        $("#search-status").textContent = `${items.length} sonuç · tarihler alınamadı`;
        return;
      }
      $("#search-status").textContent = `${items.length} sonuç · tarih ${done}/${totalToFetch}`;
    }
  }
  const workers = Array.from({ length: Math.min(concurrency, queue.length) }, () => worker());
  await Promise.all(workers);
  if (!aborted) $("#search-status").textContent = `${items.length} sonuç`;
}
$("#search-btn").addEventListener("click", doSearch);
$("#search-input").addEventListener("keydown", (e) => {
  if (e.key === "Enter") doSearch();
});

function renderResults(items) {
  const ul = $("#search-results");
  ul.innerHTML = "";
  for (const it of items) {
    const li = document.createElement("li");
    const checked = selected.has(it.url) ? "checked" : "";
    li.className = "rounded-xl border border-slate-200 bg-white p-3";
    li.innerHTML = `
      <label class="flex gap-3 cursor-pointer">
        <input type="checkbox" data-url="${it.url}" ${checked} class="mt-1 h-5 w-5 shrink-0 rounded border-slate-300 text-brand-600 focus:ring-brand-500" />
        <div class="flex-1 min-w-0">
          <div class="flex gap-3">
            <div class="video-thumb w-28 shrink-0 overflow-hidden rounded-lg bg-slate-100">
              ${it.thumbnail ? `<img src="${it.thumbnail}" class="h-full w-full object-cover" />` : ""}
            </div>
            <div class="min-w-0 flex-1">
              <div class="line-clamp-2 text-sm font-medium">${escapeHtml(it.title || "")}</div>
              <div class="mt-1 truncate text-xs text-slate-500">${escapeHtml(it.channel || "")}</div>
              <div class="mt-1 text-xs text-slate-500">${fmtViews(it.view_count)} görüntülenme · ${it.duration_string || "—"} · <span data-video-date="${it.id || ""}" class="${it.upload_date ? "text-slate-500 font-medium" : "text-slate-300"}">${it.upload_date || "—"}</span></div>
            </div>
          </div>
        </div>
      </label>`;
    li.querySelector("input").addEventListener("change", (e) => {
      if (e.target.checked) selected.set(it.url, it);
      else selected.delete(it.url);
      updateFab();
    });
    ul.appendChild(li);
  }
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function updateFab() {
  const n = selected.size;
  $("#fab").classList.toggle("hidden", n === 0);
  $("#fab-count").textContent = String(n);
}

// ---------- send selected to notebook ----------
$("#send-btn").addEventListener("click", async () => {
  await loadNotebooks();
  const sel = $("#pick-nb-select");
  sel.innerHTML = notebooksCache.length
    ? notebooksCache.map((n) => `<option value="${n.id}">${escapeHtml(n.title || "(başlıksız)")}</option>`).join("")
    : '<option value="">— defter yok, yeni oluştur —</option>';
  $("#pick-nb-modal").classList.remove("hidden");
  $("#pick-nb-modal").classList.add("flex");
});

$("#pick-nb-cancel").addEventListener("click", () => {
  $("#pick-nb-modal").classList.add("hidden");
  $("#pick-nb-modal").classList.remove("flex");
});

$("#pick-nb-create").addEventListener("click", async () => {
  const title = $("#pick-nb-new").value.trim();
  if (!title) return;
  try {
    const r = await api("/api/notebooks", { method: "POST", body: JSON.stringify({ title }) });
    notebooksCache.unshift(r.notebook);
    const sel = $("#pick-nb-select");
    const opt = document.createElement("option");
    opt.value = r.notebook.id;
    opt.textContent = r.notebook.title;
    opt.selected = true;
    sel.prepend(opt);
    $("#pick-nb-new").value = "";
    showToast("Defter oluşturuldu");
  } catch (e) {
    showToast("Hata: " + e.message);
  }
});

$("#pick-nb-confirm").addEventListener("click", async () => {
  const nbId = $("#pick-nb-select").value;
  if (!nbId) {
    showToast("Defter seç");
    return;
  }
  const urls = Array.from(selected.keys());
  $("#pick-nb-confirm").disabled = true;
  $("#pick-nb-confirm").textContent = "Ekleniyor…";
  try {
    const r = await api("/api/sources/add", {
      method: "POST",
      body: JSON.stringify({ notebook_id: nbId, urls }),
    });
    showToast(`${r.added.length} eklendi${r.errors.length ? `, ${r.errors.length} hata` : ""}`);
    selected.clear();
    updateFab();
    $("#pick-nb-modal").classList.add("hidden");
    $("#pick-nb-modal").classList.remove("flex");
    currentNotebookId = nbId;
    activateTab("generate");
    $("#gen-notebook").value = nbId;
    loadArtifacts(nbId);
  } catch (e) {
    showToast("Hata: " + e.message);
  } finally {
    $("#pick-nb-confirm").disabled = false;
    $("#pick-nb-confirm").textContent = "Ekle";
  }
});

// ---------- notebooks ----------
async function loadNotebooks() {
  try {
    const r = await api("/api/notebooks");
    notebooksCache = r.notebooks || [];
    renderNotebookList();
    renderNotebookSelect();
  } catch (e) {
    showToast("Defter listesi alınamadı: " + e.message);
  }
}
$("#reload-nb").addEventListener("click", loadNotebooks);

function renderNotebookList() {
  const ul = $("#notebook-list");
  if (!notebooksCache.length) {
    ul.innerHTML = '<li class="text-slate-400">Henüz defter yok.</li>';
    return;
  }
  ul.innerHTML = "";
  for (const n of notebooksCache) {
    const li = document.createElement("li");
    li.className = "flex items-center justify-between rounded-lg border border-slate-200 px-3 py-2";
    li.innerHTML = `
      <div class="min-w-0 flex-1">
        <div class="truncate font-medium">${escapeHtml(n.title || "(başlıksız)")}</div>
        <div class="truncate text-xs text-slate-400">${n.id}</div>
      </div>
      <button class="text-xs text-brand-600 hover:underline">Aç →</button>`;
    li.querySelector("button").addEventListener("click", () => {
      currentNotebookId = n.id;
      activateTab("generate");
      $("#gen-notebook").value = n.id;
      loadArtifacts(n.id);
      loadSources(n.id);
    });
    ul.appendChild(li);
  }
}

function renderNotebookSelect() {
  const sel = $("#gen-notebook");
  const cur = sel.value;
  sel.innerHTML = '<option value="">— Defter seç —</option>' +
    notebooksCache.map((n) => `<option value="${n.id}">${escapeHtml(n.title || "(başlıksız)")}</option>`).join("");
  if (cur) sel.value = cur;
}

$("#new-nb-btn").addEventListener("click", async () => {
  const title = $("#new-nb-title").value.trim();
  if (!title) return;
  try {
    await api("/api/notebooks", { method: "POST", body: JSON.stringify({ title }) });
    $("#new-nb-title").value = "";
    showToast("Defter oluşturuldu");
    loadNotebooks();
  } catch (e) {
    showToast("Hata: " + e.message);
  }
});

$("#gen-notebook").addEventListener("change", (e) => {
  currentNotebookId = e.target.value || null;
  if (currentNotebookId) {
    loadArtifacts(currentNotebookId);
    loadSources(currentNotebookId);
  } else {
    $("#artifact-list").innerHTML = "";
    $("#gen-sources").textContent = "";
  }
});

// ---------- sources ----------
async function loadSources(nbId) {
  try {
    const r = await api(`/api/notebooks/${nbId}/sources`);
    const ready = r.sources.filter((s) => s.status === "ready").length;
    $("#gen-sources").textContent = `${r.sources.length} kaynak (${ready} hazır)`;
  } catch (e) {
    $("#gen-sources").textContent = "Kaynaklar alınamadı";
  }
}

// ---------- generate ----------
async function generate(kind) {
  if (!currentNotebookId) {
    showToast("Önce defter seç");
    return;
  }
  const btn = document.querySelector(`[data-gen="${kind}"]`);
  const prevTxt = btn.textContent;
  btn.disabled = true;
  btn.textContent = "Üretiliyor…";
  try {
    let body = { notebook_id: currentNotebookId };
    let path = "";
    if (kind === "audio") {
      path = "/api/generate/audio";
      body.audio_format = $("#audio-format").value || null;
      body.audio_length = $("#audio-length").value || null;
      body.instructions = $("#gen-instructions").value.trim() || null;
    } else if (kind === "report") {
      path = "/api/generate/report";
      body.report_format = $("#report-format").value || "briefing_doc";
      body.extra_instructions = $("#gen-instructions").value.trim() || null;
    } else if (kind === "quiz") {
      path = "/api/generate/quiz";
    } else if (kind === "mind_map") {
      path = "/api/generate/mind-map";
    } else if (kind === "slide_deck") {
      path = "/api/generate/slide-deck";
      body.instructions = $("#gen-instructions").value.trim() || null;
    }
    const r = await api(path, { method: "POST", body: JSON.stringify(body) });
    showToast(`${kind} kuyrukta` + (r.task_id ? "" : ""));
    setTimeout(() => loadArtifacts(currentNotebookId), 1500);
  } catch (e) {
    showToast("Hata: " + e.message);
  } finally {
    btn.disabled = false;
    btn.textContent = prevTxt;
  }
}
$$(".gen-btn").forEach((b) => b.addEventListener("click", () => generate(b.dataset.gen)));

// ---------- artifacts ----------
async function loadArtifacts(nbId) {
  if (!nbId) return;
  try {
    const r = await api(`/api/notebooks/${nbId}/artifacts`);
    renderArtifacts(r.artifacts || [], nbId);
  } catch (e) {
    $("#artifact-list").innerHTML = `<li class="text-red-600">Hata: ${escapeHtml(e.message)}</li>`;
  }
}
$("#reload-art").addEventListener("click", () => currentNotebookId && loadArtifacts(currentNotebookId));

function renderArtifacts(items, nbId) {
  const ul = $("#artifact-list");
  if (!items.length) {
    ul.innerHTML = '<li class="text-slate-400">Henüz üretilmiş içerik yok.</li>';
    return;
  }
  ul.innerHTML = "";
  for (const a of items) {
    const li = document.createElement("li");
    const pending = a.status && a.status !== "completed";
    li.className = "rounded-lg border border-slate-200 px-3 py-2";
    li.innerHTML = `
      <div class="flex items-center gap-2">
        <span class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-mono uppercase">${a.type || "?"}</span>
        <span class="min-w-0 flex-1 truncate text-sm">${escapeHtml(a.title || "(başlıksız)")}</span>
        ${pending ? '<span class="text-xs text-amber-600">⏳</span>' : ''}
      </div>
      <div class="mt-1 flex items-center justify-between">
        <div class="text-xs text-slate-400">${a.status || ""}</div>
        ${!pending ? '<div class="flex gap-1.5"><button data-act="view" class="rounded-md border border-brand-600 px-2.5 py-1 text-xs font-medium text-brand-600">👁 Görüntüle</button><button data-act="dl" class="rounded-md bg-brand-600 px-2.5 py-1 text-xs font-medium text-white">İndir</button></div>' : ""}
      </div>
    `;
    if (!pending) {
      li.querySelector('[data-act="view"]').addEventListener("click", () => viewArtifact(nbId, a));
      li.querySelector('[data-act="dl"]').addEventListener("click", () => downloadArtifact(nbId, a));
    } else {
      // auto-poll
      if (!pollers.has(a.id)) {
        const id = setInterval(() => loadArtifacts(nbId), 15000);
        pollers.set(a.id, id);
      }
    }
    ul.appendChild(li);
  }
  // clean up pollers for completed/missing artifacts
  for (const [aid, intId] of pollers.entries()) {
    const a = items.find((x) => x.id === aid);
    if (!a || a.status === "completed") {
      clearInterval(intId);
      pollers.delete(aid);
    }
  }
}

// ---------- viewer ----------
function openViewer(title, bodyHtml) {
  $("#viewer-title").textContent = title;
  $("#viewer-body").innerHTML = bodyHtml;
  $("#viewer-modal").classList.remove("hidden");
}
function closeViewer() {
  $("#viewer-modal").classList.add("hidden");
  // revoke any blob URLs
  $("#viewer-body").querySelectorAll("[data-blob-url]").forEach((el) => URL.revokeObjectURL(el.dataset.blobUrl));
  $("#viewer-body").innerHTML = "";
}
$("#viewer-close").addEventListener("click", closeViewer);
$("#viewer-modal").addEventListener("click", (e) => {
  if (e.target.id === "viewer-modal") closeViewer();
});

async function viewArtifact(nbId, a) {
  showToast("Yükleniyor…");
  $("#viewer-download").onclick = () => downloadArtifact(nbId, a);
  try {
    const t = a.type;
    // Text-based: report (md), quiz/mind_map/flashcards (json), data_table (csv)
    if (["report", "quiz", "mind_map", "flashcards", "data_table"].includes(t)) {
      const r = await api(`/api/notebooks/${nbId}/artifacts/${a.id}/preview?type=${encodeURIComponent(t)}`);
      let html = "";
      if (t === "report") {
        const md = r.content || "";
        html = `<article class="prose prose-slate max-w-3xl mx-auto p-6 text-slate-900">${window.marked ? window.marked.parse(md) : `<pre class="whitespace-pre-wrap text-sm">${escapeHtml(md)}</pre>`}</article>`;
      } else if (t === "quiz" || t === "mind_map" || t === "flashcards") {
        try {
          const data = JSON.parse(r.content);
          html = renderJsonContent(t, data);
        } catch {
          html = `<pre class="whitespace-pre-wrap p-4 text-sm">${escapeHtml(r.content)}</pre>`;
        }
      } else {
        html = `<pre class="whitespace-pre-wrap p-4 text-sm">${escapeHtml(r.content || "")}</pre>`;
      }
      openViewer(a.title || a.type, html);
      return;
    }
    // Binary-based: audio/video/slide_deck/infographic — fetch as blob, embed
    const url = `/api/notebooks/${nbId}/artifacts/${a.id}/download?type=${encodeURIComponent(t)}&inline=true`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const blob = await res.blob();
    const blobUrl = URL.createObjectURL(blob);
    let html = "";
    if (t === "audio") {
      html = `<div class="flex items-center justify-center p-6"><audio controls autoplay class="w-full max-w-2xl" data-blob-url="${blobUrl}" src="${blobUrl}"></audio></div>`;
    } else if (t === "video") {
      html = `<div class="flex items-center justify-center p-2"><video controls autoplay class="max-h-full max-w-full" data-blob-url="${blobUrl}" src="${blobUrl}"></video></div>`;
    } else if (t === "slide_deck") {
      html = `<iframe class="h-full w-full" data-blob-url="${blobUrl}" src="${blobUrl}"></iframe>`;
    } else if (t === "infographic") {
      html = `<div class="flex items-center justify-center p-2"><img class="max-h-full max-w-full" data-blob-url="${blobUrl}" src="${blobUrl}" /></div>`;
    } else {
      html = `<a class="block p-4 text-brand-600 underline" data-blob-url="${blobUrl}" href="${blobUrl}" target="_blank">İçeriği aç</a>`;
    }
    openViewer(a.title || a.type, html);
  } catch (e) {
    showToast("Görüntüleme hatası: " + e.message);
  }
}

function renderJsonContent(type, data) {
  if (type === "quiz" && Array.isArray(data?.questions || data)) {
    const qs = data.questions || data;
    return `<div class="prose prose-slate max-w-3xl mx-auto p-6">
      <h1>Quiz</h1>
      <ol class="space-y-4">${qs.map((q, i) => `
        <li>
          <p class="font-medium">${escapeHtml(q.question || q.q || "")}</p>
          ${Array.isArray(q.options || q.choices) ? `<ul class="ml-4 mt-1 space-y-1">${(q.options || q.choices).map((o) => `<li>${escapeHtml(typeof o === "string" ? o : (o.text || ""))}</li>`).join("")}</ul>` : ""}
          ${q.answer || q.correct ? `<details class="mt-1 text-sm text-slate-600"><summary>Cevap</summary><div class="mt-1">${escapeHtml(String(q.answer || q.correct))}</div></details>` : ""}
        </li>`).join("")}
      </ol></div>`;
  }
  if (type === "mind_map") {
    return `<div class="prose prose-slate max-w-3xl mx-auto p-6"><h1>Zihin Haritası</h1>${renderMindNode(data)}</div>`;
  }
  if (type === "flashcards" && Array.isArray(data?.cards || data)) {
    const cs = data.cards || data;
    return `<div class="prose prose-slate max-w-3xl mx-auto p-6">
      <h1>Flashcards</h1>
      <ul class="space-y-3">${cs.map((c) => `
        <li class="rounded border border-slate-200 p-3">
          <p class="font-medium">${escapeHtml(c.front || c.q || "")}</p>
          <details class="mt-1 text-sm"><summary>Arka yüz</summary><p class="mt-1">${escapeHtml(c.back || c.a || "")}</p></details>
        </li>`).join("")}</ul></div>`;
  }
  return `<pre class="whitespace-pre-wrap p-4 text-xs">${escapeHtml(JSON.stringify(data, null, 2))}</pre>`;
}

function renderMindNode(node, depth = 0) {
  if (!node || typeof node !== "object") return "";
  const label = node.title || node.label || node.text || node.name || "";
  const children = node.children || node.nodes || node.subtopics || [];
  const padding = depth === 0 ? "" : "ml-4";
  return `<div class="${padding}">
    <div class="font-${depth === 0 ? "bold" : "medium"}">${escapeHtml(label)}</div>
    ${Array.isArray(children) && children.length ? `<div class="mt-1 space-y-1">${children.map((c) => renderMindNode(c, depth + 1)).join("")}</div>` : ""}
  </div>`;
}

async function downloadArtifact(nbId, a) {
  showToast("İndiriliyor…");
  try {
    const url = `/api/notebooks/${nbId}/artifacts/${a.id}/download?type=${encodeURIComponent(a.type)}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) throw new Error((await res.json()).detail || res.statusText);
    const blob = await res.blob();
    const dlUrl = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = dlUrl;
    link.download = a.title ? `${a.title}` : `artifact-${a.id}`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(dlUrl);
  } catch (e) {
    showToast("İndirme hatası: " + e.message);
  }
}

// ---------- init ----------
async function init() {
  activateTab("search");
  await loadNotebooks();
}

if (token) {
  hideAuth();
  init();
} else {
  showAuth();
}
