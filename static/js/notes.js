(() => {
  const notesInput   = document.getElementById("notes-input");
  const titleInput   = document.getElementById("title-input");
  const fileInput    = document.getElementById("file-input");
  const clearFileBtn = document.getElementById("clear-file-btn");
  const fileNameHint = document.getElementById("file-name-hint");
  const lengthSelect = document.getElementById("length-select");
  const qcountSelect = document.getElementById("qcount-select");
  const wordCountEl  = document.getElementById("word-count");
  const errorBox     = document.getElementById("notes-error");

  const summarizeBtn = document.getElementById("summarize-btn");
  const notesStatus   = document.getElementById("notes-status");
  const notesStatusText = document.getElementById("notes-status-text");

  const summaryPanel = document.getElementById("summary-panel");
  const summaryText  = document.getElementById("summary-text");
  const quizBtn       = document.getElementById("quiz-btn");
  const quizStatus     = document.getElementById("quiz-status");
  const quizStatusText = document.getElementById("quiz-status-text");

  const quizPanel = document.getElementById("quiz-panel");
  const quizCards  = document.getElementById("quiz-cards");
  const submitQuizBtn = document.getElementById("submit-quiz-btn");
  const quizResult = document.getElementById("quiz-result");
  const discussBtn = document.getElementById("discuss-btn");

  let currentNoteId = null;
  let currentSummary = "";
  let quizState = [];   // [{question, answer, options, userAnswer, isCorrect, answered}]

  function setStatus(el, textEl, state, text) {
    el.className = `status ${state}`;
    textEl.textContent = text;
  }

  function showError(msg) {
    errorBox.innerHTML = `<div class="error-box">${msg}</div>`;
  }
  function clearError() { errorBox.innerHTML = ""; }

  notesInput.addEventListener("input", () => {
    const words = notesInput.value.trim().split(/\s+/).filter(Boolean).length;
    wordCountEl.textContent = `${words} word${words === 1 ? "" : "s"}`;
  });

  function resetFileInput() {
    fileInput.value = "";
    fileNameHint.textContent = "";
    clearFileBtn.style.display = "none";
  }

  fileInput.addEventListener("change", async () => {
    const file = fileInput.files[0];
    if (!file) return;
    setStatus(notesStatus, notesStatusText, "busy", "Reading file…");
    fileNameHint.textContent = file.name;
    clearFileBtn.style.display = "inline-flex";
    const form = new FormData();
    form.append("file", file);
    try {
      const res = await fetch("/api/upload", { method: "POST", body: form });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Upload failed.");
      notesInput.value = data.text;
      notesInput.dispatchEvent(new Event("input"));
      setStatus(notesStatus, notesStatusText, "ok", "File imported");
      clearError();
    } catch (e) {
      setStatus(notesStatus, notesStatusText, "error", "Import failed");
      showError(e.message);
      resetFileInput();
    }
  });

  clearFileBtn.addEventListener("click", () => {
    resetFileInput();
    notesInput.value = "";
    notesInput.dispatchEvent(new Event("input"));
    clearError();
    setStatus(notesStatus, notesStatusText, "ok", "Ready");
  });

  summarizeBtn.addEventListener("click", async () => {
    const text = notesInput.value.trim();
    if (!text) { showError("Paste or upload some notes first."); return; }
    clearError();
    summarizeBtn.disabled = true;
    setStatus(notesStatus, notesStatusText, "busy", "Summarizing…");

    try {
      const res = await fetch("/api/summarize", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text,
          title: titleInput.value.trim() || "Untitled Note",
          target_length: parseInt(lengthSelect.value, 10),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Summarization failed.");

      currentNoteId = data.note_id;
      currentSummary = data.summary;
      summaryText.textContent = data.summary;
      summaryPanel.style.display = "block";
      quizPanel.style.display = "none";
      setStatus(notesStatus, notesStatusText, "ok", "Summary ready");
      summaryPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setStatus(notesStatus, notesStatusText, "error", "Failed");
      showError(e.message);
    } finally {
      summarizeBtn.disabled = false;
    }
  });

  discussBtn.addEventListener("click", () => {
    if (!currentNoteId) { showError("Summarize your notes first."); return; }
    window.location.href = `/chat?note_id=${currentNoteId}`;
  });

  quizBtn.addEventListener("click", async () => {
    quizBtn.disabled = true;
    setStatus(quizStatus, quizStatusText, "busy", "Generating…");
    try {
      const res = await fetch("/api/quiz", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          text: currentSummary || notesInput.value.trim(),
          max_questions: parseInt(qcountSelect.value, 10),
        }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Quiz generation failed.");

      quizState = data.questions.map(q => ({ ...q, userAnswer: null, isCorrect: null, answered: false }));
      renderQuiz();
      quizPanel.style.display = "block";
      submitQuizBtn.style.display = "none";
      quizResult.innerHTML = "";
      setStatus(quizStatus, quizStatusText, "ok", `${quizState.length} questions ready`);
      quizPanel.scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (e) {
      setStatus(quizStatus, quizStatusText, "error", "Failed");
      showError(e.message);
    } finally {
      quizBtn.disabled = false;
    }
  });

  function renderQuiz() {
    quizCards.innerHTML = quizState.map((q, i) => `
      <div class="quiz-card" data-idx="${i}">
        <div class="quiz-q"><span class="num">Q${i + 1}.</span>${escapeHtml(q.question)}</div>
        <div class="quiz-options">
          ${q.options.map(opt => `<button class="quiz-opt" data-opt="${escapeAttr(opt)}">${escapeHtml(opt)}</button>`).join("")}
        </div>
      </div>
    `).join("");

    quizCards.querySelectorAll(".quiz-card").forEach(card => {
      const idx = parseInt(card.dataset.idx, 10);
      card.querySelectorAll(".quiz-opt").forEach(btn => {
        btn.addEventListener("click", () => handleAnswer(idx, btn, card));
      });
    });
  }

  function handleAnswer(idx, btn, card) {
    const q = quizState[idx];
    if (q.answered) return;

    const chosen = btn.dataset.opt;
    const correct = chosen === q.answer;
    q.userAnswer = chosen;
    q.isCorrect = correct;
    q.answered = true;

    card.querySelectorAll(".quiz-opt").forEach(optBtn => {
      optBtn.disabled = true;
      if (optBtn.dataset.opt === q.answer) optBtn.classList.add("correct");
      else if (optBtn === btn) optBtn.classList.add("incorrect");
    });

    if (quizState.every(x => x.answered)) {
      const score = quizState.filter(x => x.isCorrect).length;
      quizResult.innerHTML = `<div class="quiz-summary-banner">Scored <strong>${score} / ${quizState.length}</strong> — save this attempt to track it on your Progress dashboard.</div>`;
      submitQuizBtn.style.display = "inline-flex";
    }
  }

  submitQuizBtn.addEventListener("click", async () => {
    submitQuizBtn.disabled = true;
    try {
      const payload = {
        note_id: currentNoteId,
        note_title: titleInput.value.trim() || "Untitled Note",
        questions: quizState.map(q => ({
          question: q.question,
          correct_answer: q.answer,
          user_answer: q.userAnswer,
          is_correct: q.isCorrect,
        })),
      };
      const res = await fetch("/api/quiz/submit", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error || "Save failed.");
      quizResult.innerHTML += `<div class="hint">Saved — <a href="/progress" style="color:var(--accent-3);">view your Progress dashboard →</a></div>`;
      submitQuizBtn.style.display = "none";
    } catch (e) {
      showError(e.message);
      submitQuizBtn.disabled = false;
    }
  });

  function escapeHtml(str) {
    const d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
  }
  function escapeAttr(str) {
    return String(str).replace(/"/g, "&quot;");
  }
})();
