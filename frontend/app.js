const PROFILE_FIELDS = [
  ["preferred_languages", "languages-tags"],
  ["preferred_topics", "topics-tags"],
  ["preferred_orgs", "orgs-tags"],
  ["excluded_labels", "excluded-labels-tags"],
  ["excluded_topics", "excluded-topics-tags"],
];

const EMPTY_PROFILE = {
  preferred_languages: [],
  preferred_topics: [],
  preferred_orgs: [],
  excluded_labels: [],
  excluded_topics: [],
  experience_level: "intermediate",
  raw_notes: "",
};

const elements = {
  chatLog: document.getElementById("chat-log"),
  chatForm: document.getElementById("chat-form"),
  messageInput: document.getElementById("message-input"),
  sendButton: document.getElementById("send-button"),
  errorBanner: document.getElementById("error-banner"),
  wakeBanner: document.getElementById("wake-banner"),
  healthDot: document.getElementById("health-dot"),
  healthLabel: document.getElementById("health-label"),
  sessionKey: document.getElementById("session-key"),
  saveStatus: document.getElementById("save-status"),
  experience: document.getElementById("experience-level"),
  prioritizeGSoC: document.getElementById("prioritize-gsoc"),
  sidebar: document.getElementById("sidebar"),
  sidebarToggle: document.getElementById("sidebar-toggle"),
};

let sessionKey = readStorage("scout.sessionKey") || createSessionKey();
let preferences = structuredClone(EMPTY_PROFILE);
let saveTimer;

function readStorage(key) {
  try {
    return window.localStorage.getItem(key);
  } catch {
    return null;
  }
}

function writeStorage(key, value) {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    showError("Local storage is unavailable. Session settings may not persist after closing this tab.");
  }
}

function createSessionKey() {
  const identifier = globalThis.crypto?.randomUUID?.()
    || `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
  return `scout-${identifier}`;
}

function setSessionKey(value) {
  sessionKey = value;
  writeStorage("scout.sessionKey", value);
  elements.sessionKey.textContent = value;
}

function showError(message) {
  elements.errorBanner.textContent = message;
  elements.errorBanner.hidden = false;
}

function clearError() {
  elements.errorBanner.textContent = "";
  elements.errorBanner.hidden = true;
}

async function requestJson(path, options = {}) {
  const response = await fetch(path, {
    ...options,
    headers: {
      Accept: "application/json",
      ...(options.body ? { "Content-Type": "application/json" } : {}),
      ...options.headers,
    },
  });
  if (!response.ok) {
    const body = await response.text();
    const error = new Error(body || `Request failed (${response.status})`);
    error.status = response.status;
    throw error;
  }
  if (response.status === 204) {
    return null;
  }
  return response.json();
}

function updateHealth(healthy, waking = false) {
  elements.healthDot.classList.toggle("is-healthy", healthy);
  elements.healthDot.classList.toggle("is-offline", !healthy && !waking);
  elements.healthDot.classList.toggle("is-waking", waking);
  elements.healthLabel.textContent = healthy ? "Backend online" : waking ? "Waking up" : "Unavailable";
  elements.wakeBanner.hidden = healthy;
}

async function pollHealth() {
  try {
    const response = await fetch("/health", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Health check returned ${response.status}`);
    }
    updateHealth(true);
    return true;
  } catch {
    updateHealth(false, true);
    return false;
  }
}

async function monitorHealth() {
  if (await pollHealth()) {
    return;
  }
  const interval = window.setInterval(async () => {
    if (await pollHealth()) {
      window.clearInterval(interval);
    }
  }, 3000);
}

function renderTagEditor(field, containerId) {
  const container = document.getElementById(containerId);
  container.replaceChildren();
  for (const tag of preferences[field] || []) {
    const chip = document.createElement("span");
    chip.className = "tag-chip";
    const label = document.createElement("span");
    label.textContent = tag;
    const remove = document.createElement("button");
    remove.type = "button";
    remove.className = "tag-remove";
    remove.textContent = "×";
    remove.setAttribute("aria-label", `Remove ${tag}`);
    remove.addEventListener("click", () => {
      preferences[field] = preferences[field].filter((item) => item !== tag);
      renderTagEditor(field, containerId);
      schedulePreferenceSave();
    });
    chip.append(label, remove);
    container.append(chip);
  }
}

function renderPreferences() {
  for (const [field, containerId] of PROFILE_FIELDS) {
    renderTagEditor(field, containerId);
  }
  elements.experience.value = preferences.experience_level || "intermediate";
}

