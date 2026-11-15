// Detetive Mentor — front-end (vanilla JS)

const state = {
  caseFile: null,
  sessionId: null,
  maxHints: 3,
  solved: false,
  busy: false,
};

const $ = (selector) => document.querySelector(selector);

// ---------------------------------------------------------------- API

async function api(path, options = {}) {
  const response = await fetch(`/api${path}`, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  const data = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
  return data;
}

const post = (path, body) => api(path, { method: "POST", body: JSON.stringify(body) });

// ---------------------------------------------------------------- rendering helpers

function element(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

function addMessage(role, text, source) {
  const item = element("li", `message message--${role}`);
  item.append(element("div", "message__body", text));
  if (source === "cache") item.append(element("div", "message__source", "Resposta reaproveitada do cache semântico"));

  $("#messages").append(item);
  item.scrollIntoView({ behavior: "smooth", block: "end" });
  return item;
}

function plural(count, singular, pluralForm) {
  return `${count} ${count === 1 ? singular : pluralForm}`;
}

function updateProgress(progress) {
  if (!progress) return;

  const hints = progress.hint_level === 0
    ? "Nenhuma dica usada"
    : `${progress.hint_level} de ${state.maxHints} dicas usadas`;
  const discoveries = progress.discoveries === 0
    ? "nenhuma contradição encontrada"
    : `${plural(progress.discoveries, "contradição encontrada", "contradições encontradas")}`;
  $("#progress").textContent = `${hints}, ${discoveries}`;

  const stamp = $("#solved-stamp");
  if (progress.solved && stamp.hidden) {
    stamp.hidden = false;
    stamp.classList.add("is-landing");
  } else if (!progress.solved) {
    stamp.hidden = true;
    stamp.classList.remove("is-landing");
  }

  // once solved, the case can only be discussed or closed: no more hints or accusations
  $(".conversation__header").classList.toggle("is-solved", progress.solved);
  $("#case-closed").hidden = !progress.solved;
  $("#chat-form").classList.toggle("is-closed", progress.solved);
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll(".chat-form button").forEach((b) => (b.disabled = busy));
}

// ---------------------------------------------------------------- case ledger

async function loadCases() {
  const list = $("#case-list");
  try {
    const cases = await api("/cases");
    list.replaceChildren(
      ...cases.map((caseItem, index) => {
        const row = element("tr");
        row.append(element("td", "", String(index + 1).padStart(3, "0")));

        const title = element("td");
        title.append(element("span", "ledger__case-title", caseItem.title));
        row.append(title);

        row.append(element("td", "", caseItem.difficulty));

        const action = element("td");
        const button = element("button", "button", "Abrir caso");
        button.type = "button";
        button.addEventListener("click", () => openCase(caseItem.id));
        action.append(button);
        row.append(action);

        return row;
      })
    );
  } catch (error) {
    const row = element("tr");
    const cell = element("td", "ledger__empty", `Não foi possível carregar os casos (${error.message}). Verifique se o servidor MCP está rodando e recarregue a página.`);
    cell.colSpan = 4;
    row.append(cell);
    list.replaceChildren(row);
  }
}

// ---------------------------------------------------------------- dossier

function renderDossier(caseFile) {
  $("#masthead-case").textContent = `Caso em andamento: ${caseFile.title}`;
  $("#case-title").textContent = caseFile.title;
  $("#case-meta").textContent = `${caseFile.location}, ${caseFile.date}`;
  $("#case-intro").textContent = caseFile.introduction;

  $("#suspect-list").replaceChildren(
    ...caseFile.suspects.map((s) => {
      const li = element("li", "suspect");
      li.append(element("h3", "suspect__name", s.name));
      li.append(element("span", "suspect__shoe", `calça ${s.shoe_size}`));
      li.append(element("p", "suspect__desc", s.description));
      li.append(element("p", "suspect__relationship", s.relationship));
      return li;
    })
  );

  $("#evidence-list").replaceChildren(
    ...caseFile.evidence.map((e) => {
      const li = element("li", "evidence");
      li.append(element("span", "evidence__id", e.id));
      li.append(element("p", "evidence__name", e.name));
      li.append(element("p", "evidence__desc", e.description));
      return li;
    })
  );

  $("#testimony-list").replaceChildren(
    ...caseFile.testimonies.map((t) => {
      const li = element("li", "testimony");
      li.append(element("p", "testimony__person", t.person));
      li.append(element("p", "testimony__text", `“${t.text}”`));
      return li;
    })
  );

  $("#timeline-list").replaceChildren(
    ...caseFile.timeline.map((t) => {
      const li = element("li");
      li.append(element("span", "timeline__time", t.time));
      li.append(element("span", "timeline__event", t.event));
      return li;
    })
  );

  selectTab("summary");
}

function selectTab(name) {
  document.querySelectorAll(".tab").forEach((tab) => {
    const active = tab.dataset.tab === name;
    tab.classList.toggle("is-active", active);
    tab.setAttribute("aria-selected", String(active));
  });
  document.querySelectorAll(".tab-panel").forEach((panel) => panel.classList.toggle("is-active", panel.dataset.panel === name));
}

async function openCase(caseId) {
  try {
    const [caseFile, session] = await Promise.all([api(`/cases/${caseId}`), post("/sessions", { case_id: caseId })]);
    state.caseFile = caseFile;
    state.sessionId = session.session_id;
    state.maxHints = session.hint_count;
    state.solved = false;

    renderDossier(caseFile);
    $("#messages").replaceChildren();
    updateProgress({ hint_level: 0, discoveries: 0, solved: false });
    addMessage("mentor", session.greeting);

    $("#case-picker").hidden = true;
    $("#desk").hidden = false;
    $("#chat-input").focus();
  } catch (error) {
    alert(`Não foi possível abrir o caso (${error.message}).`);
  }
}

// ---------------------------------------------------------------- conversation

async function talk(path, body, learnerText) {
  if (state.busy) return;
  if (learnerText) addMessage("learner", learnerText);

  setBusy(true);
  const waiting = addMessage("mentor", "O inspetor está pensando…");
  waiting.classList.add("message--waiting");

  try {
    const data = await post(path, { session_id: state.sessionId, ...body });
    waiting.remove();
    addMessage("mentor", data.answer, data.source);
    updateProgress(data.progress);
    state.solved = data.progress.solved;
    if (data.solved && path === "/accuse") addMessage("notice", "Caso resolvido.");
  } catch (error) {
    waiting.remove();
    addMessage("notice", `A mensagem não chegou ao mentor (${error.message}). Tente enviar de novo.`);
  } finally {
    setBusy(false);
  }
}

$("#chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const input = $("#chat-input");
  const message = input.value.trim();
  if (!message) return;
  input.value = "";
  talk("/chat", { message }, message);
});

$("#chat-input").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    $("#chat-form").requestSubmit();
  }
});

