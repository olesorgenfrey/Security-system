# Sicheres Deployment

Diese Anleitung beschreibt den aktuellen Ein-Host-Betrieb mit Docker Compose.
Sie ersetzt nicht die Härtung des Betriebssystems, Firewall-Regeln,
regelmäßige Updates und getestete Backups.

## 1. Voraussetzungen

- Node.js 20 oder neuer mit `npm`
- Docker Engine und Docker Compose v2; auf macOS Docker Desktop
- für vollständiges Host-Monitoring ein eigener oder ausdrücklich
  autorisierter Linux-Host
- ein dateibasiertes Authentifizierungslog (`auth.log` oder `secure`)
- SSH-Key-Zugang und ein TLS-Reverse-Proxy, falls das Dashboard nicht
  ausschließlich lokal oder über einen SSH-Tunnel genutzt wird

Der Host-Agent kann Dateien tailen, aber noch nicht direkt aus journald lesen.
Auf Linux-Systemen ohne persistente Auth-Datei muss zuerst eine passende
rsyslog-/journald-Weiterleitung eingerichtet werden.

Unter macOS funktioniert der Dashboard-/Backend-Stack über Docker Desktop.
Der Linux-Host-Agent wird dort bewusst ausgelassen, weil er den eigentlichen
macOS-Host aus einer Linux-VM nicht verlässlich beobachten kann.

## 2. Installation und Konfiguration

Die globale Installation benötigt hostseitig weder Python noch `uv`. Aus einem
lokalen Checkout funktioniert sie sofort:

```bash
cd /absoluter/pfad/zum/Security-system
npm install --global .
aeris init
```

Nach dem Push kann npm die Quellen auch direkt per Git beziehen; dafür muss
zusätzlich `git` installiert sein:

```bash
npm install --global "git+https://github.com/olesorgenfrey/Security-system.git#main"
aeris init
```

Nach der ersten Veröffentlichung in der npm-Registry lautet der
Installationsbefehl `npm install --global aeris-security-cli`.

`aeris init` erzeugt drei unabhängige Zufalls-Secrets und schreibt die
Konfiguration standardmäßig nach `~/.config/aeris/.env`. Die Datei besitzt
unter macOS und Linux Modus `0600`. Ihr Pfad lässt sich mit `AERIS_HOME`
oder `--env-file` ändern. Bereits vorhandene Env-Dateien werden nicht
überschrieben; Symlinks werden abgelehnt.

Dashboard-Zugang anzeigen:

```bash
aeris credentials
```

Der Befehl zeigt ausschließlich `AEGIS_API_USERNAME` und
`AEGIS_API_PASSWORD`. PostgreSQL- und Redis-Secrets bleiben verborgen.
`.env` darf weder committet noch in Tickets oder Logs kopiert werden.

`AEGIS_BIND_ADDRESS=127.0.0.1` nicht ändern, solange keine bewusst geplante
Netzwerksegmentierung davorsteht. Insbesondere die Ports 5432 und 6379 gehören
nie ins öffentliche Internet.

### Manuelle Checkout-Konfiguration

Wer statt des verwalteten npm-Pakets bewusst mit einem Checkout arbeitet, kann
ihn explizit über `--project-dir` verwenden. Nur vertrauenswürdige Pfade
angeben, weil Aeris dort den Dockerfile baut:

```bash
cp .env.example .env
chmod 600 .env
openssl rand -hex 32
aeris --project-dir /srv/aeris --env-file /srv/aeris/.env doctor
```

Den letzten Befehl dreimal ausführen und unterschiedliche, URL-sichere Werte
als `POSTGRES_PASSWORD`, `REDIS_PASSWORD` und `AEGIS_API_PASSWORD`
eintragen.

## 3. Reales Linux-Host-Log anbinden

Compose mountet das Verzeichnis aus `HOST_LOG_DIR` read-only nach
`/host/var/log`. Ein Verzeichnis-Mount stellt sicher, dass der Agent nach
einer Logrotation die neue Datei sieht.

Typische Werte in `~/.config/aeris/.env`:

```dotenv
# Debian / Ubuntu
HOST_LOG_DIR=/var/log
HOST_AGENT_LOG_PATHS=/host/var/log/auth.log

# RHEL / Fedora
# HOST_LOG_DIR=/var/log
# HOST_AGENT_LOG_PATHS=/host/var/log/secure
```

Mehrere Dateien können kommasepariert angegeben werden, sofern sie innerhalb
des gemounteten Verzeichnisses liegen. Der Agent beginnt am Dateiende und
importiert bewusst nicht die komplette Historie.

