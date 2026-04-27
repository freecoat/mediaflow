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
      "propose_quote_line": "Riga quote",
      "propose_price_item": "Voce listino",
      "web_search": "Ricerca web",
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
        <div class="cp-action-data">${escapeHtml(dataPretty)}</div>
        <div class="cp-action-actions">${actions}</div>
        <div class="cp-action-status">Stato: ${status}${a.result ? " · " + escapeHtml(typeof a.result === "string" ? a.result : JSON.stringify(a.result)) : ""}</div>
      </div>
    `;
  }

  // ── Apply / Reject ───────────────────────────────────────
  window.copilotApply = async function (actionId) {
    try {
      const res = await api("POST", `/ai/api/actions/${actionId}/apply`);
      updateActionStatus(actionId, "applied", res.result);
      toast("Azione applicata", "success");
    } catch (e) {
      updateActionStatus(actionId, "failed", e.message);
      toast("Applicazione fallita: " + e.message, "error");
    }
  };

  window.copilotReject = async function (actionId) {
    try {
      await api("POST", `/ai/api/actions/${actionId}/reject`);
      updateActionStatus(actionId, "rejected", null);
    } catch (e) {
      toast(e.message, "error");
    }
  };

  function updateActionStatus(actionId, status, result) {
    for (const m of state.messages) {
      for (const a of (m.actions || [])) {
        if (a.id === actionId) { a.status = status; a.result = result; }
      }
    }
    render();
  }
})();
