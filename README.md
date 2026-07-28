# Aegis — Adaptive Defensive Security Platform

Aegis ist eine modulare, rein defensive Security-Plattform für eigene oder
ausdrücklich autorisierte Systeme. Der aktuelle MVP sammelt Host-Ereignisse,
persistiert und bewertet sie, zeigt Events und Alerts im Web-Dashboard und
versendet konfigurierbare Benachrichtigungen.

> Repository und Kommandozeilenprogramm heißen `aeris`; Produkt und Datenbank
> heißen `Aegis` beziehungsweise `aegis`.

## Implementierter Stand

| Baustein | Heute implementiert |
|---|---|
| Host-Agent | Datei-Tailing sowie Prozess- und Socket-Snapshots des Linux-Hosts |
| Event Bus | Authentifizierte Redis Streams mit AOF-Persistenz, Pending-Recovery und Dead-Letter-Stream |
| Storage | PostgreSQL, Alembic-Migrationen und globale Event-Retention |
| Detection | Host-/IP-bezogene Brute-Force-Regel, deduplizierte Keyword-Regeln und Z-Score-Prozessanomalie |
| Alerting | Persistente Zustellwarteschlange mit Retry für Webhook und SMTP |
| Web | FastAPI, Jinja-Dashboard, REST-Endpunkte, HTTP-Basic-Authentifizierung und Browser-Polling |
| CLI | Global installierbarer `aeris`-Befehl für Dashboard, Compose-Betrieb, Diagnose und Wartung |

