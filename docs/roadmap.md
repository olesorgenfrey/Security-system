# Roadmap — Aegis

Inkrementeller Aufbau auf dem echten Kali-VPS. Jede Phase liefert etwas
**Lauffähiges & Nützliches** auf dem echten Server — kein rein theoretisches
Grundgerüst. Reihenfolge: **beobachten → erkennen → reagieren.** Die
riskante Automatik (Response) kommt bewusst zuletzt, und der zweite
(geschäftlich genutzte) Server wird erst angebunden, wenn Aegis sich auf
Kali bewährt hat.

Legende: 🔲 offen · 🚧 in Arbeit · ✅ fertig

---

## Phase 0 — Grundgerüst & Kali-Härtung  ✅
**Ziel:** Sauberer, reproduzierbarer Ausgangspunkt auf dem echten Server.

- [x] Projektstruktur & Python-Setup (uv, Linting/ruff, Typing/mypy)
- [x] Gemeinsames Event-Schema (ECS-angelehnt, inkl. `event.direction`)
- [x] PostgreSQL + Migrationen (SQLAlchemy/Alembic)
- [x] `docker-compose` für die Aegis-Komponenten (DB/Redis/App)
- [x] GitHub-Actions-CI: Lint, Tests
- [x] Konfigurations- & Scope-Konzept (`config/scope.yaml`, fail-closed
      außerhalb des erlaubten Bereichs)
- [x] Kali-VPS-Grundhärtung (root-Login/Passwort-Login waren bereits aus;
      Docker/UFW-Expositionslücke beim Solr-Testcontainer behoben, siehe
      unten)
- [ ] Eigener SSH-Key/eigene IP als **Allowlist-Eintrag** dokumentiert —
      Grundlage, die die Response-Engine (Phase 5) später nie automatisch
      blocken darf

**Ergebnis:** `docker compose up` startet das vollständige Aegis-Skelett auf
dem echten Server.

**Erledigte Baustelle (außerhalb des Phasenplans):** Bei der
Bestandsaufnahme des Servers wurde ein absichtlich verwundbarer
Solr-Testcontainer gefunden, der wegen eines Docker/UFW-Zusammenspiels
öffentlich statt nur lokal erreichbar war (Ports 5005/8983 auf `0.0.0.0`).
Fix angewendet: Ports in `docker-compose.yml` auf `127.0.0.1` gebunden,
Zugriff bei Bedarf per SSH-Tunnel. ✅ Vom Nutzer bestätigt ausgeführt
(technische Verifikation via `kali-server`-MCP-Verbindung steht noch aus,
da diese aktuell nicht erreichbar ist).

---

## Phase 1 — Monitoring-MVP: SSH & eingehende Verbindungen  ✅
**Ziel:** Echte Sichtbarkeit über das, was von außen auf den Server zukommt.

- [x] Host-Agent: Log-Tailing (Auth-Log) + Prozess-/Netzwerk-Snapshot
- [x] Event Bus (Redis Streams) + Normalizer
- [x] Events strukturiert in Postgres (Consumer-Worker)
- [x] **Dashboard-Design gemeinsam** — Referenz-Design steht
      ([`dashboard/design/Aegis_Dashboard.html`](../dashboard/design/Aegis_Dashboard.html),
      siehe `architecture.md` Abschnitt 3.7), vorgezogen vor den Rest von
      Phase 1
- [x] Minimal-Dashboard: HTMX/Jinja mit Live-Feed + Filter/Suche (eigene,
      schlanke Umsetzung — visuelle Angleichung ans Referenz-Design steht
      noch aus, siehe Phase 1 Folgearbeiten)
- [x] Erste E-Mail/Webhook-Benachrichtigung ab konfigurierbarem
      Severity-Schwellwert

**Ergebnis:** Live-Sicht auf eingehende Auth-/Verbindungsereignisse, Start
via `docker compose -f deploy/docker-compose.yml up`, Dashboard unter
http://localhost:8000/.

**Offene Folgearbeit:** Das laufende Minimal-Dashboard nutzt noch sein
eigenes, schlichtes HTMX/Jinja-Layout, nicht die Optik/Interaktionsmuster
des Referenz-Designs (Freigabe-Reibung nach Schweregrad, Kill-Chain-Stages,
Dark-Ops-Konsolen-Look etc.). Angleichung ist eine bewusste spätere
Entscheidung, kein Versehen.

---

## Phase 2 — Detection Engine  ✅
**Ziel:** Aus rohen Events werden aussagekräftige Alerts — dein
Brute-Force-Beispiel wird real erkannt.

- [x] Regel: Brute-Force-Erkennung (Schwellwert/Zeitfenster, IP-gruppiert,
      dedupliziert)
- [x] Kuratierte Keyword-Regeln (neues Admin-/Sudo-Konto, Reverse-Shell-Muster
      in Prozess-Kommandozeilen) — echtes Sigma (pySigma) als späterer Ausbau