$("#hint-button").addEventListener("click", () => talk("/hint", {}, "Mentor, preciso de uma dica."));

// ---------------------------------------------------------------- accusation

function openAccusation() {
  const { suspects, evidence } = state.caseFile;

  $("#accuse-suspects").replaceChildren(
    ...suspects.map((s, i) => {
      const label = element("label");
      const input = element("input");
      Object.assign(input, { type: "radio", name: "suspect", value: s.id, required: true, checked: i === 0 });
      label.append(input, document.createTextNode(s.name));
      return label;
    })
  );

  $("#accuse-evidence").replaceChildren(
    ...evidence.map((e) => {
      const label = element("label");
      const input = element("input");
      Object.assign(input, { type: "checkbox", name: "evidence", value: e.id });
      label.append(input, document.createTextNode(`${e.id}, ${e.name.toLowerCase()}`));
      return label;
    })
  );

  $("#accuse-motive").value = "";
  $("#accuse-dialog").showModal();
}

$("#accuse-button").addEventListener("click", openAccusation);
$("#accuse-cancel").addEventListener("click", () => $("#accuse-dialog").close());

$("#accuse-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const form = event.target;
  const suspectId = form.querySelector("input[name=suspect]:checked").value;
  const evidenceIds = [...form.querySelectorAll("input[name=evidence]:checked")].map((i) => i.value);
  const motive = $("#accuse-motive").value.trim();
  const suspect = state.caseFile.suspects.find((s) => s.id === suspectId);

  $("#accuse-dialog").close();
  const evidenceText = evidenceIds.length ? `com as evidências ${evidenceIds.join(", ")}` : "sem citar evidências";
  const summary = `Acuso ${suspect.name}, ${evidenceText}.${motive ? ` Motivo: ${motive}` : ""}`;
  talk("/accuse", { suspect_id: suspectId, evidence_ids: evidenceIds, motive }, summary);
});

// ---------------------------------------------------------------- navigation

document.querySelectorAll(".tab").forEach((tab) => tab.addEventListener("click", () => selectTab(tab.dataset.tab)));

// leaving a case erases its progress on the server, so it can be played again from scratch
async function leaveCase() {
  const sessionId = state.sessionId;
  state.sessionId = null;
  state.caseFile = null;

  $("#desk").hidden = true;
  $("#case-picker").hidden = false;
  $("#masthead-case").textContent = "Escolha um caso para começar a investigação";
  window.scrollTo(0, 0);

  if (sessionId) {
    try {
      await post("/sessions/end", { session_id: sessionId });
    } catch (error) {
      console.warn("could not reset the case progress", error);
    }
  }
}

$("#back-button").addEventListener("click", () => {
  if (state.busy) return;
  if (!state.solved && !confirm("Sair deste caso? A investigação será apagada e o caso recomeça do zero na próxima vez.")) return;
  leaveCase();
});

$("#finish-button").addEventListener("click", () => {
  if (!state.busy) leaveCase();
});

window.addEventListener("pagehide", () => {
  if (!state.sessionId) return;
  const body = new Blob([JSON.stringify({ session_id: state.sessionId })], { type: "application/json" });
  navigator.sendBeacon("/api/sessions/end", body);
});

loadCases();
