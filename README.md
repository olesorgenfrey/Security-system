# Aegis — Adaptive Defensive Security Platform

> Arbeitstitel „Aegis" (griech. Schutzschild). Der Name ist frei änderbar.

Eine modulare, **rein defensive** Security-Plattform, die Monitoring/SIEM,
Intrusion Detection, Schwachstellen-Scanning und ein zentrales Dashboard
vereint — mit einer **adaptiven Response-Engine**, die auf erkannte Angriffe
mit vordefinierten, abgesicherten Gegenmaßnahmen reagiert.

## Vision

Ein einziges System, das über verschiedene Umgebungen hinweg (Heimnetz,
Server/Cloud, Web-Anwendungen, Firmennetz) Sicherheitsereignisse **sammelt**,
**erkennt**, **korreliert**, **visualisiert** und bei Bedarf **automatisch
reagiert** — mit Mensch-im-Kontrollkreis für kritische Aktionen.

## Kernbausteine

| Baustein | Aufgabe | Status |
|----------|---------|--------|
| **Collectors / Agents** | Sammeln Logs, Prozess-, Netzwerk- und Cloud-Events | 🚧 Host-Agent fertig |
| **Ingestion & Event Bus** | Normalisieren auf ein gemeinsames Schema | ✅ fertig |
| **SIEM / Storage** | Speichern & durchsuchen von Events | ✅ fertig |
| **Detection Engine** | Regel- (Sigma) + Signatur- + Anomalie-Erkennung | ✅ Keyword-Regeln + Z-Score |
| **Vulnerability Scanner** | Orchestriert nmap / nuclei / Trivy | 🔲 geplant |
| **IDS-Integration** | Netzwerk-Erkennung via Suricata / Zeek | 🔲 geplant |
| **Correlation & Alerting** | Events → Incidents, Deduplizierung, Severity | 🚧 erste Benachrichtigung fertig |
| **Adaptive Response (SOAR)** | Playbooks mit Safety-Gates & Rollback | 🔲 geplant |
| **Dashboard** | Web-UI für Status, Alerts, Incidents, Scans | 🚧 Live-Feed-MVP fertig |

## Dokumentation

- 📐 [Architektur](docs/architecture.md) — Komponenten, Datenfluss, Tech-Stack
- 🗺️ [Roadmap](docs/roadmap.md) — Phasenplan mit Meilensteinen
- 🛡️ [Sicherheit & Ethik](docs/architecture.md#sicherheit-recht--ethik)

## Grundprinzip

**Nur auf eigenen oder ausdrücklich autorisierten Systemen einsetzbar.**
Alle Gegenmaßnahmen sind defensiv (blockieren, isolieren, drosseln) — niemals
offensiv gegen Dritte. Details siehe Architektur-Dokument.

## Status

✅ **Phase 0 (Projekt-Grundgerüst) abgeschlossen.** Python-Setup (uv, ruff,
mypy), ECS-angelehntes Event-Schema, Postgres-Modelle + Alembic-Migration,
docker-compose (DB/Redis/App), GitHub-Actions-CI und das Scope-Konzept stehen.

✅ **Phase 1 (Monitoring-MVP) abgeschlossen.** Host-Agent (Log-Tailing +
Prozess-/Netzwerk-Snapshot), Event Bus über Redis Streams, Consumer-Worker
der Events nach Postgres schreibt, HTMX/Jinja-Dashboard mit Live-Feed +
Filter/Suche, sowie konfigurierbare E-Mail-/Webhook-Benachrichtigung ab
einstellbarem Severity-Schwellwert. Starten via aeris up, Dashboard unter
http://localhost:8000/.

✅ **Phase 2 (Detection Engine) abgeschlossen.** Brute-Force-Regel (Schwellwert +
Zeitfenster, IP-gruppiert, dedupliziert), kuratierte Keyword-Regeln (neues
Admin-/Sudo-Konto, Reverse-Shell-Muster in Prozess-Kommandozeilen), Z-Score-
Anomalie-Detektor auf der Prozess-Erstellungsrate pro Host, MITRE-ATT&CK-
Mapping je Alert sowie eine eigene Alert-Ansicht im Dashboard.

Nächster Schritt: Phase 3 (Vulnerability Scanning) — nmap/nuclei/Trivy-
Orchestrierung, Asset-Inventar, Finding-Verwaltung.
