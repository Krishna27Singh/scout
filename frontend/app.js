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

const LANGUAGE_COLORS = {
  python: "#3572A5",
  "c++": "#f34b7d",
  javascript: "#f1e05a",
  typescript: "#3178c6",
  rust: "#dea584",
  go: "#00ADD8",
};
const CHAT_REQUEST_TIMEOUT_MS = 90_000;

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
  if (response.ok) {
    updateHealth(true);
  }
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
  elements.healthLabel.textContent = healthy ? "Online" : waking ? "Waking up" : "Unavailable";
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
    elements.saveStatus.textContent = "Synced";
    elements.saveStatus.classList.remove("is-error");
  } catch (error) {
    if (error.status !== 404) {
      showError("Could not load preferences. You can still chat; try refreshing the preferences later.");
    }
    preferences = structuredClone(EMPTY_PROFILE);
    elements.saveStatus.textContent = "Not synced";
  }
  renderPreferences();
}

async function savePreferences() {
  elements.saveStatus.textContent = "Saving…";
  elements.saveStatus.classList.remove("is-error");
  try {
    preferences = await requestJson(`/api/v1/profiles/${encodeURIComponent(sessionKey)}`, {
      method: "PUT",
      body: JSON.stringify(preferences),
    });
    renderPreferences();
    elements.saveStatus.textContent = "Synced";
  } catch (error) {
    elements.saveStatus.textContent = "Save failed";
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

function createIcon(className, paths) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 16 16");
  svg.setAttribute("aria-hidden", "true");
  svg.classList.add(className);
  for (const definition of paths) {
    const path = document.createElementNS("http://www.w3.org/2000/svg", "path");
    path.setAttribute("d", definition);
    path.setAttribute("fill", "currentColor");
    svg.append(path);
  }
  return svg;
}

const ISSUE_ICON_PATH = "M8 1.5a6.5 6.5 0 1 0 0 13 6.5 6.5 0 0 0 0-13Zm0 1.25a5.25 5.25 0 1 1 0 10.5 5.25 5.25 0 0 1 0-10.5Zm-.75 2.5a.75.75 0 0 1 1.5 0v2h1.5a.75.75 0 0 1 0 1.5H8a.75.75 0 0 1-.75-.75v-2.75Z";
const COMMENT_ICON_PATH = "M2.5 2.75A1.75 1.75 0 0 1 4.25 1h7.5A1.75 1.75 0 0 1 13.5 2.75v6.5A1.75 1.75 0 0 1 11.75 11H8l-3.1 2.33A.75.75 0 0 1 3.7 12.7V11h-.45A1.75 1.75 0 0 1 1.5 9.25v-6.5Zm1.75-.25a.25.25 0 0 0-.25.25v6.5c0 .14.11.25.25.25h1.2a.75.75 0 0 1 .75.75v.95l1.8-1.35a.75.75 0 0 1 .45-.15h3.3a.25.25 0 0 0 .25-.25v-6.5a.25.25 0 0 0-.25-.25h-7.5Z";

function createQueryRow(text) {
  const row = document.createElement("div");
  row.className = "query-row";
  row.append(createIcon("query-icon", [COMMENT_ICON_PATH]));
  const query = document.createElement("span");
  query.textContent = text || "";
  row.append(query);
  return row;
}

function createAssistantHistoryRow(text) {
  const row = document.createElement("div");
  row.className = "history-response";
  row.append(createIcon("open-issue-icon", [ISSUE_ICON_PATH]));
  const message = document.createElement("p");
  message.textContent = text || "";
  row.append(message);
  return row;
}

function createTurn(userMessage) {
  document.getElementById("welcome-card")?.remove();
  const turn = document.createElement("article");
  turn.className = "chat-turn";
  turn.append(createQueryRow(userMessage));
  elements.chatLog.append(turn);
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  return turn;
}

function appendResponse(turn, response) {
  turn.querySelector(".chat-inline-loading")?.remove();
  turn.append(createResponseBox(response));
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
}

function createResponseBox(response) {
  const matches = response.matches || [];
  const box = document.createElement("section");
  box.className = "match-box";

  const header = document.createElement("header");
  header.className = "box-header";

  const summary = document.createElement("div");
  summary.className = "box-summary";
  summary.append(createIcon("open-issue-icon", [ISSUE_ICON_PATH]));
  const summaryText = document.createElement("div");
  summaryText.className = "summary-text";
  const count = document.createElement("span");
  count.className = "summary-count";
  count.dataset.count = String(matches.length);
  count.textContent = `${matches.length} open ${matches.length === 1 ? "match" : "matches"}`;
  summaryText.append(count, document.createTextNode(response.assistant_message || ""));
  summary.append(summaryText);

  const tools = document.createElement("div");
  tools.className = "box-tools";
  const latency = Math.max(0, Number(response.latency_ms) || 0) / 1000;
  const telemetry = document.createElement("span");
  telemetry.className = "telemetry";
  telemetry.textContent = `${response.provider_used || "unknown"} · ${latency.toFixed(1)}s`;
  tools.append(telemetry);

  const traceItems = response.tool_trace || [];
  if (traceItems.length) {
    const trace = document.createElement("details");
    trace.className = "trace-details";
    const traceSummary = document.createElement("summary");
    traceSummary.textContent = "Trace";
    const traceList = document.createElement("span");
    traceList.className = "trace-list";
    for (const item of traceItems) {
      const pill = document.createElement("span");
      pill.className = "trace-pill";
      pill.textContent = item;
      traceList.append(pill);
    }
    trace.append(traceSummary, traceList);
    tools.append(trace);
  }

  if (response.hydration?.triggered === true) {
    const repos = response.hydration.repos_synced?.join(", ")
      || response.hydration.scope
      || "target scope";
    const badge = document.createElement("span");
    badge.className = "hydration-badge";
    badge.textContent = `Hydrated live · ${repos} · +${response.hydration.issues_added || 0} issues`;
    tools.append(badge);
  }

  header.append(summary, tools);
  box.append(header);

  if (matches.length) {
    const list = document.createElement("div");
    list.className = "match-list";
    for (const match of matches) {
      list.append(createMatchCard(match, list, count));
    }
    box.append(list);
  }
  return box;
}

function createMatchCard(match, matchList, countElement) {
  const issue = match.issue;
  const card = document.createElement("article");
  card.className = "match-card";
  card.append(createIcon("row-issue-icon", [ISSUE_ICON_PATH]));

  const content = document.createElement("div");
  content.className = "issue-content";
  const top = document.createElement("div");
  top.className = "match-card-top";

  const primary = document.createElement("div");
  primary.className = "issue-primary";
  const safeUrl = safeIssueUrl(issue.html_url);
  const titleText = issue.title || "Untitled issue";
  if (safeUrl) {
    const link = document.createElement("a");
    link.className = "issue-title";
    link.href = safeUrl;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.textContent = titleText;
    primary.append(link);
  } else {
    const text = document.createElement("span");
    text.className = "issue-title";
    text.textContent = titleText;
    primary.append(text);
  }

  const number = document.createElement("span");
  number.className = "issue-number";
  number.textContent = `#${issue.number}`;
  primary.append(number);
  const labels = document.createElement("span");
  labels.className = "issue-labels";
  if (issue.program_tags?.some((tag) => tag.toLocaleLowerCase() === "gsoc")) {
    labels.append(createPill("GSoC", "label-pill gsoc-pill"));
  }
  for (const labelText of issue.labels || []) {
    labels.append(createPill(labelText, "label-pill"));
  }
  primary.append(labels);

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
        const remaining = Math.max(0, Number(countElement.dataset.count) - 1);
        countElement.dataset.count = String(remaining);
        countElement.textContent = `${remaining} open ${remaining === 1 ? "match" : "matches"}`;
        if (!matchList.childElementCount) {
          matchList.remove();
        }
      }, 170);
    } catch (error) {
      dismiss.disabled = false;
      showError(`Could not dismiss this issue: ${error.message}`);
    }
  });
  top.append(primary, dismiss);

  const metadata = document.createElement("div");
  metadata.className = "issue-meta";
  const repo = document.createElement("span");
  repo.className = "repo-badge";
  repo.textContent = `${issue.repo_full_name}#${issue.number}`;
  metadata.append(repo);

  if (issue.primary_language) {
    const language = document.createElement("span");
    language.className = "language-meta";
    const dot = document.createElement("span");
    dot.className = "language-dot";
    const color = LANGUAGE_COLORS[issue.primary_language.toLocaleLowerCase()];
    if (color) {
      dot.style.backgroundColor = color;
    }
    const languageName = document.createElement("span");
    languageName.textContent = issue.primary_language;
    language.append(dot, languageName);
    metadata.append(language);
  }

  const score = Math.max(0, Math.min(1, Number(issue.maintainer_activity_score) || 0));
  const maintainer = document.createElement("span");
  maintainer.className = "maintainer";
  maintainer.textContent = `Maintainer ${Math.round(score * 100)}%`;
  metadata.append(maintainer);
  metadata.append(createScoreDetails(issue.scores || {}));

  const reason = document.createElement("p");
  reason.className = "match-reason";
  reason.textContent = match.match_reason || "";

  content.append(top, metadata, reason);
  card.append(content);
  return card;
}