- [x] Anomalie-Detektor: Z-Score auf Prozess-Erstellungsrate pro Host
- [x] Severity-Scoring + MITRE-ATT&CK-Mapping (erste Regel)
- [x] Alert-Ansicht im Dashboard
- [ ] Correlation-Engine: zusammenhängende Alerts → ein Incident mit
      Verdachtsspur (welcher Login → welcher Prozess → welche Aktion) —
      noch offen, aktuell einzelne Alerts ohne Incident-Zusammenfassung

**Ergebnis:** Das System meldet „hier ist ein Brute-Force-Angriff" bzw.
„hier deutet etwas auf einen erfolgreichen Einbruch hin" — mit Kontext.

---

## Phase 3 — Adaptive Response (zuerst nur Dry-Run)  🔲
**Ziel:** Dein Kern-Szenario — Angriff erkennen, automatisch reagieren,
kontrolliert.

- [ ] Playbook-Format (YAML) + Ausführungs-Engine
- [ ] **Allowlist-Layer zuerst umsetzen und testen** — eigener Key/eigene
      IP dürfen nachweislich nie geblockt werden (eigener Testfall!)
- [ ] Dry-Run-Default für jede neue Aktion
- [ ] Aktion 1: verdächtige IP nach Brute-Force temporär blocken (nftables),
      mit TTL/Rollback
- [ ] Aktion 2: bei Post-Compromise-Verdacht Session/Prozess beenden,
      Konto sperren
- [ ] Freigabe-Reibung nach Schweregrad gestaffelt (Halten-zum-Bestätigen
      bei kritisch, Doppelklick bei hoch) — UX bereits im Referenz-Design
      vorgezeichnet, siehe `architecture.md` Abschnitt 3.6
- [ ] Fail-Active/Fail-Closed-Einstufung je Playbook
- [ ] Globaler SCHARF/DRY-RUN-Schalter
- [ ] Vollständiges Audit-Log jeder ausgelösten Aktion
- [ ] Schrittweise Freigabe: Beobachten → mit Freigabe → (für den
      Brute-Force-Fall) vollautomatisch

**Ergebnis:** Das System wehrt Brute-Force-Angriffe selbst ab und reagiert
auf Anzeichen eines erfolgreichen Einbruchs — mit Sicherheitsnetz.

---

## Phase 4 — Vulnerability Scanning  🔲
**Ziel:** Proaktiv Schwachstellen auf dem eigenen Server finden.

- [ ] nmap-Orchestrierung (Asset-/Port-Discovery des eigenen Servers)
- [ ] nuclei für bekannte CVEs auf exponierten Diensten
- [ ] Findings im Dashboard, priorisiert nach CVSS + Erreichbarkeit
- [ ] Geplante & Ad-hoc-Scans

**Ergebnis:** Regelmäßige Zustandsprüfung — Lücken werden gefunden, bevor
sie ausgenutzt werden. (Hätte den Solr-Expositionsfund aus Phase 0 früh
automatisch aufgedeckt.)

---

## Phase 5 — Netzwerk-IDS (Suricata)  🔲
**Ziel:** Tiefere Netzwerksicht zusätzlich zu Host-Events.

- [ ] Suricata als Sensor einbinden (EVE-JSON → Bus)
- [ ] Netzwerk-Alerts in Correlation-Engine integrieren
- [ ] Angriffsketten über Host- + Netz-Events korrelieren

**Ergebnis:** Kombinierte Host- und Netzwerksicht in einem Incident-Bild.

---

## Phase 6 — Rollout auf den zweiten (wichtigen) Server  🔲
**Ziel:** Aegis auf den geschäftlich genutzten Server bringen — vorsichtig.

- [ ] Konservativerer Response-Modus als Standard (mehr Freigaben, weniger
      Automatik, bis Vertrauen besteht)
- [ ] Anpassung an dortige Dienste (Web-Apps statt Pentesting-Tools)
- [ ] Schrittweise Angleichung an das Automatisierungsniveau von Kali,
      nur nach expliziter Freigabe

---

## Stretch-Goal (nach Phase 6, offen) — „Zero-Day-Selbstheilung"  🔲

Nur falls der gesamte Kern zuverlässig läuft: vorsichtige Experimente
Richtung automatisierter Ursachenforschung und Fix-Vorschlägen für
unbekannte Lücken (Mensch bestätigt weiterhin jeden Fix). Kein
MVP-Bestandteil, siehe `architecture.md` Abschnitt 8.

---

## Priorisierungs-Logik

1. **Sichtbarkeit zuerst** (Phasen 0–2) — ohne verlässliche Daten zum
   eingehenden Traffic ist alles andere wertlos. ✅ erledigt.
2. **Automatik erst wenn Erkennung sitzt** (Phase 3) — mit hartem
   Allowlist-Schutz von Anfang an. ← aktueller Stand.
3. **Breiter werden** (Phasen 4–5) — Scanning und Netzwerksicht ergänzen
   den bewährten Kern.
4. **Zweiter Server erst zum Schluss** (Phase 6) — höhere Vorsicht, weniger
   Automatik, bis Vertrauen besteht.