async function loadPreferences() {
  try {
    preferences = await requestJson(`/api/v1/profiles/${encodeURIComponent(sessionKey)}`);
    elements.saveStatus.textContent = "Preferences synced to this session.";
  } catch (error) {
    if (error.status !== 404) {
      showError("Could not load preferences. You can still chat; try refreshing the preferences later.");
    }
    preferences = structuredClone(EMPTY_PROFILE);
    elements.saveStatus.textContent = "No saved preferences yet.";
  }
  renderPreferences();
}

async function savePreferences() {
  elements.saveStatus.textContent = "Saving preferences…";
  elements.saveStatus.classList.remove("is-error");
  try {
    preferences = await requestJson(`/api/v1/profiles/${encodeURIComponent(sessionKey)}`, {
      method: "PUT",
      body: JSON.stringify(preferences),
    });
    renderPreferences();
    elements.saveStatus.textContent = "Preferences saved.";
  } catch (error) {
    elements.saveStatus.textContent = "Could not save preferences.";
    elements.saveStatus.classList.add("is-error");
    showError(`Preference save failed: ${error.message}`);
  }
}

function schedulePreferenceSave() {
  window.clearTimeout(saveTimer);
  saveTimer = window.setTimeout(savePreferences, 250);
}

function addTag(field, input) {
  const tag = input.value.trim().toLocaleLowerCase();
  input.value = "";
  if (!tag || (preferences[field] || []).includes(tag)) {
    return;
  }
  preferences[field] = [...(preferences[field] || []), tag];
  const config = PROFILE_FIELDS.find(([candidate]) => candidate === field);
  if (config) {
    renderTagEditor(config[0], config[1]);
  }
  schedulePreferenceSave();
}

for (const button of document.querySelectorAll("[data-add-tag]")) {
  button.addEventListener("click", () => {
    const field = button.dataset.addTag;
    const input = document.querySelector(`[data-tag-input="${field}"]`);
    if (field && input) {
      addTag(field, input);
    }
  });
}

for (const input of document.querySelectorAll("[data-tag-input]")) {
  input.addEventListener("keydown", (event) => {
    if (event.key === "Enter") {
      event.preventDefault();
      const field = input.dataset.tagInput;
      if (field) {
        addTag(field, input);
      }
    }
  });
}

elements.experience.addEventListener("change", () => {
  preferences.experience_level = elements.experience.value;
  schedulePreferenceSave();
});

elements.prioritizeGSoC.checked = readStorage("scout.prioritizeGSoC") !== "false";
elements.prioritizeGSoC.addEventListener("change", () => {
  writeStorage("scout.prioritizeGSoC", String(elements.prioritizeGSoC.checked));
});

function appendMessage(role, text) {
  document.getElementById("welcome-card")?.remove();
  const message = document.createElement("div");
  message.className = `message message-${role}`;
  message.textContent = text;
  elements.chatLog.append(message);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  return message;
}