Für Prozess- und Socket-Sicht teilt der Agent Host-PID- und
Host-Netzwerk-Namespace. Er läuft nicht `privileged`, besitzt keine
Schreib-/Netzwerk-Admin-Capability und bekommt nur `DAC_READ_SEARCH` und
`SYS_PTRACE`. LSM-, `hidepid`- oder Rootless-Docker-Einstellungen können
Snapshots einschränken. In diesem Fall die Agent-Logs prüfen und keine
pauschale `privileged`-Freigabe hinzufügen.

## 4. Start und Kontrolle

```bash
aeris doctor
aeris                         # startet und öffnet das Dashboard
aeris status
```

Auf einem Server ohne grafische Oberfläche:

```bash
aeris dashboard --no-browser
```

`aeris` prüft einen dienstspezifischen `/health`-Endpunkt. Ist der Stack
noch nicht gesund, startet die CLI die Dienste, wartet auf Bereitschaft und
öffnet anschließend den Standardbrowser. Die maximale Wartezeit ist mit
`--wait-seconds` einstellbar.

Der Compose-Ablauf ist geordnet:

1. PostgreSQL und Redis werden gesund.
2. `migrate` bringt das Schema auf den aktuellen Alembic-Stand.
3. Danach starten API, Ingestion-, Notification- und Retention-Worker.

Relevante Befehle:

```bash
aeris dashboard --no-start
aeris dashboard --no-browser
aeris dashboard --no-auth          # nur für einen lokalen Kurztest
aeris up
aeris up --no-build
aeris down
aeris status
aeris logs migrate app worker notification_worker maintenance host_agent --tail 200
aeris logs app worker -f --tail 200
aeris maintenance --once
```

`aeris dashboard --no-auth` deaktiviert die HTTP-Basic-Anmeldung nur transient
und nur, wenn Bind-Adresse und Dashboard-URL wörtliche Loopback-Adressen sind.
Die `.env` bleibt unverändert. Ein normaler Aufruf von `aeris` oder `aeris up`
setzt den App-Container anschließend wieder mit aktivierter Anmeldung auf.

`aeris down` behält PostgreSQL- und Redis-Volumes. Die CLI bietet
absichtlich keinen Schalter zum Löschen der Volumes.

Redis verwendet AOF mit `appendfsync everysec`; PostgreSQL und Redis besitzen
benannte Volumes. Das verbessert Neustartfestigkeit, ersetzt aber kein Backup.

## 5. Remote-Zugriff und TLS

Für Einzelzugriff einen SSH-Tunnel verwenden:

```bash
ssh -L 8000:127.0.0.1:8000 user@server
```

Für einen dauerhaften Endpunkt kann Nginx auf dem Host TLS terminieren. Das
Backend bleibt an Loopback gebunden:

```nginx
server {
    listen 443 ssl;
    listen [::]:443 ssl;
    server_name aegis.example.com;

    ssl_certificate /etc/letsencrypt/live/aegis.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/aegis.example.com/privkey.pem;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto https;
    }
}
```

Nur Port 443 für die erforderlichen Quellnetze freigeben. HTTP Basic ist erst
zusammen mit TLS ein angemessener Transportschutz.

Bei einer abweichenden öffentlichen Adresse:

```bash
AERIS_DASHBOARD_URL=https://aegis.example.com aeris dashboard --no-start
```

## 6. Updates, Retention und Benachrichtigungen

Vor einem Update PostgreSQL und die Env-Datei sichern. GitHub-Installation
aktualisieren und den Stack neu bauen:

```bash
npm install --global "git+https://github.com/olesorgenfrey/Security-system.git#main"
aeris up
aeris status
```

Nach einem Registry-Release kann stattdessen
`npm update --global aeris-security-cli` verwendet werden. Die persistente
Konfiguration unter `~/.config/aeris` wird bei npm-Updates nicht ersetzt.

Der `migrate`-Service führt neue Migrationen vor dem Anwendungsstart aus.
`EVENT_RETENTION_DAYS` steuert die globale Event-Aufbewahrung; der
Maintenance-Worker löscht ältere Events im konfigurierten Intervall.

Benachrichtigungen werden persistent vorgemerkt und vom
`notification_worker` mit begrenztem exponentiellem Retry zugestellt. Leere
Webhook-/SMTP-Ziele deaktivieren den jeweiligen Kanal.

## 7. Backup und Wiederherstellung

PostgreSQL regelmäßig mit `pg_dump` sichern und Restore-Proben auf einem
separaten System durchführen. Redis enthält den Event-Transport und ist dank
AOF neustartfest; für die fachlich dauerhaften Daten bleibt PostgreSQL die
maßgebliche Sicherungsquelle.

`aeris down` behält Volumes. Ein manuelles
`docker compose down --volumes` löscht sie dauerhaft und darf nur nach
bestätigtem Backup eingesetzt werden.
