(() => {
  const log = document.getElementById("chat-log");
  const empty = document.getElementById("chat-empty");
  const input = document.getElementById("chat-input");
  const sendBtn = document.getElementById("send-btn");
  const newChatBtn = document.getElementById("new-chat-btn");
  const statusEl = document.getElementById("chat-status");
  const statusText = document.getElementById("chat-status-text");
  const errorBox = document.getElementById("chat-error");
  const noteSelect = document.getElementById("note-select");
  const noteBadge = document.getElementById("note-badge");
  const noteBadgeTitle = document.getElementById("note-badge-title");

  let conversationId = window.__INITIAL_CONVERSATION_ID__ || null;
  let attachedNoteId = window.__INITIAL_NOTE_ID__ || null;
  let notesList = [];

  function setStatus(state, text) {
    statusEl.className = `status ${state}`;
    statusText.textContent = text;
  }

  function showError(msg) {
    errorBox.innerHTML = `<div class="error-box">${msg}</div>`;
  }
  function clearError() { errorBox.innerHTML = ""; }

  function clearLog() {
    log.innerHTML = "";
    log.appendChild(empty);
    empty.style.display = "block";
  }

  function addBubble(role, text) {
    empty.style.display = "none";
    const b = document.createElement("div");
    b.className = `bubble ${role}`;
    if (role === "ai") {
      b.innerHTML = `<span class="role">A.P.E.X.</span><span class="text"></span>`;
      b.querySelector(".text").textContent = text || "";
    } else {
      b.textContent = text;
    }
    log.appendChild(b);
    log.scrollTop = log.scrollHeight;
    return b;
  }

  function updateUrl() {
    const url = conversationId ? `/chat?conversation_id=${conversationId}` : "/chat";
    window.history.replaceState({}, "", url);
  }

  // ── Note attachment (RAG) ────────────────────────────────────────────

  function noteTitleById(id) {
    const n = notesList.find(n => n.id === id);
    return n ? n.title : "your note";
  }

  function showNoteBadge(noteId) {
    noteBadgeTitle.textContent = noteTitleById(noteId);
    noteBadge.style.display = "inline-flex";
    noteSelect.style.display = "none";
  }

  function showNotePicker() {
    noteBadge.style.display = "none";
    noteSelect.style.display = "inline-block";
    noteSelect.value = "";
  }

  async function loadNotesList() {
    try {
      const res = await fetch("/api/notes/list");
      const data = await res.json();
      if (!res.ok) return;
      notesList = data.notes || [];
      noteSelect.innerHTML = `<option value="">Attach a saved note (optional)…</option>` +
        notesList.map(n => `<option value="${n.id}">${escapeHtml(n.title)}</option>`).join("");
      if (attachedNoteId) {
        if (conversationId) showNoteBadge(attachedNoteId);
        else { noteSelect.value = attachedNoteId; }
      }
    } catch (e) { /* non-critical — the picker just stays empty */ }
  }

  noteSelect.addEventListener("change", () => {
    attachedNoteId = noteSelect.value || null;
  });

  // ── Conversation loading ─────────────────────────────────────────────

  async function loadConversation(id) {
    setStatus("busy", "Loading conversation…");
    try {
      const res = await fetch(`/api/conversations/${id}`);
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Couldn't load that conversation.");
      clearLog();
      for (const m of data.messages) {
        addBubble(m.role === "user" ? "user" : "ai", m.content);
      }
      conversationId = data.conversation_id;
      attachedNoteId = data.note_id || null;
      if (attachedNoteId) showNoteBadge(attachedNoteId);
      else showNotePicker();
      setStatus("ok", "Ready");
    } catch (e) {
      setStatus("error", "Failed to load");
      showError(e.message);
    }
  }

  loadNotesList().then(() => {
    if (conversationId) loadConversation(conversationId);
    else if (attachedNoteId) showNoteBadge(attachedNoteId);
  });

  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      send();
    }
  });
  sendBtn.addEventListener("click", send);

  newChatBtn.addEventListener("click", () => {
    conversationId = null;
    attachedNoteId = null;
    clearLog();
    clearError();
    updateUrl();
    showNotePicker();
    setStatus("ok", "New chat started");
    input.focus();
  });

  async function send() {
    const text = input.value.trim();
    if (!text) return;
    clearError();
    input.value = "";
    sendBtn.disabled = true;
    setStatus("busy", "A.P.E.X. is thinking…");

    addBubble("user", text);
    const aiBubble = addBubble("ai", "");
    const aiTextEl = aiBubble.querySelector(".text");

    try {
      const res = await fetch("/api/chat/stream", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, conversation_id: conversationId, note_id: attachedNoteId }),
      });
      if (!res.ok || !res.body) {
        const data = await res.json().catch(() => ({}));
        if (data.auth_required) { window.location.href = "/login"; return; }
        throw new Error(data.error || "The tutor didn't respond.");
      }

      const reader = res.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";

      while (true) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n\n");
        buffer = parts.pop();  // last (possibly incomplete) chunk stays in buffer

        for (const part of parts) {
          const line = part.trim();
          if (!line.startsWith("data:")) continue;
          const payload = JSON.parse(line.slice(5).trim());
          if (payload.error) throw new Error(payload.error);
          if (payload.conversation_id && !conversationId) {
            conversationId = payload.conversation_id;
            updateUrl();
            if (attachedNoteId) showNoteBadge(attachedNoteId);
          }
          if (payload.chunk) {
            aiTextEl.textContent += payload.chunk;
            log.scrollTop = log.scrollHeight;
          }
        }
      }
      setStatus("ok", "Ready");
    } catch (e) {
      setStatus("error", "Failed");
      showError(e.message);
      if (!aiTextEl.textContent) aiBubble.remove();
    } finally {
      sendBtn.disabled = false;
      input.focus();
    }
  }

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
})();
