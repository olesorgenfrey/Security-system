"use strict";

const filters = document.querySelector("#event-filters");
const eventsTable = document.querySelector("#events-table");
const alertsTable = document.querySelector("#alerts-table");
const pollingToggle = document.querySelector("#toggle-polling");
const pollingState = document.querySelector("#polling-state");
const clock = document.querySelector("#current-time");
const activeRequests = new WeakMap();

let filterTimer;
let pollingPaused = false;

function setText(id, value) {
  const element = document.getElementById(id);
  if (element) {
    element.textContent = String(value);
  }
}

function localizeTimes(root) {
  const timeFormat = new Intl.DateTimeFormat("de-DE", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
  const titleFormat = new Intl.DateTimeFormat("de-DE", {
    dateStyle: "medium",
    timeStyle: "long",
  });

  for (const element of root.querySelectorAll("time[datetime]")) {
    const timestamp = element.getAttribute("datetime");
    if (!timestamp) continue;
    const utcTimestamp = /(?:Z|[+-]\d{2}:\d{2})$/i.test(timestamp) ? timestamp : `${timestamp}Z`;
    const date = new Date(utcTimestamp);
    if (Number.isNaN(date.getTime())) continue;
    element.textContent = timeFormat.format(date);
    element.title = titleFormat.format(date);
  }
}

function updateMetrics() {
  const eventRows = eventsTable?.querySelectorAll("tbody tr.data-row") ?? [];
  const alertRows = alertsTable?.querySelectorAll("tbody tr.data-row") ?? [];
  const hosts = new Set();
  for (const row of eventRows) {
    if (row.dataset.host) hosts.add(row.dataset.host);
  }
  let criticalAlerts = 0;
  for (const row of alertRows) {
    if (Number(row.dataset.severity) >= 80) criticalAlerts += 1;
  }

  const eventCount = eventRows.length;
  const alertCount = alertRows.length;
  setText("top-event-count", eventCount);
  setText("top-alert-count", alertCount);
  setText("kpi-event-count", eventCount);
  setText("kpi-host-count", hosts.size);
  setText("kpi-alert-count", alertCount);
  setText("kpi-critical-count", criticalAlerts);
  setText("alerts-panel-count", `Neueste ${alertCount} Einträge`);

  document.getElementById("kpi-critical-card")?.classList.toggle("critical", criticalAlerts > 0);
  const navBadge = document.getElementById("nav-alert-count");
  if (navBadge) {
    navBadge.textContent = String(alertCount);
    navBadge.hidden = alertCount === 0;
  }

  const banner = document.getElementById("alert-banner");
  banner?.classList.toggle("clear", alertCount === 0);
  setText("alert-banner-icon", alertCount > 0 ? "▲" : "●");
  setText(
    "alert-banner-title",
    alertCount > 0
      ? `${alertCount} ${alertCount === 1 ? "offener Alert" : "offene Alerts"} angezeigt`
      : "Keine offenen Alerts",
  );
  setText(
    "alert-banner-detail",
    alertCount > 0
      ? `davon ${criticalAlerts} kritisch · sortiert nach Eingangszeit`
      : "Der aktuelle Alert-Feed ist leer.",
  );
  const bannerLink = document.getElementById("alert-banner-link");
  if (bannerLink) bannerLink.hidden = alertCount === 0;
}

function updateClock() {
  if (clock) {
    clock.textContent = new Date().toLocaleTimeString("de-DE", { hour12: false });
  }
}

function filterQuery() {
  const query = new URLSearchParams();
  if (!filters) {
    return query;
  }
  for (const [name, value] of new FormData(filters).entries()) {
    if (typeof value === "string" && value !== "") {
      query.set(name, value);
    }
  }
  return query;
}

function replaceFromPartial(target, url) {
  activeRequests.get(target)?.abort();
  const request = new AbortController();
  activeRequests.set(target, request);
  target.setAttribute("aria-busy", "true");

  void (async () => {
    try {
      const response = await fetch(url, {
        cache: "no-store",
        credentials: "same-origin",
        headers: { "X-Requested-With": "fetch" },
        signal: request.signal,
      });
      if (!response.ok) {
        throw new Error(`Dashboard refresh returned ${response.status}`);
      }
      target.innerHTML = await response.text();
      localizeTimes(target);
      updateMetrics();
      target.classList.remove("refresh-failed");
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        target.classList.add("refresh-failed");
        console.error("Dashboard refresh failed", error);
      }
    } finally {
      if (activeRequests.get(target) === request) {
        activeRequests.delete(target);
        target.removeAttribute("aria-busy");
      }
    }
  })();
}

function refreshEvents({ updateLocation = false, force = false } = {}) {
  if (!filters || !eventsTable || document.hidden || (pollingPaused && !force)) {
    return;
  }
  const query = filterQuery().toString();
  if (updateLocation) {
    window.history.replaceState(null, "", query ? `/?${query}` : "/");
  }
  replaceFromPartial(eventsTable, `/partials/events${query ? `?${query}` : ""}`);
}

function refreshAlerts() {
  if (!alertsTable || document.hidden || pollingPaused) {
    return;
  }
  replaceFromPartial(alertsTable, "/partials/alerts");
}

function setPollingPaused(paused) {
  pollingPaused = paused;
  pollingToggle?.setAttribute("aria-pressed", String(paused));
  if (pollingToggle) {
    pollingToggle.textContent = paused ? "▶" : "Ⅱ";
    pollingToggle.title = paused ? "Live-Feed fortsetzen" : "Live-Feed pausieren";
    pollingToggle.setAttribute("aria-label", pollingToggle.title);
  }
  if (pollingState) {
    pollingState.classList.toggle("paused", paused);
    const stateLabel = pollingState.querySelector("span:last-child");
    if (stateLabel) {
      stateLabel.textContent = paused ? "AUTO-REFRESH · PAUSIERT" : "AUTO-REFRESH · 3 S";
    }
  }
  if (paused) {
    if (eventsTable) activeRequests.get(eventsTable)?.abort();
    if (alertsTable) activeRequests.get(alertsTable)?.abort();
  } else {
    refreshEvents();
    refreshAlerts();
  }
}

if (filters) {
  filters.addEventListener("submit", (event) => {
    event.preventDefault();
    refreshEvents({ updateLocation: true, force: true });
  });
  filters.addEventListener("input", () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => {
      refreshEvents({ updateLocation: true, force: true });
    }, 300);
  });
  filters.addEventListener("reset", () => {
    window.clearTimeout(filterTimer);
    filterTimer = window.setTimeout(() => {
      refreshEvents({ updateLocation: true, force: true });
    });
  });
}

pollingToggle?.addEventListener("click", () => setPollingPaused(!pollingPaused));
document.addEventListener("visibilitychange", () => {
  if (!document.hidden && !pollingPaused) {
    refreshEvents();
    refreshAlerts();
  }
});

updateClock();
localizeTimes(document);
updateMetrics();
window.setInterval(updateClock, 1000);
window.setInterval(refreshEvents, 3000);
window.setInterval(refreshAlerts, 5000);
