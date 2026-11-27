(() => {
  const CFG = window.SITE_CONFIG || {};
  const LANGS = Object.keys(window.I18N);
  const $ = id => document.getElementById(id);
  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  };

  const params = new URLSearchParams(location.search);
  const browser = (navigator.language || "en").slice(0, 2);
  let lang = params.get("lang") || store.get("fr_lang") || (LANGS.includes(browser) ? browser : CFG.defaultLang || "en");
  if (!LANGS.includes(lang)) lang = "en";

  const state = { view: params.get("view") || "all", items: [], generated: null };
  const T = k => (window.I18N[lang][k] ?? window.I18N.en[k] ?? k);
  const TYPES = ["grant", "contest", "subsidy", "training", "news"];
  const THEMES = ["youth", "migrants", "latam", "culture", "democracy", "sustainability", "inclusion", "volunteering", "civil-society"];
  const VIEWS = {
    all: () => true,
    de: o => o.scope.includes("DE") || o.scope.includes("EU"),
    eu: o => o.scope.includes("EU"),
    mig: o => o.audiences.includes("migrants") || o.audiences.includes("latam"),
    nat: o => o.scope.some(s => s !== "EU" && s !== "DE"),
  };
  const FLAGS = { EU: "🇪🇺", DE: "🇩🇪", ES: "🇪🇸", PT: "🇵🇹", FR: "🇫🇷", IT: "🇮🇹", AT: "🇦🇹", BE: "🇧🇪", NL: "🇳🇱", PL: "🇵🇱", GR: "🇬🇷", IE: "🇮🇪" };

  const today = new Date(); today.setHours(0, 0, 0, 0);
  const daysTo = iso => Math.round((new Date(iso + "T00:00:00") - today) / 864e5);
  const isNew = o => o.first_seen && (today - new Date(o.first_seen + "T00:00:00")) / 864e5 <= 7;
  const fmtDate = iso => new Date(iso + "T00:00:00").toLocaleDateString(lang, { day: "numeric", month: "short", year: "numeric" });
  const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  function fillSelect(el, options, keep) {
    const cur = keep ? el.value : "";
    el.innerHTML = options.map(([v, label]) => `<option value="${esc(v)}">${esc(label)}</option>`).join("");
    if (cur && options.some(o => o[0] === cur)) el.value = cur;
  }

  function renderChrome() {
    document.documentElement.lang = lang;
    document.querySelectorAll("[data-i18n]").forEach(el => { el.textContent = T(el.dataset.i18n); });
    document.querySelectorAll("[data-i18n-ph]").forEach(el => { el.placeholder = T(el.dataset.i18nPh); });
    fillSelect($("lang"), LANGS.map(l => [l, window.I18N[l]._name]));
    $("lang").value = lang;
    fillSelect($("f-type"), [["", `${T("f_type")}: ${T("any")}`], ...TYPES.map(t => [t, T("t_" + t)])], true);
    fillSelect($("f-theme"), [["", `${T("f_theme")}: ${T("any")}`], ...THEMES.map(t => [t, T("a_" + t)])], true);
    fillSelect($("f-deadline"), [["", `${T("f_deadline")}: ${T("any")}`], ["30", T("d30")], ["90", T("d90")], ["rolling", T("rolling")]], true);
    fillSelect($("f-sort"), [["deadline", T("sort_deadline")], ["new", T("sort_new")]], true);
    $("views").innerHTML = Object.keys(VIEWS).map(v =>
      `<button role="tab" data-view="${v}" aria-selected="${v === state.view}">${esc(T("v_" + v))}</button>`).join("");
    $("suggest").href = reportHref(null);
    if (state.generated) $("updated").textContent = new Date(state.generated).toLocaleString(lang, { dateStyle: "medium", timeStyle: "short" });
  }

  function reportHref(o) {
    const title = o ? `Report: ${o.id}` : "Suggestion: new opportunity";
    const body = o ? `${T("report_body")}\n\n${o.title}\n${o.url}\nid: ${o.id}\n\n` : "Name:\nLink:\nDeadline:\nWho can apply:\n";
    if (CFG.repo) return `https://github.com/${CFG.repo}/issues/new?labels=${o ? "report" : "suggestion"}&title=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
    if (CFG.reportEmail) return `mailto:${CFG.reportEmail}?subject=${encodeURIComponent(title)}&body=${encodeURIComponent(body)}`;
    return "#";
  }

  function filtered() {
    const q = $("q").value.trim().toLowerCase();
    const type = $("f-type").value, theme = $("f-theme").value, dl = $("f-deadline").value, onlyNew = $("f-new").checked;
    let out = state.items.filter(VIEWS[state.view] || VIEWS.all).filter(o => {
      if (type && o.type !== type) return false;
      if (theme && !o.audiences.includes(theme)) return false;
      if (onlyNew && !isNew(o)) return false;
      if (dl === "rolling" && o.deadline) return false;
      if ((dl === "30" || dl === "90") && (!o.deadline || daysTo(o.deadline) > +dl)) return false;
      if (q && !`${o.title} ${o.summary} ${o.programme || ""} ${o.source_name}`.toLowerCase().includes(q)) return false;
      return true;
    });
    if ($("f-sort").value === "new") out = out.slice().sort((a, b) => (b.first_seen || "").localeCompare(a.first_seen || ""));
    return out;
  }

  function card(o) {
    const d = o.deadline ? daysTo(o.deadline) : null;
    const dl = o.deadline
      ? `<span class="pill dl ${d <= 21 ? "soon" : ""}">${esc(T("deadline"))}: ${esc(fmtDate(o.deadline))} · ${esc(T("days_left")(d))}</span>`
      : `<span class="pill dl">${esc(T("no_deadline"))}</span>`;
    const tags = o.audiences.filter(a => THEMES.includes(a)).map(a => `<span class="pill">${esc(T("a_" + a))}</span>`).join("");
    const scope = o.scope.map(s => `${FLAGS[s] || ""} ${esc(s)}`).join(" ");
    const rep = reportHref(o);
    return `<li class="card">
      <div class="meta">${dl}${isNew(o) ? `<span class="pill new">${esc(T("isnew"))}</span>` : ""}<span class="pill">${esc(T("t_" + o.type))}</span><span>${scope}</span></div>
      <h2><a href="${esc(o.url)}" target="_blank" rel="noopener">${esc(o.title)}</a></h2>
      ${o.summary ? `<p class="summary">${esc(o.summary)}</p>` : ""}
      <div class="meta">${tags}</div>
      <div class="actions">
        <a class="go" href="${esc(o.url)}" target="_blank" rel="noopener">${esc(T("open"))} →</a>
        ${rep !== "#" ? `<a class="rep" href="${esc(rep)}" target="_blank" rel="noopener">⚑ ${esc(T("report"))}</a>` : ""}
        <span class="src">${esc(o.source_name)}${o.programme ? " · " + esc(o.programme) : ""} · ${esc(T("lang_note"))}: ${esc(o.language.toUpperCase())}</span>
      </div>
    </li>`;
  }

  function render() {
    const list = filtered();
    $("count").textContent = T("results")(list.length);
    $("list").innerHTML = list.length ? list.map(card).join("") : `<li class="empty">${esc(T("none"))}</li>`;
  }

  function syncUrl() {
    const p = new URLSearchParams(location.search);
    p.set("lang", lang); p.set("view", state.view);
    history.replaceState(null, "", "?" + p.toString());
  }

  $("lang").addEventListener("change", e => { lang = e.target.value; store.set("fr_lang", lang); renderChrome(); render(); syncUrl(); });
  $("views").addEventListener("click", e => {
    const b = e.target.closest("button[data-view]"); if (!b) return;
    state.view = b.dataset.view; renderChrome(); render(); syncUrl();
  });
  ["q", "f-type", "f-theme", "f-deadline", "f-sort", "f-new"].forEach(id => $(id).addEventListener("input", render));

  renderChrome();
  fetch("data/opportunities.json", { cache: "no-cache" })
    .then(r => r.json())
    .then(data => { state.items = data.items || []; state.generated = data.generated_at; renderChrome(); render(); })
    .catch(() => { $("list").innerHTML = `<li class="empty">Could not load data.</li>`; });
})();