function appendResponse(response) {
  document.getElementById("welcome-card")?.remove();
  const turn = document.createElement("article");
  turn.className = "chat-turn";
  turn.append(createMessage("assistant", response.assistant_message));
  turn.append(createTelemetry(response));

  if (response.matches?.length) {
    const list = document.createElement("div");
    list.className = "match-list";
    for (const match of response.matches) {
      list.append(createMatchCard(match, list));
    }
    turn.append(list);
  }
  elements.chatLog.append(turn);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function createMessage(role, text) {
  const message = document.createElement("div");
  message.className = `message message-${role}`;
  message.textContent = text || "";
  return message;
}

function createTelemetry(response) {
  const telemetry = document.createElement("div");
  telemetry.className = "telemetry";
  telemetry.append(
    createTelemetryPill("provider", response.provider_used || "unknown"),
    createTelemetryPill("latency", `${Number(response.latency_ms || 0).toFixed(0)} ms`),
  );

  const traces = document.createElement("span");
  traces.className = "trace-list";
  for (const item of response.tool_trace || []) {
    const pill = document.createElement("span");
    pill.className = "trace-pill";
    pill.textContent = item;
    traces.append(pill);
  }
  if (traces.childElementCount) {
    telemetry.append(traces);
  }

  if (response.hydration?.triggered === true) {
    const repos = response.hydration.repos_synced?.join(", ") || response.hydration.scope || "target scope";
    const badge = document.createElement("span");
    badge.className = "hydration-badge";
    badge.textContent = `JIT · synced ${repos} · +${response.hydration.issues_added || 0} issues`;
    telemetry.append(badge);
  }
  return telemetry;
}

function createTelemetryPill(label, value) {
  const pill = document.createElement("span");
  pill.className = "telemetry-pill";
  const strong = document.createElement("strong");
  strong.textContent = `${label} `;
  pill.append(strong, document.createTextNode(value));
  return pill;
}

function createMatchCard(match, matchList) {
  const issue = match.issue;
  const card = document.createElement("article");
  card.className = "match-card";

  const top = document.createElement("div");
  top.className = "match-card-top";
  const title = document.createElement("div");
  const safeUrl = safeIssueUrl(issue.html_url);
  const titleText = `${issue.title || "Untitled issue"} `;
  if (safeUrl) {
    const link = document.createElement("a");
    link.className = "issue-title";
    link.href = safeUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = titleText;
    title.append(link);
  } else {
    const text = document.createElement("span");
    text.className = "issue-title";
    text.textContent = titleText;
    title.append(text);
  }
  const number = document.createElement("span");
  number.className = "issue-number";
  number.textContent = `#${issue.number}`;
  title.append(number);

  const dismiss = document.createElement("button");
  dismiss.className = "dismiss-button";
  dismiss.type = "button";
  dismiss.textContent = "Dismiss";
  dismiss.setAttribute("aria-label", `Dismiss ${issue.repo_full_name} issue ${issue.number}`);
  dismiss.addEventListener("click", async () => {
    dismiss.disabled = true;
    try {
      await requestJson(`/api/v1/profiles/${encodeURIComponent(sessionKey)}/dismiss`, {
        method: "POST",
        body: JSON.stringify({ issue_id: issue.id, reason: null }),
      });
      card.classList.add("is-removing");
      window.setTimeout(() => {
        card.remove();
        if (!matchList.childElementCount) {
          matchList.remove();
        }
      }, 190);
    } catch (error) {
      dismiss.disabled = false;
      showError(`Could not dismiss this issue: ${error.message}`);
    }
  });
  top.append(title, dismiss);

  const repoLine = document.createElement("div");
  repoLine.className = "repo-line";
  const repo = document.createElement("span");
  repo.className = "repo-badge";
  repo.textContent = issue.repo_full_name;
  repoLine.append(repo);
  const badges = document.createElement("div");
  badges.className = "match-badges";
  if (issue.primary_language) {
    badges.append(createPill(issue.primary_language, "meta-pill"));
  }
  if (issue.program_tags?.some((tag) => tag.toLocaleLowerCase() === "gsoc")) {
    badges.append(createPill("GSoC", "meta-pill gsoc-pill"));
  }
  badges.append(createMaintainerIndicator(issue.maintainer_activity_score));
  repoLine.append(badges);

  const labels = document.createElement("div");
  labels.className = "issue-labels";
  for (const labelText of issue.labels || []) {
    labels.append(createPill(labelText, "label-pill"));
  }

  const reason = document.createElement("p");
  reason.className = "match-reason";
  reason.textContent = match.match_reason;

  const scores = document.createElement("details");
  scores.className = "score-details";
  const summary = document.createElement("summary");
  summary.textContent = "Score details";
  const scoreGrid = document.createElement("div");
  scoreGrid.className = "score-grid";
  const scoreValues = issue.scores || {};
  for (const [label, value] of [
    ["RRF", scoreValues.rrf_score],
    ["Maintainer", scoreValues.maintainer_score],
    ["Final", scoreValues.final_score],
  ]) {
    const item = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = `${label} `;
    item.append(strong, document.createTextNode(formatScore(value)));
    scoreGrid.append(item);
  }
  scores.append(summary, scoreGrid);
  card.append(top, repoLine);
  if (labels.childElementCount) {
    card.append(labels);
  }
  card.append(reason, scores);
  return card;
}

function safeIssueUrl(value) {
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : null;
  } catch {
    return null;
  }
}

function createPill(text, className) {
  const pill = document.createElement("span");
  pill.className = className;
  pill.textContent = text;
  return pill;
}

