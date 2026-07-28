# Aegis — Adaptive Defensive Security Platform

> Arbeitstitel „Aegis" (griech. Schutzschild). Der Name ist frei änderbar.

Eine modulare, **rein defensive** Security-Plattform, die Monitoring/SIEM,
Intrusion Detection, Schwachstellen-Scanning und ein zentrales Dashboard
vereint — mit einer **adaptiven Response-Engine**, die auf erkannte Angriffe
mit vordefinierten, abgesicherten Gegenmaßnahmen reagiert.

## Vision

Ein System, das die **eingehende Angriffsfläche eines echten Servers**
überwacht — Sicherheitsereignisse **sammelt**, **erkennt**, **korreliert**,
**visualisiert** und bei Bedarf **automatisch reagiert** — mit
Mensch-im-Kontrollkreis für kritische Aktionen.

**Reales Setup:** Entwicklung und erstes Schutzziel ist ein eigener
Kali-VPS (Doppelnutzung als Pentesting-Werkzeugkasten — Aegis überwacht
bewusst nur eingehenden Traffic, nicht die eigene Tool-Nutzung). Ein
zweiter, geschäftlich genutzter Server kommt erst später dazu, mit
konservativerem Automatisierungsgrad. Details siehe
[Architektur, Abschnitt 0](docs/architecture.md#0-reales-setup-ausgangslage).

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

## Zusammenarbeit

Ein Großteil des Codes wird von Claude geschrieben; Entscheidungen an
Weichenstellungen werden kurz erklärt und gemeinsam freigegeben. Das
Dashboard-Design wird **gemeinsam** gestaltet, sobald diese Phase in der
Roadmap ansteht.

## Status

🌱 **Planungsphase, gemeinsam abgestimmt.** Noch kein produktiver Code.
Nächster Schritt: Phase 0 (Projekt-Grundgerüst & Kali-Härtung).
