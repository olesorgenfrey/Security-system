# Roadmap — Aegis

Inkrementeller Aufbau auf dem echten Kali-VPS. Jede Phase liefert etwas
**Lauffähiges & Nützliches** auf dem echten Server — kein rein theoretisches
Grundgerüst. Reihenfolge: **beobachten → erkennen → reagieren.** Die
riskante Automatik (Response) kommt bewusst zuletzt, und der zweite
(geschäftlich genutzte) Server wird erst angebunden, wenn Aegis sich auf
Kali bewährt hat.

Legende: 🔲 offen · 🚧 in Arbeit · ✅ fertig

---

## Phase 0 — Grundgerüst & Kali-Härtung  🔲
**Ziel:** Sauberer, reproduzierbarer Ausgangspunkt auf dem echten Server.

- [ ] Kali-VPS-Grundhärtung: root-Login aus, Passwort-Login aus (nur Key),
      unnötige Dienste identifizieren
- [ ] Eigener SSH-Key/eigene IP als **Allowlist-Eintrag** dokumentieren —
      Grundlage, die später nie automatisch geblockt werden darf
- [ ] Projektstruktur & Python-Setup (Dependency-Management, Linting)
- [ ] Gemeinsames Event-Schema (ECS-angelehnt, inkl. `event.direction`)
- [ ] PostgreSQL + Migrationen
- [ ] `docker-compose` für die Aegis-Komponenten auf dem Kali-Server
- [ ] GitHub-Actions-CI: Lint, Tests

**Ergebnis:** Der Kali-Server ist etwas gehärtet, `docker compose up` startet
ein leeres, aber vollständiges Aegis-Skelett darauf.

---

## Phase 1 — Monitoring-MVP: SSH & eingehende Verbindungen  🔲
**Ziel:** Echte Sichtbarkeit über das, was von außen auf den Server zukommt.

- [ ] Host-Agent: `auth.log`/journald-Tailing (SSH-Logins, `sudo`-Nutzung)
- [ ] Eingehende Netzwerkverbindungen erfassen (ausgehende/lokale explizit
      ignorieren, um Pentesting-Nutzung nicht als Bedrohung zu werten)
- [ ] Event Bus (Redis Streams) + Normalizer
- [ ] Events strukturiert in Postgres
- [x] **Dashboard-Design gemeinsam** — Referenz-Design steht bereits
      ([`dashboard/design/Aegis_Dashboard.html`](../dashboard/design/Aegis_Dashboard.html),
      siehe `architecture.md` Abschnitt 3.7), vorgezogen vor den Rest von
      Phase 1
- [ ] Minimal-Dashboard: Live-Feed eingehender Auth-/Verbindungsereignisse
      an das bestehende Design anbinden (echte Daten statt Mock-Daten)
- [ ] Erste E-Mail/Webhook-Benachrichtigung bei auffälligen Login-Versuchen

**Ergebnis:** Du siehst live, wer/was versucht, auf deinen Kali-Server
zuzugreifen.

---

## Phase 2 — Detection Engine  🔲
**Ziel:** Aus rohen Events werden aussagekräftige Alerts — dein
Brute-Force-Beispiel wird real erkannt.

- [ ] Regel: „N fehlgeschlagene SSH-Logins von IP X in Zeitfenster Y" →
      Alert
- [ ] Verhaltensregeln für Post-Compromise-Verdacht: neuer Prozess mit
      ungewöhnlichem Elternprozess nach fremdem Login, neue Nutzerkonten,
      Rechte-Eskalation
- [ ] Correlation-Engine: zusammenhängende Alerts → ein Incident mit
      Verdachtsspur (welcher Login → welcher Prozess → welche Aktion)
- [ ] Severity-Scoring
- [ ] Alert-/Incident-Ansicht im Dashboard
- [ ] Erweiterung auf **Sigma-Regeln** für mehr Deckungsbreite (optional,
      nach den eigenen Kernregeln)

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
- [ ] Approval-Queue im Dashboard für alles außer „IP temporär blocken"
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
sie ausgenutzt werden.

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
   eingehenden Traffic ist alles andere wertlos.
2. **Automatik erst wenn Erkennung sitzt** (Phase 3) — mit hartem
   Allowlist-Schutz von Anfang an.
3. **Breiter werden** (Phasen 4–5) — Scanning und Netzwerksicht ergänzen
   den bewährten Kern.
4. **Zweiter Server erst zum Schluss** (Phase 6) — höhere Vorsicht, weniger
   Automatik, bis Vertrauen besteht.
