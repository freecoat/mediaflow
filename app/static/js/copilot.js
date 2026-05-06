// MediaFlow — Copilot AI drawer
// Pattern "AI propone, utente dispone": ogni azione richiede conferma esplicita.

(function () {
  const state = {
    conversationId: null,
    messages: [],          // [{role, content, actions?}]
    typing: false,
  };

  // ── Context detection ────────────────────────────────────
  function detectContext() {
    const path = location.pathname;
    const ctx = { page: path };
    let m;
    if ((m = path.match(/^\/projects\/(\d+)/))) ctx.project_id = parseInt(m[1]);
    else if ((m = path.match(/^\/quotes\/(\d+)/))) ctx.quote_id = parseInt(m[1]);
    else if ((m = path.match(/^\/jobs\/(\d+)/))) ctx.job_id = parseInt(m[1]);
    if (path.startsWith("/quotes") && location.hash) {
      const qid = parseInt(location.hash.slice(1));
      if (!isNaN(qid)) ctx.quote_id = qid;
    }
    return ctx;
  }

  function ctxTag() {
    const c = detectContext();
    if (c.project_id) return `progetto #${c.project_id}`;
    if (c.quote_id) return `quote #${c.quote_id}`;
    if (c.job_id) return `job #${c.job_id}`;
    return c.page.replace("/", "") || "home";
  }

  // ── Open/close drawer ────────────────────────────────────
  window.copilotOpen = async function () {
    document.body.classList.add("copilot-open");
    document.getElementById("cp-context-tag").textContent = ctxTag();
    await loadConversations();
  };
  window.copilotClose = function () {
    document.body.classList.remove("copilot-open");
  };
  window.copilotNewConv = function () {
    state.conversationId = null;
    state.messages = [];
    document.getElementById("cp-conv-select").value = "";
    render();
  };

  // ── Conversations history ────────────────────────────────
  async function loadConversations() {
    try {
      const list = await api("GET", "/ai/api/conversations");
      const sel = document.getElementById("cp-conv-select");
      const current = sel.value;
      sel.innerHTML = '<option value="">(nuova)</option>' +
        list.map(c => `<option value="${c.id}" ${c.id == state.conversationId ? "selected" : ""}>${(c.title || "—").slice(0, 40)} · ${c.message_count} msg</option>`).join("");
      sel.value = state.conversationId ?? "";
    } catch (e) { /* silent */ }
  }

  window.copilotLoadConv = async function (id) {
    if (!id) { copilotNewConv(); return; }
    try {
      const data = await api("GET", `/ai/api/conversations/${id}`);
      state.conversationId = data.id;
      state.messages = data.messages.map(m => ({ role: m.role, content: m.content, actions: [] }));
      render();
    } catch (e) { toast("Errore caricamento conversazione: " + e.message, "error"); }
  };

  // ── Send message ─────────────────────────────────────────
  // Convenzione: Enter = a capo nel testo, Ctrl/⌘+Enter = invia.
  window.copilotInputKey = function (e) {
    if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      copilotSendOrStop();
    }
  };
  window.copilotResizeInput = function (ta) {
    ta.style.height = "36px";
    ta.style.height = Math.min(160, ta.scrollHeight) + "px";
  };

  // Stato per abort della richiesta in corso
  state.abortCtrl = null;

  window.copilotSendOrStop = function () {
    if (state.typing && state.abortCtrl) {
      state.abortCtrl.abort();
      return;
    }
    copilotSend();
  };

  window.copilotSend = async function () {
    const ta = document.getElementById("cp-input");
    const text = ta.value.trim();
    if (!text || state.typing) return;
    ta.value = ""; copilotResizeInput(ta);

    state.messages.push({ role: "user", content: text });
    render();

    state.abortCtrl = new AbortController();
    setTyping(true);

    const ctx = detectContext();
    const body = {
      messages: state.messages.filter(m => m.role !== "system").map(m => ({ role: m.role, content: m.content })),
      page: ctx.page,
      project_id: ctx.project_id || null,
      quote_id: ctx.quote_id || null,
      job_id: ctx.job_id || null,
      conversation_id: state.conversationId,
    };

    try {
      const r = await fetch("/ai/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: state.abortCtrl.signal,
      });
      const data = await r.json();
      if (!r.ok) throw new Error(data.detail || ("HTTP " + r.status));
      state.conversationId = data.conversation_id || state.conversationId;
      state.messages.push({
        role: "assistant",
        content: data.reply || "",
        actions: data.actions || [],
      });
      if (data.error === "provider_disabled") {
        toast("AI non configurata. Vai in Impostazioni → tab AI.", "info");
      } else {
        // v3.5.0-alpha.29: chime soft al completamento AI (toggle in /settings).
        try { if (typeof playSound === 'function') playSound('ai_done'); } catch (e) {}
      }
    } catch (e) {
      if (e.name === "AbortError") {
        state.messages.push({
          role: "assistant",
          content: "_(generazione interrotta)_",
          actions: [],
        });
      } else {
        state.messages.push({ role: "assistant", content: "Errore: " + e.message, actions: [] });
      }
    } finally {
      state.abortCtrl = null;
      setTyping(false);
      render();
      loadConversations();
    }
  };

  function setTyping(v) {
    state.typing = v;
    document.getElementById("cp-typing").style.display = v ? "block" : "none";
    const btn = document.getElementById("cp-send");
    if (v) {
      btn.textContent = "✕ Stop";
      btn.classList.add("cp-stop");
      btn.disabled = false;  // resta cliccabile per fare abort
    } else {
      btn.textContent = "Invia";
      btn.classList.remove("cp-stop");
      btn.disabled = false;
    }
  }

  // ── Render ───────────────────────────────────────────────
  function escapeHtml(s) {
    return (s || "").replace(/[&<>"']/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  function renderMarkdownBasic(text) {
    // Minimo: code inline, bold, italic, line breaks. Niente parser pesante.
    let html = escapeHtml(text);
    html = html.replace(/```([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
    html = html.replace(/(^|\s)\*([^*\n]+)\*/g, "$1<i>$2</i>");
    html = html.replace(/\n/g, "<br>");
    return html;
  }

  function actionTypeLabel(t) {
    return ({
      "propose_client": "Cliente (nuovo)",
      "propose_project": "Progetto (nuovo)",
      "propose_project_metadata": "Progetto (metadati)",
      "propose_quote": "Quote (nuova)",
      "update_quote": "Quote (modifica)",
      "propose_quote_line": "Riga quote",
      "propose_price_item": "Voce listino",
      "propose_new_item_and_line": "Nuova voce listino + riga quote",
      "propose_booking": "Booking (nuovo)",
      "web_search": "Ricerca web",
      // v3.5.0-alpha.19 — Settings
      "list_settings_schemas": "⚙ Discovery aree configurabili",
      "read_setting": "⚙ Lettura impostazione",
      "update_setting": "⚙ Modifica impostazioni",
    })[t] || t;
  }

  function render() {
    const wrap = document.getElementById("cp-messages");
    if (!state.messages.length) {
      // Lascia il messaggio di benvenuto
      return;
    }
    const html = [];
    for (const m of state.messages) {
      if (m.role === "user") {
        html.push(`<div class="cp-msg user">${escapeHtml(m.content)}</div>`);
      } else {
        if (m.content) {
          html.push(`<div class="cp-msg assistant">${renderMarkdownBasic(m.content)}</div>`);
        }
        for (const a of (m.actions || [])) {
          html.push(renderActionCard(a));
        }
      }
    }
    wrap.innerHTML = html.join("");
    wrap.scrollTop = wrap.scrollHeight;
  }

  function renderActionCard(a) {
    const status = a.status || "proposed";
    const cls = "cp-action-card " + status;
    const dataPretty = JSON.stringify(a.data || {}, null, 2);
    const summary = renderActionSummary(a);
    let actions = "";
    if (status === "proposed") {
      actions = `
        <button class="btn btn-primary btn-sm" onclick="copilotApply(${a.id})">Applica</button>
        <button class="btn btn-secondary btn-sm" onclick="copilotReject(${a.id})">Rifiuta</button>
      `;
    }
    return `
      <div class="${cls}" data-action-id="${a.id}">
        <div class="cp-action-type">${actionTypeLabel(a.action_type)}</div>
        <div class="cp-action-title">${escapeHtml(a.title || "")}</div>
        <div class="cp-action-summary">${summary}</div>
        <div class="cp-action-actions">${actions}</div>
        <div class="cp-action-status">Stato: ${status}${a.result ? " · " + escapeHtml(typeof a.result === "string" ? a.result : JSON.stringify(a.result)) : ""}</div>
        <button class="cp-debug-toggle" type="button" onclick="copilotToggleJSON(this)">&lt;/&gt; Mostra dati grezzi</button>
        <pre class="cp-action-data" hidden>${escapeHtml(dataPretty)}</pre>
      </div>
    `;
  }

  // ── Renderer human-readable per type ─────────────────────
  function renderActionSummary(a) {
    const d = a.data || {};
    switch (a.action_type) {
      case "propose_client": return summaryClient(d);
      case "propose_project": return summaryProject(d);
      case "propose_project_metadata": return summaryProjectMeta(d);
      case "propose_quote": return summaryQuote(d);
      case "update_quote": return summaryUpdateQuote(d);
      case "propose_quote_line": return summaryQuoteLine(d);
      case "propose_price_item": return summaryPriceItem(d);
      case "propose_new_item_and_line": return summaryNewItemAndLine(d);
      case "web_search": return `<div>Cerca: <b>${escapeHtml(d.query || "—")}</b></div>`;
      case "update_setting": return summaryUpdateSetting(d);
      default: return `<span class="cp-muted">Nessun renderer per questo tipo. Apri "dati grezzi".</span>`;
    }
  }

  // v3.5.0-alpha.19 — diff visivo per update_setting (settings registry).
  // Il payload è {key, patch:{field: new_value, ...}}. Mostriamo "key" + ogni
  // field con freccia "→ nuovo_valore". Lo stato attuale (per il "vecchio
  // valore") non è disponibile lato client, ma il backend lo aggiunge al
  // tool_result post-apply ("applied: {field: {old, new}}"). Per la card
  // pre-apply mostriamo solo i nuovi valori e il nome dell'area.
  function summaryUpdateSetting(d) {
    const SETTINGS_LABEL = {
      "working_hours": "Orario di lavoro (default tenant)",
      "tenant_settings": "Dati azienda",
      "notification_preferences": "Preferenze notifiche",
    };
    const lines = [];
    const lbl = SETTINGS_LABEL[d.key] || d.key || "—";
    lines.push(`<b>${escapeHtml(lbl)}</b>`);
    const patch = d.patch || {};
    const keys = Object.keys(patch);
    if (!keys.length) {
      lines.push(`<span class="cp-muted">(nessun campo specificato)</span>`);
      return lines.join("<br>");
    }
    lines.push(`<span class="cp-muted">Modifiche proposte:</span>`);
    const rows = keys.map(k => {
      const v = patch[k];
      const vRender = typeof v === "boolean"
        ? (v ? "✓ true" : "✗ false")
        : (v == null ? "—" : escapeHtml(String(v)));
      return `<div style="font-size:12px;"><span class="cp-muted">${escapeHtml(k)}:</span> <b>${vRender}</b></div>`;
    });
    lines.push(rows.join(""));
    return lines.join("<br>");
  }

  function fmtCur(n) {
    if (n == null || n === "") return "—";
    const num = Number(n);
    if (isNaN(num)) return escapeHtml(String(n));
    return "€ " + num.toLocaleString("it-IT", { minimumFractionDigits: 0, maximumFractionDigits: 2 });
  }

  function summaryClient(d) {
    const lines = [];
    if (d.name) lines.push(`<b>${escapeHtml(d.name)}</b>`);
    const meta = [d.legal_form, d.industry].filter(Boolean).map(escapeHtml).join(" · ");
    if (meta) lines.push(`<span class="cp-muted">${meta}</span>`);
    const loc = [d.city, d.country].filter(Boolean).map(escapeHtml).join(", ");
    if (loc) lines.push(loc);
    if (d.vat_number) lines.push(`P.IVA <span class="mono">${escapeHtml(d.vat_number)}</span>`);
    if (d.contact_email) lines.push(`<span class="cp-muted">${escapeHtml(d.contact_email)}</span>`);
    return lines.join("<br>") || `<span class="cp-muted">Nessun campo</span>`;
  }

  function summaryProject(d) {
    const lines = [];
    const head = `${d.code ? `<b>${escapeHtml(d.code)}</b> · ` : ""}${escapeHtml(d.title || "")}`;
    if (head.trim() && head.trim() !== "·") lines.push(head);
    if (d.client_name) lines.push(`Cliente: ${escapeHtml(d.client_name)}`);
    else if (d.client_id) lines.push(`<span class="cp-muted">Cliente #${d.client_id}</span>`);
    const tech = [
      d.length_minutes ? `${d.length_minutes} min` : null,
      d.production_material,
      d.fps ? `${d.fps} fps` : null,
    ].filter(Boolean).map(escapeHtml).join(" · ");
    if (tech) lines.push(`<span class="cp-muted">${tech}</span>`);
    return lines.join("<br>") || `<span class="cp-muted">Nessun campo</span>`;
  }

  function summaryUpdateQuote(d) {
    const lines = [];
    const head = d.quote_id
      ? `<b>Quote #${escapeHtml(String(d.quote_id))}</b>`
      : (d.quote_number ? `<b>${escapeHtml(d.quote_number)}</b>` : "<b>(quote)</b>");
    lines.push(head + " — modifica");
    const fields = [
      ["title", "titolo"], ["issue_date", "data emiss."], ["valid_until", "scadenza"],
      ["vat_rate", "IVA %"], ["package_discount", "sconto pkg %"],
      ["payment_terms", "pagamento"], ["notes", "note"],
    ];
    for (const [k, lbl] of fields) {
      if (d[k] !== undefined && d[k] !== null && d[k] !== "") {
        lines.push(`<span class="cp-muted">${lbl}:</span> ${escapeHtml(String(d[k])).slice(0, 120)}`);
      }
    }
    return lines.join("<br>");
  }

  function summaryProjectMeta(d) {
    const items = Object.entries(d).filter(([k]) => k !== "project_id" && k !== "id");
    if (!items.length) return `<span class="cp-muted">Nessun campo</span>`;
    return items.map(([k, v]) =>
      `<div><span class="cp-muted">${escapeHtml(k)}:</span> ${escapeHtml(String(v))}</div>`
    ).join("");
  }

  function summaryQuote(d) {
    const head = [];
    if (d.number) head.push(`<b>${escapeHtml(d.number)}</b>`);
    if (d.title) head.push(escapeHtml(d.title));
    if (d.project_id && !d.title) head.push(`<span class="cp-muted">progetto #${d.project_id}</span>`);
    let body = head.length ? head.join(" · ") : "";
    const meta = [];
    if (d.issue_date) meta.push(`Emessa ${escapeHtml(d.issue_date)}`);
    if (d.valid_until) meta.push(`valida fino ${escapeHtml(d.valid_until)}`);
    if (d.vat_rate != null) meta.push(`IVA ${d.vat_rate}%`);
    if (meta.length) body += `<br><span class="cp-muted">${meta.join(" · ")}</span>`;
    const arr = d.lines || [];
    if (arr.length) {
      const rows = arr.slice(0, 8).map(l => `
        <tr>
          <td>${escapeHtml(l.description || "")}</td>
          <td>${l.quantity ?? ""}</td>
          <td>${escapeHtml(l.unit || "")}</td>
          <td>${l.unit_price != null ? fmtCur(l.unit_price) : ""}</td>
        </tr>`).join("");
      body += `
        <table class="cp-mini-table">
          <thead><tr><th>Descrizione</th><th>Q.tà</th><th>Unità</th><th>€</th></tr></thead>
          <tbody>${rows}</tbody>
        </table>`;
      if (arr.length > 8) body += `<div class="cp-muted">+${arr.length - 8} altre righe…</div>`;
    }
    return body || `<span class="cp-muted">Nessun campo</span>`;
  }

  function summaryQuoteLine(d) {
    const lines = [];
    const desc = d.description || (d.price_item_id ? `(da listino #${d.price_item_id})` : "—");
    lines.push(`<b>${escapeHtml(desc)}</b>`);
    const qty = `${d.quantity ?? "?"} ${escapeHtml(d.unit || "")}`;
    const price = d.unit_price != null ? `× ${fmtCur(d.unit_price)}` : "";
    lines.push(`<span class="cp-muted">${qty} ${price}</span>`);
    if (d.quote_id) lines.push(`<span class="cp-muted">in quote #${d.quote_id}</span>`);
    if (d.price_item_id) {
      lines.push(`<span class="cp-muted">✓ legata a voce listino #${d.price_item_id}</span>`);
    } else {
      lines.push(`<span class="cp-muted">⚠ voce libera (non legata al listino)</span>`);
    }
    if (d.category_override) lines.push(`<span class="cp-muted">categoria: ${escapeHtml(d.category_override)}</span>`);
    return lines.join("<br>");
  }

  function summaryNewItemAndLine(d) {
    const lines = [];
    lines.push(`<b>${escapeHtml(d.name || d.description || "—")}</b>`);
    const meta = [d.category_name, d.unit].filter(Boolean).map(escapeHtml).join(" · ");
    if (meta) lines.push(`<span class="cp-muted">${meta}</span>`);
    if (d.price_list != null) lines.push(`Listino: <b>${fmtCur(d.price_list)}</b>`);
    const qty = d.quantity ?? 1;
    if (d.price_list != null) {
      const tot = qty * Number(d.price_list);
      lines.push(`<span class="cp-muted">→ ${qty} ${escapeHtml(d.unit || "")} × ${fmtCur(d.price_list)} = ${fmtCur(tot)}</span>`);
    }
    if (d.quote_id) lines.push(`<span class="cp-muted">in quote #${d.quote_id}</span>`);
    if (d.quote_number) lines.push(`<span class="cp-muted">in quote ${escapeHtml(d.quote_number)}</span>`);
    return lines.join("<br>");
  }

  function summaryPriceItem(d) {
    const lines = [];
    lines.push(`<b>${escapeHtml(d.description || d.name || "")}</b>`);
    const meta = [d.category, d.unit].filter(Boolean).map(escapeHtml).join(" · ");
    if (meta) lines.push(`<span class="cp-muted">${meta}</span>`);
    const prices = [];
    if (d.price_list != null) prices.push(`Listino: ${fmtCur(d.price_list)}`);
    if (d.price_average != null) prices.push(`Medio: ${fmtCur(d.price_average)}`);
    if (d.price_low != null) prices.push(`Basso: ${fmtCur(d.price_low)}`);
    if (prices.length) lines.push(prices.join(" · "));
    if (d.keywords) {
      const kws = Array.isArray(d.keywords) ? d.keywords : String(d.keywords).split(",");
      lines.push(`<span class="cp-muted">keywords: ${kws.map(k => escapeHtml(k.trim())).join(", ")}</span>`);
    }
    return lines.join("<br>");
  }

  window.copilotToggleJSON = function (btn) {
    const pre = btn.nextElementSibling;
    if (!pre) return;
    if (pre.hasAttribute("hidden")) {
      pre.removeAttribute("hidden");
      btn.innerHTML = "&lt;/&gt; Nascondi dati grezzi";
    } else {
      pre.setAttribute("hidden", "");
      btn.innerHTML = "&lt;/&gt; Mostra dati grezzi";
    }
  };

  // ── Apply / Reject ───────────────────────────────────────
  window.copilotApply = async function (actionId) {
    try {
      const res = await api("POST", `/ai/api/actions/${actionId}/apply`);
      // Il backend può ritornare 200 con {ok: false, error} per Apply
      // fallito ma processato (stato applicativo, non errore HTTP).
      if (res && res.ok === false) {
        const msg = res.error || "Errore sconosciuto";
        updateActionStatus(actionId, "failed", msg);
        toast("Applicazione fallita: " + msg, "error");
      } else {
        updateActionStatus(actionId, "applied", res.result);
        toast("Azione applicata", "success");
        // v3.5.0-alpha.13: notifica le pagine in ascolto in modo che possano
        // fare un refresh realtime (es. lista /quotes deve apparire la nuova
        // quote senza F5). I listener si registrano via:
        //   document.addEventListener('mf:ai-action-applied', e => ...)
        // L'evento porta `detail = {actionId, actionType, result}`.
        try {
          const action = _findAction(actionId);
          document.dispatchEvent(new CustomEvent('mf:ai-action-applied', {
            detail: {
              actionId,
              actionType: action ? action.action_type : null,
              result: res.result || null,
            },
          }));
        } catch(_) { /* fail-safe */ }
      }
      handleContinuation(res && res.continuation);
    } catch (e) {
      updateActionStatus(actionId, "failed", e.message);
      toast("Applicazione fallita: " + e.message, "error");
    }
  };

  // Helper: ritrova un'azione dal state per leggere action_type
  function _findAction(actionId) {
    for (const m of state.messages) {
      for (const a of (m.actions || [])) {
        if (a.id === actionId) return a;
      }
    }
    return null;
  }

  window.copilotReject = async function (actionId) {
    try {
      const res = await api("POST", `/ai/api/actions/${actionId}/reject`);
      updateActionStatus(actionId, "rejected", null);
      handleContinuation(res && res.continuation);
    } catch (e) {
      toast(e.message, "error");
    }
  };

  // Quando il backend ha riavviato il loop tool_use dopo un Apply/Reject,
  // restituisce `continuation = {text, actions, done, still_pending}`.
  // Mostriamo testo e nuove card come una nuova bubble assistant.
  function handleContinuation(c) {
    if (!c) return;
    if (!c.text && !(c.actions && c.actions.length)) return;
    state.messages.push({
      role: "assistant",
      content: c.text || "",
      actions: c.actions || [],
    });
    render();
    loadConversations();
  }

  function updateActionStatus(actionId, status, result) {
    for (const m of state.messages) {
      for (const a of (m.actions || [])) {
        if (a.id === actionId) { a.status = status; a.result = result; }
      }
    }
    render();
  }
})();
