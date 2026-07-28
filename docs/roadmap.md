# Roadmap — Aegis

Inkrementeller Aufbau. Jede Phase liefert etwas **Lauffähiges & Nützliches**.
Wir bauen von „beobachten" zu „erkennen" zu „reagieren" — die riskante
Automatik (SOAR) kommt bewusst zuletzt.

Legende: 🔲 offen · 🚧 in Arbeit · ✅ fertig

---

## Phase 0 — Grundgerüst  ✅
**Ziel:** Reproduzierbares Projekt-Setup, an dem alle weiteren Teile andocken.

- [x] Projektstruktur & Python-Setup (uv, Linting/ruff, Typing/mypy)
- [x] Gemeinsames **Event-Schema** (ECS-angelehnt) als Datenmodell
- [x] PostgreSQL + Migrationen (SQLAlchemy/Alembic)
- [x] Docker Compose mit DB, authentifiziertem/persistentem Redis, API und Workern
- [x] GitHub-Actions-CI: Lint, Typprüfung, Service-Tests, Migration-/Compose-Prüfung, Image-Build, Dependency-Scan
- [x] Konfigurations- & Scope-Konzept (welche Assets sind „in scope")
- [x] Deployment-Baseline: Pflicht-Secrets, Loopback-Ports, non-root/read-only Container und geordnete Migration

**Ergebnis:** Nach Befüllen von `.env` startet der dokumentierte
`docker compose`-Befehl ein gehärtetes Grundsystem.

---

## Phase 1 — Monitoring-MVP  ✅
**Ziel:** Events sammeln, speichern, sichtbar machen.

- [x] Host-Agent: konfigurierbares echtes Host-Log-Tailing + Prozess-/Netzwerk-Snapshot
- [x] Event Bus (Redis Streams) + Normalizer, Pending-Recovery und Dead-Letter-Stream
- [x] Events landen strukturiert in Postgres
- [x] Globaler Event-Retention-Worker
- [x] Minimal-Dashboard: gepollter Event-/Alert-Feed + Suche/Filter, geschützt per HTTP Basic
- [x] Persistente E-Mail-/Webhook-Outbox mit begrenztem Retry

**Ergebnis:** Du siehst per kurzem Polling-Intervall, was auf einem Host
passiert. Ein schlankes SIEM.

---

## Phase 2 — Detection Engine  ✅
**Ziel:** Aus Events werden aussagekräftige Alerts.

- [x] Erste Regel: Brute-Force-Erkennung (Schwellwert/Zeitfenster, nach Host und Quell-IP gruppiert)
- [x] Kuratierte, je Host deduplizierte Keyword-Regeln (neues Admin-Konto, Reverse-Shell-Muster) — echtes Sigma (pySigma) als späterer Ausbau
- [x] Anomalie-Detektor: Z-Score auf Prozess-Erstellungsrate pro Host
- [x] Severity-Scoring + MITRE-ATT&CK-Mapping (erste Regel)
- [x] Alert-Ansicht im Dashboard

**Ergebnis:** Das System meldet verdächtige Muster, nicht nur Rohdaten.

---

## Phase 3 — Vulnerability Scanning  🔲
**Ziel:** Proaktiv Schwachstellen finden.

- [ ] Scanner-Orchestrator (nmap → Asset-Discovery)
- [ ] nuclei (Web/Service-CVEs) + Trivy (Container/Deps) integrieren
- [ ] Asset-Inventar + Finding-Verwaltung (CVSS-Priorisierung)
- [ ] Geplante & Ad-hoc-Scans aus dem Dashboard
- [ ] Verknüpfung: Findings ↔ Assets ↔ Alerts

**Ergebnis:** Regelmäßige Zustandsprüfung deiner Umgebung.

---

## Phase 4 — IDS / Netzwerk-Erkennung  🔲
**Ziel:** Angriffe auf Netzwerkebene sehen.

- [ ] Suricata als Sensor einbinden (EVE-JSON → Bus)
- [ ] Optional Zeek für Protokoll-/Flow-Metadaten
- [ ] Netzwerk-Alerts in Correlation-Engine integrieren
- [ ] Angriffsketten über Host- + Netz-Events korrelieren (Incidents)

**Ergebnis:** Host- und Netzwerksicht in einem korrelierten Incident-Bild.

---

## Phase 5 — Adaptive Response (SOAR)  🔲
**Ziel:** Automatische, abgesicherte Gegenmaßnahmen. **Zuerst nur Dry-Run.**

- [ ] Playbook-Format (YAML) + Ausführungs-Engine
- [ ] Safety-Layer: Dry-Run-Default, Allow/Deny-Listen, Rate-Limit, Circuit-Breaker
- [ ] Approval-Queue im Dashboard (Mensch bestätigt kritische Aktionen)
- [ ] Erste Aktionen: IP blockieren, Prozess killen, Host isolieren — je mit **Rollback/TTL**
- [ ] Vollständiges Audit-Log jeder Aktion
- [ ] Schrittweise Freigabe: Beobachten → mit Freigabe → (für unkritische Fälle) vollautomatisch

**Ergebnis:** Das System kann selbst eingreifen — kontrolliert und reversibel.

---

## Phase 6 — Reife & Skalierung  🔲
**Ziel:** Produktionstauglich für größere/mehrere Umgebungen.

- [ ] Multi-Host / verteilte Sensoren + zentraler Core
- [ ] OpenSearch für große Event-Mengen
- [ ] ML-basierte Anomalie-Erkennung
- [ ] Rollen & Mandantenfähigkeit (für Firmennetz)
- [ ] Reporting/Compliance-Exports
- [ ] Vertiefte Härtung & Pen-Test der Plattform selbst (erste Deployment-Baseline ist umgesetzt)

---

## Priorisierungs-Logik

1. **Sichtbarkeit zuerst** (Phasen 0–2) — ohne verlässliche Daten ist alles andere wertlos.
2. **Proaktiv & Netz** (Phasen 3–4) — breiteres Erkennungsspektrum.
3. **Automatik zuletzt** (Phase 5) — erst wenn Erkennung vertrauenswürdig ist,
   darf sie Aktionen auslösen.
4. **Skalierung nach Bedarf** (Phase 6) — nur bauen, was gebraucht wird.
