const $ = (s) => document.querySelector(s);
const copy = await fetch("/copy.json").then((r) => r.json());
document
  .querySelectorAll("[data-copy]")
  .forEach((el) => (el.textContent = copy[el.dataset.copy] || el.dataset.copy));
let items = [],
  tab = "pending",
  source = "all",
  selected = null,
  online = false,
  busy = false,
  snapshot = "",
  modalId = null;
const pinned = new Set();
function node(tag, cls, text) {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
}
function button(text, cls, action) {
  const b = node("button", cls, text);
  b.type = "button";
  b.addEventListener("click", action);
  return b;
}
async function api(path, body) {
  const response = await fetch(path, {
    method: body === undefined ? "GET" : "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "X-TapGate": "1" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const data = await response.json();
  if (!response.ok)
    throw Object.assign(new Error(data.error || String(response.status)), {
      status: response.status,
    });
  return data;
}
function connection(value) {
  online = value;
  $("#connection").classList.toggle("offline", !value);
  $("#connection").replaceChildren(
    node("i"),
    document.createTextNode(value ? copy.connected : copy.offline),
  );
}
function stateText(item) {
  return copy[item.state] || item.state;
}
function metadata(item) {
  const row = node("div", "card-top");
  row.append(
    node(
      "span",
      "source-icon " + item.source,
      item.source === "codex" ? "⌘" : "✳",
    ),
    node("span", "source-name", copy[item.source]),
    node("span", "host", item.host),
  );
  return row;
}
function attachActions(item, container, surface = "browser") {
  if (item.informational && item.state === "notice") {
    container.append(node("small", "phone-hint", "元のターミナルで対応"));
    return;
  }
  if (item.state !== "pending") {
    container.append(node("span", "state-chip " + item.state, stateText(item)));
    if (item.state === "approved" || item.state === "denied")
      container.append(
        node(
          "span",
          "delivery",
          item.delivered ? "回答受信済み" : "回答の受信待ち",
        ),
      );
    return;
  }
  if (item.informational) {
    container.append(node("small", "phone-hint", "元のターミナルで対応"));
    return;
  }
  const deny = button(copy.deny, "deny", () => decide(item, "denied", surface));
  deny.disabled = busy || !online || !item.live;
  container.append(deny);
  let approve;
  if (item.phone_required && surface === "watch")
    approve = button(copy.openPhone, "phone-action", () => openDetail(item.id));
  else if (item.phone_required && surface === "browser" && modalId !== item.id)
    approve = button(copy.openPhone, "phone-action", () => openDetail(item.id));
  else
    approve = button("✓  " + copy.approve, "approve", () =>
      decide(item, "approved", surface),
    );
  approve.disabled = busy || !online || !item.live;
  container.append(approve);
}
function render() {
  const pending = items.filter((x) => x.state === "pending").length;
  $("#pending-count").textContent = pending;
  $("#nav-count").textContent = pending;
  $("#requests").hidden = tab === "settings";
  $("#settings-panel").hidden = tab !== "settings";
  $("#list-label").textContent =
    tab === "history"
      ? "RECENT ACTIVITY"
      : tab === "settings"
        ? "PREFERENCES"
        : "INBOX";
  document
    .querySelectorAll("[data-tab]")
    .forEach((b) => b.classList.toggle("active", b.dataset.tab === tab));
  document
    .querySelectorAll("[data-source]")
    .forEach((b) => b.classList.toggle("active", b.dataset.source === source));
  const visible = items.filter(
    (x) =>
      (tab === "history"
        ? x.state !== "pending"
        : x.state === "pending" || x.state === "notice" || pinned.has(x.id)) &&
      (source === "all" || x.source === source),
  );
  const list = $("#requests");
  list.replaceChildren();
  if (!visible.length) {
    const empty = node("div", "empty glass");
    empty.append(
      node("div", "empty-icon", "✓"),
      node("h2", "", tab === "history" ? copy.noHistory : copy.emptyTitle),
      node("p", "", copy.emptyBody),
    );
    list.append(empty);
  }
  visible.forEach((item, index) => {
    const card = node(
      "article",
      "request-card glass" + (selected === item.id ? " selected" : ""),
    );
    card.dataset.id = item.id;
    card.append(
      metadata(item),
      node("h2", "", item.task),
      node("code", "operation", item.operation),
    );
    const bottom = node("div", "card-bottom");
    bottom.append(
      button(copy.details + " ↗", "details", () => openDetail(item.id)),
    );
    attachActions(item, bottom);
    card.append(bottom);
    if (item.phone_required && item.state === "pending")
      card.append(node("p", "phone-hint", "◈  " + copy.phoneRequired));
    card.addEventListener("click", (e) => {
      if (e.target.closest("button")) return;
      selected = item.id;
      render();
    });
    list.append(card);
  });
  renderWatch();
  if (modalId) renderDetail();
}
function renderWatch() {
  const content = $("#watch-content");
  content.replaceChildren();
  content.className = "watch-content";
  const item = items.find((x) => x.id === selected);
  if (!item) {
    content.append(
      node("div", "watch-complete", "✓"),
      node("h3", "", copy.emptyTitle),
    );
    return;
  }
  if (item.informational && item.state === "notice") {
    content.append(
      node("h3", "", item.task),
      node("p", "", "元のターミナルで対応"),
    );
    return;
  }
  if (item.state !== "pending") {
    const result = node("div", "watch-complete");
    result.append(
      node(
        "span",
        "complete-check",
        item.state === "approved" ? "✓" : item.state === "denied" ? "−" : "◷",
      ),
      node("strong", "", stateText(item)),
      node("small", "", item.task),
      node("small", "", item.delivered ? "回答受信済み" : copy.watchHint),
    );
    result.append(
      button(copy.next + " →", "watch-next", () => {
        const next = items.find(
          (x) => x.state === "pending" && x.id !== selected,
        );
        selected = next?.id || null;
        render();
      }),
    );
    content.append(result);
    return;
  }
  content.append(
    node("div", "watch-source", copy[item.source] + " · " + item.host),
    node("h3", "", item.task),
    node("code", "", item.phone_required ? copy.phoneRequired : item.operation),
  );
  const actions = node("div", "watch-actions");
  attachActions(item, actions, "watch");
  content.append(actions);
}
function openDetail(id) {
  modalId = id;
  selected = id;
  renderDetail();
  $("#detail-dialog").showModal();
}
function renderDetail() {
  const item = items.find((x) => x.id === modalId);
  if (!item) return;
  const detail = $("#detail-content");
  detail.replaceChildren(
    metadata(item),
    node("h2", "", item.task),
    node("pre", "", item.operation),
  );
  if (item.reason) detail.append(node("pre", "", item.reason));
  const actions = node("div", "card-bottom");
  attachActions(item, actions, "phone");
  detail.append(actions);
}
async function decide(item, decision, surface) {
  if (busy) return;
  busy = true;
  $("#status").textContent = copy.sending;
  render();
  try {
    const result = await api("/api/requests/" + item.id + "/decision", {
      decision,
      surface,
      version: item.version,
      payload_hash: item.payload_hash,
    });
    items = items.map((x) => (x.id === result.id ? result : x));
    pinned.add(result.id);
    selected = result.id;
    $("#status").textContent = stateText(result);
    if (navigator.vibrate) navigator.vibrate(30);
  } catch (error) {
    $("#status").textContent = error.message;
    if (error.status === undefined) connection(false);
    await refresh(false);
  } finally {
    busy = false;
    render();
  }
}
async function refresh(showSpin = true) {
  if (showSpin) $("#refresh").classList.add("spinning");
  try {
    const wasOnline = online;
    const data = await api("/api/inbox");
    connection(true);
    $("#pairing").hidden = true;
    $("#workspace").hidden = false;
    $("#demo-banner").hidden = !data.demo;
    const changed = JSON.stringify(data.requests) !== snapshot;
    snapshot = JSON.stringify(data.requests);
    items = data.requests;
    if (selected === null)
      selected = items.find((x) => x.state === "pending")?.id || null;
    $("#push-state").textContent =
      data.push.map((x) => x.state + ": " + x.count).join(" · ") ||
      "APNs: 端末未登録";
    if (changed || !wasOnline || !$("#requests").children.length) render();
  } catch (error) {
    connection(false);
    if (error.status === 401) {
      $("#pairing").hidden = false;
      $("#workspace").hidden = true;
    } else {
      $("#status").textContent = error.message;
      render();
    }
  } finally {
    $("#refresh").classList.remove("spinning");
  }
}
$("#pair-form").addEventListener("submit", async (e) => {
  e.preventDefault();
  const b = e.target.querySelector("button");
  b.disabled = true;
  try {
    await api("/api/pair", { code: $("#code").value, name: "Browser" });
    $("#code").value = "";
    $("#pair-error").textContent = "";
    await refresh();
  } catch (error) {
    $("#pair-error").textContent = error.message;
  } finally {
    b.disabled = false;
  }
});
$("#refresh").addEventListener("click", () => refresh());
$("#close-detail").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("close", () => {
  modalId = null;
  render();
});
$("#logout").addEventListener("click", async () => {
  await api("/api/logout", {});
  location.reload();
});
document.querySelectorAll("[data-tab]").forEach((b) =>
  b.addEventListener("click", () => {
    tab = b.dataset.tab;
    pinned.clear();
    render();
  }),
);
document.querySelectorAll("[data-source]").forEach((b) =>
  b.addEventListener("click", () => {
    source = b.dataset.source;
    render();
  }),
);
$("#watch-time").textContent = new Intl.DateTimeFormat("ja-JP", {
  hour: "numeric",
  minute: "2-digit",
}).format(new Date());
await refresh();
setInterval(() => {
  if (!busy) refresh(false);
}, 3000);
