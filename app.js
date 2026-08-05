/* Radar de Virais — MediaGrowth
   Pagina estatica (GitHub Pages) que le o seed clients/seed/<slug>.json (via seed/<slug>.json)
   e sincroniza as decisoes de aprovacao com api.php (backend por slug na Hostinger).
   Decisoes sao chaveadas pelo ID do item -> aprovar sobrevive a recoleta de hora em hora. */
(function () {
  "use strict";
  var API = (window.RV_CONFIG && window.RV_CONFIG.apiBase) || "";
  var params = new URLSearchParams(location.search);
  var SLUG = (params.get("c") || params.get("slug") || "marcelo").toLowerCase().replace(/[^a-z0-9\-]/g, "");

  var seed = null;
  var state = { decisions: {}, reviewer: "" };
  var ALLOWED_F = ["all", "ontem", "semana", "mes", "video", "noticia", "approved"];
  var filter = ALLOWED_F.indexOf(params.get("f")) !== -1 ? params.get("f") : "all";
  var openNotes = {};

  var $ = function (id) { return document.getElementById(id); };
  function esc(s) { return String(s == null ? "" : s).replace(/[&<>"']/g, function (c) {
    return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c];
  }); }

  /* ---------- rede ---------- */
  function apiGet() {
    return fetch(API + "?action=get&slug=" + encodeURIComponent(SLUG), { cache: "no-store" })
      .then(function (r) { return r.json(); });
  }
  var savedTimer = null, noteTimer = null;
  function post(action, data) {
    var body = new URLSearchParams();
    body.set("action", action); body.set("slug", SLUG);
    Object.keys(data).forEach(function (k) { body.set(k, data[k] == null ? "" : data[k]); });
    return fetch(API, { method: "POST", headers: { "Content-Type": "application/x-www-form-urlencoded" }, body: body.toString() })
      .then(function (r) { return r.json(); });
  }
  function flashSaved(ok) {
    var el = $("saved"); if (!el) return;
    clearTimeout(savedTimer);
    if (ok === false) { el.textContent = "sem conexão"; el.classList.remove("on"); return; }
    el.textContent = "salvando…"; el.classList.remove("on");
    savedTimer = setTimeout(function () { el.textContent = "salvo ✓"; el.classList.add("on"); }, 250);
  }
  function toast(msg) {
    var t = $("toast"); t.textContent = msg; t.classList.add("show");
    setTimeout(function () { t.classList.remove("show"); }, 2600);
  }

  /* ---------- estado ---------- */
  function decOf(id) { return state.decisions[id] || { status: "pending", note: "" }; }
  function reviewerName() { return ($("reviewer").value || state.reviewer || "").trim(); }

  function saveDecision(id) {
    var d = decOf(id);
    flashSaved();
    post("decide", { id: id, status: d.status, note: d.note || "", by: reviewerName() })
      .then(function () { flashSaved(true); })
      .catch(function () { flashSaved(false); toast("Não consegui salvar. Verifique a conexão."); });
  }

  function setStatus(id, status) {
    if (status === "approved" && !reviewerName()) {
      var rv = $("reviewer"); rv.focus(); rv.scrollIntoView({ block: "center", behavior: "smooth" });
      toast("Escreva seu nome ali em cima antes de aprovar.");
      return;
    }
    var d = state.decisions[id] || { status: "pending", note: "" };
    d.status = (d.status === status) ? "pending" : status;      // toggle
    if (d.status === "pending" && !d.note) delete state.decisions[id];
    else state.decisions[id] = d;
    saveDecision(id);
    render();
  }

  function setNote(id, note) {
    var d = state.decisions[id] || { status: "pending", note: "" };
    d.note = note;
    if (d.status === "pending" && !note) delete state.decisions[id];
    else state.decisions[id] = d;
    clearTimeout(noteTimer);
    noteTimer = setTimeout(function () { saveDecision(id); }, 600);
  }

  /* ---------- filtro ---------- */
  function match(it) {
    var d = decOf(it.id);
    if (filter === "all") return true;
    if (filter === "approved") return d.status === "approved";
    if (filter === "video") return it.tipo === "video";
    if (filter === "noticia") return it.tipo === "noticia";
    if (filter === "ontem" || filter === "semana" || filter === "mes") return it.bucket === filter;
    return true;
  }

  /* ---------- render ---------- */
  var WHEN = { ontem: "🔥 de ontem", semana: "📅 esta semana", mes: "🗓️ este mês" };
  function heatLabel(n) { return n >= 3 ? "🔴🔴🔴 bombando" : n >= 2 ? "🟠🟠 em alta" : "🟡 subindo"; }

  function counts() {
    var ap = 0;
    (seed.itens || []).forEach(function (it) { if (decOf(it.id).status === "approved") ap++; });
    return { ap: ap, total: (seed.itens || []).length };
  }

  function cardHTML(it) {
    var d = decOf(it.id);
    var cls = d.status === "approved" ? " approved" : d.status === "rejected" ? " rejected" : "";
    var isVid = it.tipo === "video";
    var thumb;
    if (it.thumb) {
      thumb = '<a class="thumb" href="' + esc(it.url) + '" target="_blank" rel="noopener" style="background-image:url(' + JSON.stringify(it.thumb) + ')">' +
        (isVid ? '<span class="play">▶</span>' : '') + '</a>';
    } else {
      thumb = '<a class="thumb ph" href="' + esc(it.url) + '" target="_blank" rel="noopener">' + (isVid ? "🎬" : "🌊") + '</a>';
    }
    var extra = "";
    if (it.fontes_extra && it.fontes_extra.length) {
      extra = '<details class="more"><summary>+' + it.fontes_extra.length + ' fontes falando disso</summary><ul>' +
        it.fontes_extra.map(function (f) {
          return '<li><a href="' + esc(f.url) + '" target="_blank" rel="noopener">' + esc(f.titulo) + '</a> <span style="color:#7a869a">· ' + esc(f.fonte) + '</span></li>';
        }).join("") + '</ul></details>';
    }
    var a = it.angulo || {};
    var vistas = isVid && it.views ? ' · ' + Intl.NumberFormat('pt-BR', { notation: 'compact' }).format(it.views) + ' views' : '';
    var noteOpen = openNotes[it.id];
    var byLine = (d.status === "approved" && d.by) ? '<span class="by">✓ Aprovado por ' + esc(d.by) + '</span>' : '';

    return '<article class="card' + cls + '" data-id="' + esc(it.id) + '">' +
      '<div class="card-top">' + thumb +
        '<div class="body">' +
          '<div class="tags">' +
            '<span class="tag tipo-' + it.tipo + '">' + (isVid ? "🎬 Vídeo" : "📰 Notícia") + '</span>' +
            '<span class="tag heat">' + heatLabel(it.calor) + '</span>' +
            (WHEN[it.bucket] ? '<span class="tag when">' + WHEN[it.bucket] + '</span>' : '') +
          '</div>' +
          '<h3>' + esc(it.titulo) + '</h3>' +
          '<div class="src">' + esc(it.fonte || "") + vistas + ' · <a href="' + esc(it.url) + '" target="_blank" rel="noopener">abrir</a></div>' +
        '</div>' +
      '</div>' +
      (a.gancho ? '<div class="angle"><div class="hk">🎯 Ângulo pro Reels</div>' +
        '<div class="gancho">' + esc(a.gancho) + '</div>' +
        '<div class="desc">' + esc(a.corpo || "") + ' ' + esc(a.fecho || "") + '</div>' +
        '<span class="fmt">' + esc(a.formato || "Reels") + '</span></div>' : '') +
      extra +
      '<div class="actions">' +
        '<button class="btn btn-ok" data-act="ok">' + (d.status === "approved" ? "✓ Aprovado" : "✓ Aprovar") + '</button>' +
        '<button class="btn btn-no" data-act="no">✕ Descartar</button>' +
        byLine +
        '<button class="btn btn-cm' + (d.note ? ' has' : '') + '" data-act="cm">💬 Comentar</button>' +
      '</div>' +
      '<div class="note' + (noteOpen ? ' open' : '') + '">' +
        '<textarea placeholder="Um ajuste no ângulo, uma ideia, o que combina mais…">' + esc(d.note || "") + '</textarea>' +
        '<div class="hint">Salva sozinho.</div>' +
      '</div>' +
    '</article>';
  }

  function render() {
    var c = counts();
    $("s-ap").textContent = c.ap; $("s-total").textContent = c.total;
    if (seed.gerado_em) {
      var dt = new Date(seed.gerado_em);
      $("s-upd").textContent = "atualizado " + dt.toLocaleDateString("pt-BR") + " " + dt.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit" });
    }
    var host = $("feed");
    var vis = (seed.itens || []).filter(match);
    host.innerHTML = vis.length ? vis.map(cardHTML).join("") : '<div class="empty">Nada neste filtro por enquanto. Volte daqui a pouco — o radar atualiza sozinho.</div>';
  }

  /* ---------- eventos ---------- */
  function bind() {
    $("feed").addEventListener("click", function (e) {
      var b = e.target.closest("[data-act]"); if (!b) return;
      var card = b.closest(".card"); var id = card.getAttribute("data-id");
      var act = b.getAttribute("data-act");
      if (act === "ok") setStatus(id, "approved");
      else if (act === "no") setStatus(id, "rejected");
      else if (act === "cm") {
        openNotes[id] = !openNotes[id];
        var nb = card.querySelector(".note");
        nb.classList.toggle("open");
        if (nb.classList.contains("open")) { var ta = nb.querySelector("textarea"); if (ta) ta.focus(); }
      }
    });
    $("feed").addEventListener("input", function (e) {
      if (e.target.tagName === "TEXTAREA") {
        var id = e.target.closest(".card").getAttribute("data-id");
        setNote(id, e.target.value);
      }
    });
    $("chips").addEventListener("click", function (e) {
      var chip = e.target.closest(".chip"); if (!chip) return;
      filter = chip.getAttribute("data-f");
      [].forEach.call(document.querySelectorAll(".chip"), function (c) { c.classList.toggle("on", c === chip); });
      render();
    });
    // reflete o filtro inicial (?f=) no chip ativo
    [].forEach.call(document.querySelectorAll(".chip"), function (c) {
      c.classList.toggle("on", c.getAttribute("data-f") === filter);
    });
    var rv = $("reviewer");
    rv.value = localStorage.getItem("rv_reviewer_" + SLUG) || state.reviewer || "";
    rv.addEventListener("change", function () {
      var v = rv.value.trim();
      localStorage.setItem("rv_reviewer_" + SLUG, v);
      state.reviewer = v;
      if (v) post("reviewer", { by: v }).catch(function () {});
    });
  }

  /* ---------- boot ---------- */
  function applyBrand() {
    var b = seed.brand || {};
    var r = document.documentElement.style;
    if (b.primary) r.setProperty("--brand", b.primary);
    if (b.primaryDark) r.setProperty("--brand-dark", b.primaryDark);
    document.title = (seed.client ? seed.client + " · " : "") + (seed.title || "Radar de Virais");
    $("client").textContent = seed.client || "";
    $("title").textContent = seed.title || "Radar de Virais";
    $("subtitle").textContent = seed.subtitle || "";
    $("intro").textContent = seed.intro || "";
    if (b.logo) { var l = $("logo"); l.src = b.logo; l.style.display = ""; l.onerror = function () { l.style.display = "none"; }; l.alt = seed.client || ""; }
  }
  function fail(msg) { $("feed").innerHTML = '<div class="empty">' + esc(msg) + '</div>'; }

  fetch("seed/" + SLUG + ".json", { cache: "no-store" })
    .then(function (r) { if (!r.ok) throw new Error("seed"); return r.json(); })
    .then(function (s) { seed = s; applyBrand(); return apiGet().catch(function () { return null; }); })
    .then(function (live) {
      if (live && typeof live === "object") {
        state.decisions = live.decisions || {};
        state.reviewer = live.reviewer || "";
      }
      bind(); render();
      // sincroniza a cada 45s (reflete quem mais aprovou + itens novos publicados)
      setInterval(function () {
        Promise.all([
          fetch("seed/" + SLUG + ".json", { cache: "no-store" }).then(function (r) { return r.ok ? r.json() : null; }).catch(function () { return null; }),
          apiGet().catch(function () { return null; })
        ]).then(function (res) {
          if (res[0]) seed = res[0];
          if (res[1] && typeof res[1] === "object") { state.decisions = res[1].decisions || {}; state.reviewer = res[1].reviewer || state.reviewer; }
          render();
        });
      }, 45000);
    })
    .catch(function () { fail("Não consegui carregar o radar. Confira o link ou tente de novo."); });
})();
