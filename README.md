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
| **Collectors / Agents** | Sammeln Logs, Prozess-, Netzwerk- und Cloud-Events | 🔲 geplant |
| **Ingestion & Event Bus** | Normalisieren auf ein gemeinsames Schema | 🔲 geplant |
| **SIEM / Storage** | Speichern & durchsuchen von Events | 🔲 geplant |
| **Detection Engine** | Regel- (Sigma) + Signatur- + Anomalie-Erkennung | 🔲 geplant |
| **Vulnerability Scanner** | Orchestriert nmap / nuclei / Trivy | 🔲 geplant |
| **IDS-Integration** | Netzwerk-Erkennung via Suricata / Zeek | 🔲 geplant |
| **Correlation & Alerting** | Events → Incidents, Deduplizierung, Severity | 🔲 geplant |
| **Adaptive Response (SOAR)** | Playbooks mit Safety-Gates & Rollback | 🔲 geplant |
| **Dashboard** | Web-UI für Status, Alerts, Incidents, Scans | 🔲 geplant |

## Dokumentation

- 📐 [Architektur](docs/architecture.md) — Komponenten, Datenfluss, Tech-Stack
- 🗺️ [Roadmap](docs/roadmap.md) — Phasenplan mit Meilensteinen
- 🛡️ [Sicherheit & Ethik](docs/architecture.md#sicherheit-recht--ethik)

## Grundprinzip

**Nur auf eigenen oder ausdrücklich autorisierten Systemen einsetzbar.**
Alle Gegenmaßnahmen sind defensiv (blockieren, isolieren, drosseln) — niemals
offensiv gegen Dritte. Details siehe Architektur-Dokument.

## Status

🌱 **Planungsphase.** Noch kein produktiver Code. Nächster Schritt: Freigabe
der Architektur, dann Phase 0 (Projekt-Grundgerüst).