function createMaintainerIndicator(value) {
  const score = Math.max(0, Math.min(1, Number(value) || 0));
  const wrapper = document.createElement("span");
  wrapper.className = "maintainer";
  wrapper.setAttribute("aria-label", `Maintainer activity ${Math.round(score * 100)} percent`);
  const track = document.createElement("span");
  track.className = "maintainer-track";
  const fill = document.createElement("span");
  fill.className = "maintainer-fill";
  fill.style.width = `${Math.round(score * 100)}%`;
  track.append(fill);
  wrapper.append(track, document.createTextNode(`Maintainer ${Math.round(score * 100)}%`));
  return wrapper;
}

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(2) : "—";
}

function appendLoadingSkeleton() {
  const skeleton = document.createElement("div");
  skeleton.className = "loading-skeleton";
  skeleton.setAttribute("aria-label", "Scout is searching");
  const avatar = document.createElement("span");
  avatar.className = "skeleton-avatar";
  const lines = document.createElement("span");
  lines.className = "skeleton-lines";
  lines.append(document.createElement("span"), document.createElement("span"));
  skeleton.append(avatar, lines);
  elements.chatLog.append(skeleton);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  return skeleton;
}

async function sendMessage(text) {
  const message = text.trim();
  if (message.length < 2) {
    return;
  }
  clearError();
  appendMessage("user", message);
  elements.sendButton.disabled = true;
  const skeleton = appendLoadingSkeleton();
  try {
    const response = await requestJson("/api/v1/chat", {
      method: "POST",
      body: JSON.stringify({
        session_key: sessionKey,
        message,
        limit: 5,
        prioritize_gsoc: elements.prioritizeGSoC.checked,
      }),
    });
    skeleton.remove();
    appendResponse(response);
    preferences = response.preferences || preferences;
    renderPreferences();
  } catch (error) {
    skeleton.remove();
    showError(`Scout could not complete that search: ${error.message}`);
  } finally {
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
  }
}

async function loadHistory() {
  elements.chatLog.replaceChildren();
  try {
    const history = await requestJson(
      `/api/v1/chat/${encodeURIComponent(sessionKey)}/history`,
    );
    for (const turn of history.turns || []) {
      const entry = document.createElement("article");
      entry.className = "chat-turn";
      entry.append(
        createMessage("user", turn.user_message),
        createMessage("assistant", turn.assistant_message),
      );
      elements.chatLog.append(entry);
    }
    if (!history.turns?.length) {
      showWelcome();
    }
  } catch (error) {
    showError(`Could not load chat history: ${error.message}`);
    showWelcome();
  }
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function showWelcome() {
  const welcome = document.createElement("div");
  welcome.id = "welcome-card";
  welcome.className = "welcome-card";
  const icon = document.createElement("span");
  icon.className = "welcome-orbit";
  icon.setAttribute("aria-hidden", "true");
  icon.textContent = "✦";
  const heading = document.createElement("h3");
  heading.textContent = "What would you like to work on?";
  const description = document.createElement("p");
  description.textContent = "Tell Scout about your interests, preferred languages, or the kind of issue you want to tackle.";
  welcome.append(icon, heading, description);
  elements.chatLog.append(welcome);
}

elements.chatForm.addEventListener("submit", (event) => {
  event.preventDefault();
  const message = elements.messageInput.value;
  elements.messageInput.value = "";
  elements.messageInput.style.height = "auto";
  void sendMessage(message);
});

elements.messageInput.addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) {
    event.preventDefault();
    elements.chatForm.requestSubmit();
  }
});

elements.messageInput.addEventListener("input", () => {
  elements.messageInput.style.height = "auto";
  elements.messageInput.style.height = `${Math.min(elements.messageInput.scrollHeight, 140)}px`;
});

document.getElementById("new-session").addEventListener("click", async () => {
  setSessionKey(createSessionKey());
  preferences = structuredClone(EMPTY_PROFILE);
  renderPreferences();
  elements.chatLog.replaceChildren();
  clearError();
  await Promise.all([loadPreferences(), loadHistory()]);
});

for (const chip of document.querySelectorAll("[data-prompt]")) {
  chip.addEventListener("click", () => {
    const prompt = chip.dataset.prompt;
    if (prompt) {
      elements.messageInput.value = prompt;
      void sendMessage(prompt);
    }
  });
}

elements.sidebarToggle.addEventListener("click", () => {
  const isOpen = elements.sidebar.classList.toggle("is-open");
  elements.sidebarToggle.setAttribute("aria-expanded", String(isOpen));
});

async function initialize() {
  setSessionKey(sessionKey);
  await monitorHealth();
  await Promise.all([loadPreferences(), loadHistory()]);
}

void initialize();