Das verbindliche visuelle und funktionale Zielbild der Oberfläche liegt in
[`dashboard/design/Aegis_Dashboard.html`](https://github.com/olesorgenfrey/Security-system/blob/main/dashboard/design/Aegis_Dashboard.html).
Das aktuelle Dashboard setzt davon den Event-/Alert-MVP um.

## Installation wie bei Codex CLI

Für die normale Installation werden hostseitig weder Python noch `uv`
benötigt. Voraussetzungen sind:

- macOS oder Linux
- Node.js 20 oder neuer einschließlich `npm`
- Docker Desktop beziehungsweise Docker Engine mit Docker Compose v2

Prüfen:

```bash
node --version
npm --version
docker compose version
```

Falls `npm` auf dem Mac fehlt, installiere zuerst eine aktuelle Node.js-
Version, beispielsweise mit dem offiziellen Installer oder Homebrew. Docker
Desktop muss vor dem ersten Start laufen.

Direkt aus einem lokalen Checkout ist die CLI schon jetzt global installierbar:

```bash
cd /absoluter/pfad/zum/Security-system
npm install --global .
aeris
```

Sobald die aktuellen Änderungen auf GitHub liegen, funktioniert derselbe Weg
ohne vorherigen Checkout. Dieser vorläufige Weg benötigt zusätzlich `git`:

```bash
npm install --global "git+https://github.com/olesorgenfrey/Security-system.git#main"
aeris
```

Damit ist `aeris` aus jedem Verzeichnis verfügbar. Sobald
`aeris-security-cli` erstmals in der npm-Registry veröffentlicht wurde,
verkürzt sich die Installation auf:

```bash
npm install --global aeris-security-cli
```

Die Registry-Veröffentlichung ist noch nicht erfolgt. Bis dahin sind der
lokale Checkout und nach dem Push der GitHub-Befehl die installierbaren Wege.

### Erster Start

`aeris` ohne Argumente legt beim ersten Aufruf automatisch eine private
Konfiguration an, erzeugt drei voneinander unabhängige Zufalls-Secrets, startet
die Docker-Compose-Dienste und öffnet das Dashboard im Standardbrowser:

```bash
aeris
aeris credentials
```

Die Browser-Zugangsdaten zeigt nur der ausdrücklich aufgerufene Befehl
`aeris credentials`. PostgreSQL- und Redis-Secrets werden nie ausgegeben.
Standardmäßig liegen die persistenten Dateien unter:

```text
~/.config/aeris/.env
~/.config/aeris/config/scope.yaml
```

Die `.env` wird unter macOS und Linux mit Modus `0600` angelegt. Ein anderer
Basisordner lässt sich mit `AERIS_HOME` setzen. npm-Updates überschreiben
diese Konfiguration nicht.

Unter macOS läuft der Dashboard-/Backend-Stack in Docker Desktop. Der
Linux-Host-Agent wird dort bewusst nicht gestartet, weil ein Linux-Container
den eigentlichen macOS-Host nicht verlässlich überwachen kann. Für reales
Host-Monitoring Aeris auf dem autorisierten Linux-Zielsystem betreiben.

### Aktualisieren und deinstallieren

GitHub-Installation aktualisieren:

```bash
npm install --global "git+https://github.com/olesorgenfrey/Security-system.git#main"
```

Nach einem npm-Registry-Release:

```bash
npm update --global aeris-security-cli
```

CLI entfernen:

```bash
npm uninstall --global aeris-security-cli
```

Die Betriebsdaten und Secrets unter `~/.config/aeris` bleiben dabei
absichtlich erhalten.

## Kommandozeile

```bash
aeris                              # Dienste starten und Dashboard öffnen
aeris dashboard                    # identisch zum Aufruf ohne Unterbefehl
aeris dashboard --no-start         # nur eine laufende Instanz prüfen/öffnen
aeris dashboard --no-browser       # starten, aber keinen Browser öffnen
aeris dashboard --wait-seconds 60
aeris init                         # sichere Konfiguration vorab anlegen
aeris credentials                  # Dashboard-Benutzername/-Passwort anzeigen
aeris up                           # Dienste bauen und starten
aeris up --no-build                # vorhandene Images starten
aeris down                         # Dienste stoppen; Volumes behalten
aeris status                       # Compose-Status anzeigen
aeris logs                         # alle Logs anzeigen
aeris logs app worker -f --tail 200
aeris doctor                       # Installation und Konfiguration prüfen
aeris maintenance
aeris maintenance --once
aeris --version
aeris --help
```

`aeris down` löscht keine Volumes. Die CLI bietet absichtlich keinen
`--volumes`-Schalter an, damit PostgreSQL- und Redis-Daten nicht versehentlich
entfernt werden.

Ein alternatives Paket oder eine eigene Env-Datei muss explizit angegeben
werden:

```bash
aeris status --project-dir /srv/aeris --env-file /srv/aeris/.env
```

`--project-dir` erlaubt das Bauen des dortigen Dockerfiles und darf deshalb
nur auf einen vertrauenswürdigen Checkout zeigen. Ein ähnlich aussehendes
Verzeichnis wird nie automatisch übernommen.

Mit `AERIS_DASHBOARD_URL` lässt sich die Standardadresse
`http://127.0.0.1:8000/` für Healthcheck und Browser überschreiben:

```bash
AERIS_DASHBOARD_URL=https://aegis.example.com aeris dashboard --no-start
```

## Sicherer Zugriff

Dashboard, PostgreSQL und Redis sind standardmäßig nur an Loopback gebunden.
Für einen einzelnen Administrator kann ein SSH-Tunnel verwendet werden:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Für dauerhaften Browserzugriff gehört ein Reverse Proxy mit gültigem
TLS-Zertifikat vor `127.0.0.1:8000`. HTTP Basic schützt Zugangsdaten nicht auf
einer unverschlüsselten Verbindung. PostgreSQL und Redis dürfen nicht ins
öffentliche Netz freigegeben werden. Details stehen in
[`docs/deployment.md`](https://github.com/olesorgenfrey/Security-system/blob/main/docs/deployment.md).

## Entwicklung aus dem Checkout

`uv` ist ausschließlich für Python-Entwicklung und die vollständigen
Projektprüfungen erforderlich, nicht für die globale npm-Installation:

```bash
uv sync --all-groups
uv run aeris test
```

Die Node-CLI lässt sich unabhängig davon prüfen:

```bash
npm run check
npm test
npm pack --dry-run
```

Die CI startet PostgreSQL und Redis, validiert Migrationen, Ruff, Formatierung,
striktes Mypy, Python- und JavaScript-Tests, die Compose-Konfiguration und den
Container-Build. Zusätzlich packt sie die npm-Distribution und installiert den
`aeris`-Befehl isoliert aus dem erzeugten Tarball.

## Dokumentation

- [Sicheres Deployment und Betrieb](https://github.com/olesorgenfrey/Security-system/blob/main/docs/deployment.md)
- [Architektur und Ist-/Ziel-Abgrenzung](https://github.com/olesorgenfrey/Security-system/blob/main/docs/architecture.md)
- [Roadmap](https://github.com/olesorgenfrey/Security-system/blob/main/docs/roadmap.md)

## Grundprinzip

Nur auf eigenen oder ausdrücklich autorisierten Systemen einsetzen. Alle
Gegenmaßnahmen bleiben defensiv; Hack-back gegen Dritte ist ausgeschlossen.