function createScoreDetails(scoreValues) {
  const details = document.createElement("details");
  details.className = "score-details";
  const summary = document.createElement("summary");
  summary.textContent = "Scores";
  const grid = document.createElement("span");
  grid.className = "score-grid";
  for (const [label, value] of [
    ["RRF", scoreValues.rrf_score],
    ["Maintainer", scoreValues.maintainer_score],
    ["Final", scoreValues.final_score],
  ]) {
    const item = document.createElement("span");
    const strong = document.createElement("strong");
    strong.textContent = `${label} `;
    item.append(strong, document.createTextNode(formatScore(value)));
    grid.append(item);
  }
  details.append(summary, grid);
  return details;
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

function formatScore(value) {
  const score = Number(value);
  return Number.isFinite(score) ? score.toFixed(2) : "—";
}

function createLoadingRow() {
  const row = document.createElement("div");
  row.className = "chat-inline-loading";
  row.setAttribute("role", "status");
  const spinner = document.createElement("span");
  spinner.className = "loading-spinner";
  spinner.setAttribute("aria-hidden", "true");
  const message = document.createElement("span");
  message.textContent = "Searching issues (and syncing repository if needed)…";
  row.append(spinner, message);
  return row;
}

function createInlineChatError(message, onRetry) {
  const row = document.createElement("div");
  row.className = "chat-inline-error";
  row.setAttribute("role", "alert");
  row.setAttribute("aria-live", "assertive");
  const errorMessage = document.createElement("p");
  errorMessage.textContent = `Search failed: ${message}`;
  const retry = document.createElement("button");
  retry.className = "button button-secondary";
  retry.type = "button";
  retry.textContent = "Retry";
  retry.addEventListener("click", onRetry);
  row.append(errorMessage, retry);
  return row;
}

async function submitChatMessage(message, turn, previousStatus = null) {
  const loading = createLoadingRow();
  if (previousStatus) {
    previousStatus.replaceWith(loading);
  } else {
    turn.append(loading);
  }
  loading.scrollIntoView({ block: "nearest" });
  elements.chatLog.scrollTop = elements.chatLog.scrollHeight;
  elements.sendButton.disabled = true;
  const controller = new AbortController();
  const timeout = window.setTimeout(
    () => controller.abort(),
    CHAT_REQUEST_TIMEOUT_MS,
  );
  try {
    const response = await requestJson("/api/v1/chat", {
      method: "POST",
      signal: controller.signal,
      body: JSON.stringify({
        session_key: sessionKey,
        message,
        limit: 5,
        prioritize_gsoc: elements.prioritizeGSoC.checked,
      }),
    });
    appendResponse(turn, response);
    preferences = response.preferences || preferences;
    renderPreferences();
  } catch (error) {
    let errorMessage;
    if (controller.signal.aborted) {
      errorMessage = "Search timed out after 90 seconds.";
    } else {
      errorMessage = error instanceof Error ? error.message : String(error);
    }
    const errorRow = createInlineChatError(errorMessage, () => {
      void submitChatMessage(message, turn, errorRow);
    });
    loading.replaceWith(errorRow);
    errorRow.scrollIntoView({ block: "nearest" });
  } finally {
    window.clearTimeout(timeout);
    elements.sendButton.disabled = false;
    elements.messageInput.focus();
  }
}

async function sendMessage(text) {
  const message = text.trim();
  if (message.length < 2) {
    return;
  }
  clearError();
  const turn = createTurn(message);
  await submitChatMessage(message, turn);
}

async function loadHistory() {
  elements.chatLog.replaceChildren();
  try {
    const history = await requestJson(
      `/api/v1/chat/${encodeURIComponent(sessionKey)}/history`,
    );
    for (const turnData of history.turns || []) {
      const turn = document.createElement("article");
      turn.className = "chat-turn";
      turn.append(
        createQueryRow(turnData.user_message),
        createAssistantHistoryRow(turnData.assistant_message),
      );
      elements.chatLog.append(turn);
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
  welcome.append(createIcon("welcome-icon", [ISSUE_ICON_PATH]));
  const heading = document.createElement("h2");
  heading.textContent = "Find an issue to work on";
  const description = document.createElement("p");
  description.textContent = "Search open-source issues by language, project, or the kind of work you want to do.";
  welcome.append(heading, description);
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

for (const link of document.querySelectorAll("[data-prompt]")) {
  link.addEventListener("click", () => {
    const prompt = link.dataset.prompt;
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
