#!/usr/bin/env node

import { spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import {
  chmodSync,
  closeSync,
  existsSync,
  fsyncSync,
  linkSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { homedir, hostname } from "node:os";
import path from "node:path";
import { setTimeout as sleepTimer } from "node:timers/promises";
import { fileURLToPath, pathToFileURL } from "node:url";

const MODULE_DIR = path.dirname(fileURLToPath(import.meta.url));
export const PACKAGE_ROOT = path.resolve(MODULE_DIR, "..");
export const REQUIRED_SECRETS = [
  "POSTGRES_PASSWORD",
  "REDIS_PASSWORD",
  "AEGIS_API_PASSWORD",
];
const SERVICE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9_.-]*$/;
const PROJECT_NAME_PATTERN = /^name\s*=\s*["']aegis["']\s*$/m;
const MAC_CORE_SERVICES = ["app", "worker", "notification_worker", "maintenance"];
const DEFAULT_WAIT_SECONDS = 120;

export class CliError extends Error {}

function packageVersion(packageRoot = PACKAGE_ROOT) {
  try {
    return JSON.parse(readFileSync(path.join(packageRoot, "package.json"), "utf8")).version;
  } catch {
    return "0.1.0";
  }
}

function defaultRunProcess(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env,
    shell: false,
    stdio: options.quiet ? "ignore" : "inherit",
  });
  if (result.error) {
    if (result.error.code === "ENOENT") return 127;
    throw new CliError(`Befehl ${JSON.stringify(command)} konnte nicht gestartet werden.`);
  }
  if (typeof result.status === "number") return result.status;
  return 1;
}

export function isAegisHealthPayload(payload) {
  return payload?.status === "ok" && payload?.service === "aegis";
}

async function defaultHealthCheck(url, timeoutMs) {
  const parsed = new URL(url);
  parsed.pathname = "/health";
  parsed.search = "";
  parsed.hash = "";
  try {
    const response = await fetch(parsed, {
      headers: { Accept: "application/json" },
      signal: AbortSignal.timeout(timeoutMs),
    });
    if (response.status !== 200) return false;
    const body = await response.text();
    if (body.length > 4096) return false;
    return isAegisHealthPayload(JSON.parse(body));
  } catch {
    return false;
  }
}

export function browserInvocation(url, platform) {
  if (platform === "darwin") return ["open", [url]];
  if (platform === "win32") return ["explorer.exe", [url]];
  return ["xdg-open", [url]];
}

function defaultOpenBrowser(url, context) {
  const [command, args] = browserInvocation(url, context.platform);
  return context.runProcess(command, args, {
    cwd: context.cwd,
    env: context.env,
    quiet: true,
  }) === 0;
}

export function createContext(overrides = {}) {
  const context = {
    cwd: overrides.cwd ?? process.cwd(),
    env: overrides.env ?? process.env,
    homeDir: overrides.homeDir ?? homedir(),
    packageRoot: overrides.packageRoot ?? PACKAGE_ROOT,
    platform: overrides.platform ?? process.platform,
    hostName: overrides.hostName ?? hostname(),
    runProcess: overrides.runProcess ?? defaultRunProcess,
    checkHealth: overrides.checkHealth ?? defaultHealthCheck,
    sleep: overrides.sleep ?? ((milliseconds) => sleepTimer(milliseconds)),
    stdout: overrides.stdout ?? ((message) => console.log(message)),
    stderr: overrides.stderr ?? ((message) => console.error(message)),
  };
  context.openBrowser = overrides.openBrowser ?? ((url) => defaultOpenBrowser(url, context));
  return context;
}

function isAerisProject(candidate) {
  const composeFile = path.join(candidate, "deploy", "docker-compose.yml");
  const pyproject = path.join(candidate, "pyproject.toml");
  const dockerfile = path.join(candidate, "Dockerfile");
  if (!existsSync(composeFile) || !existsSync(pyproject) || !existsSync(dockerfile)) return false;
  try {
    return PROJECT_NAME_PATTERN.test(readFileSync(pyproject, "utf8"));
  } catch {
    return false;
  }
}

function resolvePath(value, base, homeDir) {
  return path.resolve(base, value.replace(/^~(?=$|[/\\])/, homeDir));
}

export function resolveProject(options, context) {
  const explicit = options.projectDir ?? context.env.AERIS_PROJECT_DIR;
  if (explicit) {
    const projectRoot = resolvePath(explicit, context.cwd, context.homeDir);
    if (!isAerisProject(projectRoot)) {
      throw new CliError("Der angegebene Projektpfad ist kein Aeris-Paket.");
    }
    return { root: projectRoot, external: true };
  }
  const packageRoot = path.resolve(context.packageRoot);
  if (!isAerisProject(packageRoot)) {
    throw new CliError("Das installierte Aeris-Paket ist unvollständig; bitte neu installieren.");
  }
  return { root: packageRoot, external: false };
}

export function aerisHome(context) {
  const configured = context.env.AERIS_HOME;
  if (configured) return resolvePath(configured, context.cwd, context.homeDir);
  const configBase = context.env.XDG_CONFIG_HOME
    ? resolvePath(context.env.XDG_CONFIG_HOME, context.cwd, context.homeDir)
    : path.join(context.homeDir, ".config");
  return path.join(configBase, "aeris");
}

function resolveEnvFile(options, context, project) {
  const explicit = options.envFile ?? context.env.AERIS_ENV_FILE;
  if (explicit) return resolvePath(explicit, project.root, context.homeDir);
  if (project.external) return path.join(project.root, ".env");
  return path.join(aerisHome(context), ".env");
}

function replaceExactlyOnce(contents, key, value) {
  const expression = new RegExp(`^${key}=.*$`, "gm");
  const matches = contents.match(expression) ?? [];
  if (matches.length !== 1) {
    throw new CliError(`Vorlage enthält ${key} nicht genau einmal.`);
  }
  return contents.replace(expression, `${key}=${value}`);
}

function quoteEnvValue(value) {
  if (/^[A-Za-z0-9_./:~-]+$/.test(value)) return value;
  return JSON.stringify(value);
}

function writeExclusiveAtomic(destination, contents, mode) {
  const parent = path.dirname(destination);
  mkdirSync(parent, { recursive: true, mode: 0o700 });
  const temporary = path.join(
    parent,
    `.${path.basename(destination)}.${process.pid}.${randomBytes(8).toString("hex")}.tmp`,
  );
  let descriptor;
  try {
    descriptor = openSync(temporary, "wx", mode);
    writeFileSync(descriptor, contents, "utf8");
    fsyncSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    try {
      linkSync(temporary, destination);
    } catch (error) {
      if (error.code !== "EEXIST") throw error;
    }
  } finally {
    if (descriptor !== undefined) closeSync(descriptor);
    try {
      unlinkSync(temporary);
    } catch (error) {
      if (error.code !== "ENOENT") throw error;
    }
  }
}

function copyIfMissing(source, destination, mode) {
  if (existsSync(destination)) return;
  writeExclusiveAtomic(destination, readFileSync(source, "utf8"), mode);
}

export function ensureRuntimeFiles(runtime, context) {
  const home = path.dirname(runtime.envFile);
  const defaultConfigDirectory = path.join(home, "config");
  const hostLogs = path.join(home, "host-logs");
  mkdirSync(home, { recursive: true, mode: 0o700 });
  if (path.resolve(home) === path.resolve(aerisHome(context)) && context.platform !== "win32") {
    chmodSync(home, 0o700);
  }

  const existingStats = lstatSync(runtime.envFile, { throwIfNoEntry: false });
  if (existingStats) {
    const stats = existingStats;
    if (stats.isSymbolicLink() || !stats.isFile()) {
      throw new CliError("Die Aeris-Konfiguration muss eine reguläre Datei sein.");
    }
    if (context.platform !== "win32") chmodSync(runtime.envFile, 0o600);
    const existingValues = parseEnvFile(runtime.envFile);
    const configuredDirectory =
      context.env.AERIS_CONFIG_DIR ?? existingValues.AERIS_CONFIG_DIR;
    const configDirectory = configuredDirectory
      ? resolvePath(configuredDirectory, path.dirname(runtime.composeFile), context.homeDir)
      : defaultConfigDirectory;
    mkdirSync(configDirectory, { recursive: true, mode: 0o700 });
    copyIfMissing(
      path.join(runtime.projectRoot, "config", "scope.yaml"),
      path.join(configDirectory, "scope.yaml"),
      0o600,
    );
    if (context.platform === "darwin") {
      const configuredHostLogs = context.env.HOST_LOG_DIR ?? existingValues.HOST_LOG_DIR;
      const resolvedHostLogs = configuredHostLogs
        ? resolvePath(configuredHostLogs, path.dirname(runtime.composeFile), context.homeDir)
        : hostLogs;
      if (path.resolve(resolvedHostLogs) === path.resolve(hostLogs)) {
        mkdirSync(hostLogs, { recursive: true, mode: 0o700 });
        const authLog = path.join(hostLogs, "auth.log");
        if (!existsSync(authLog)) writeExclusiveAtomic(authLog, "", 0o600);
      }
    }
    return false;
  }

  const configDirectory = defaultConfigDirectory;
  mkdirSync(configDirectory, { recursive: true, mode: 0o700 });
  copyIfMissing(
    path.join(runtime.projectRoot, "config", "scope.yaml"),
    path.join(configDirectory, "scope.yaml"),
    0o600,
  );

  let template = readFileSync(path.join(runtime.projectRoot, ".env.example"), "utf8");
  const generated = Object.fromEntries(
    REQUIRED_SECRETS.map((name) => [name, randomBytes(32).toString("hex")]),
  );
  for (const name of REQUIRED_SECRETS) {
    template = replaceExactlyOnce(template, name, generated[name]);
  }
  template = replaceExactlyOnce(
    template,
    "HOST_AGENT_HOSTNAME",
    quoteEnvValue(context.hostName.replace(/[\r\n]/g, "-")),
  );
  if (/^AERIS_CONFIG_DIR=/m.test(template)) {
    template = replaceExactlyOnce(
      template,
      "AERIS_CONFIG_DIR",
      quoteEnvValue(configDirectory),
    );
  } else {
    template += `\nAERIS_CONFIG_DIR=${quoteEnvValue(configDirectory)}\n`;
  }
  if (context.platform === "darwin") {
    mkdirSync(hostLogs, { recursive: true, mode: 0o700 });
    const authLog = path.join(hostLogs, "auth.log");
    if (!existsSync(authLog)) writeExclusiveAtomic(authLog, "", 0o600);
    template = replaceExactlyOnce(template, "HOST_LOG_DIR", quoteEnvValue(hostLogs));
  }
  writeExclusiveAtomic(runtime.envFile, template, 0o600);
  chmodSync(runtime.envFile, 0o600);
  return true;
}

function stripInlineComment(value) {
  const match = value.match(/\s+#/);
  return (match ? value.slice(0, match.index) : value).trimEnd();
}

export function parseEnvFile(envFile) {
  const stats = lstatSync(envFile, { throwIfNoEntry: false });
  if (!stats) return {};
  if (stats.isSymbolicLink() || !stats.isFile()) {
    throw new CliError("Die Aeris-Konfiguration muss eine reguläre Datei sein.");
  }
  let contents;
  try {
    contents = readFileSync(envFile, "utf8");
  } catch {
    throw new CliError("Die Aeris-Konfiguration kann nicht gelesen werden.");
  }
  const values = {};
  for (const rawLine of contents.split(/\r?\n/)) {
    let line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    if (line.startsWith("export ")) line = line.slice(7).trimStart();
    const separator = line.indexOf("=");
    if (separator < 1) continue;
    const key = line.slice(0, separator).trim();
    let value = line.slice(separator + 1).trim();
    if (!/^[A-Za-z_][A-Za-z0-9_]*$/.test(key)) continue;
    if (value.startsWith("'") && value.endsWith("'")) {
      value = value.slice(1, -1).replaceAll("\\'", "'");
    } else if (value.startsWith('"')) {
      const closing = value.lastIndexOf('"');
      if (closing > 0 && !value.slice(closing + 1).trim().replace(/^#.*$/, "")) {
        try {
          value = JSON.parse(value.slice(0, closing + 1));
        } catch {
          value = value.slice(1, closing);
        }
      }
    } else {
      value = stripInlineComment(value);
    }
    values[key] = value;
  }
  return values;
}

function setting(runtime, context, name, fallback = undefined) {
  return context.env[name] ?? runtime.envValues[name] ?? fallback;
}

function validateSecrets(runtime, context) {
  const values = REQUIRED_SECRETS.map((name) => setting(runtime, context, name, ""));
  const errors = [];
  for (let index = 0; index < REQUIRED_SECRETS.length; index += 1) {
    if (!values[index]) errors.push(`${REQUIRED_SECRETS[index]} fehlt oder ist leer`);
  }
  if (values[2] && values[2].length < 16) {
    errors.push("AEGIS_API_PASSWORD muss mindestens 16 Zeichen lang sein");
  }
  for (let index = 0; index < 2; index += 1) {
    if (values[index] && !/^[A-Za-z0-9._~-]+$/.test(values[index])) {
      errors.push(`${REQUIRED_SECRETS[index]} muss URL-sicher sein`);
    }
  }
  const nonempty = values.filter(Boolean);
  if (new Set(nonempty).size !== nonempty.length) {
    errors.push("POSTGRES-, REDIS- und API-Passwort müssen unterschiedlich sein");
  }
  return errors;
}

export function createRuntime(options, context, initialize = false) {
  const project = resolveProject(options, context);
  const envFile = resolveEnvFile(options, context, project);
  const runtime = {
    projectRoot: project.root,
    composeFile: path.join(project.root, "deploy", "docker-compose.yml"),
    envFile,
    envValues: {},
  };
  const created = initialize ? ensureRuntimeFiles(runtime, context) : false;
  runtime.envValues = parseEnvFile(envFile);
  return { runtime, created };
}

export function dashboardUrl(runtime, context) {
  const configured = setting(runtime, context, "AERIS_DASHBOARD_URL");
  let candidate;
  if (configured) {
    candidate = configured.trim();
  } else {
    const rawPort = setting(runtime, context, "AEGIS_HTTP_PORT", "8000");
    const port = Number(rawPort);
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
      throw new CliError("AEGIS_HTTP_PORT muss zwischen 1 und 65535 liegen.");
    }
    let host = setting(runtime, context, "AEGIS_BIND_ADDRESS", "127.0.0.1").trim();
    if (["0.0.0.0", "::", "[::]"].includes(host)) host = "127.0.0.1";
    if (/\s|[/@?#]/.test(host)) throw new CliError("AEGIS_BIND_ADDRESS ist ungültig.");
    if (host.includes(":") && !host.startsWith("[")) host = `[${host}]`;
    candidate = `http://${host}:${port}/`;
  }
  let parsed;
  try {
    parsed = new URL(candidate);
  } catch {
    throw new CliError("AERIS_DASHBOARD_URL ist keine gültige HTTP(S)-Adresse.");
  }
  if (!["http:", "https:"].includes(parsed.protocol) || !parsed.hostname) {
    throw new CliError("AERIS_DASHBOARD_URL muss eine vollständige HTTP(S)-Adresse sein.");
  }
  if (parsed.username || parsed.password) {
    throw new CliError("Zugangsdaten gehören nicht in AERIS_DASHBOARD_URL.");
  }
  if (parsed.search || parsed.hash) {
    throw new CliError("AERIS_DASHBOARD_URL darf weder Query noch Fragment enthalten.");
  }
  parsed.pathname = `${parsed.pathname.replace(/\/+$/, "")}/`;
  return parsed.toString();
}

function composeExecutable(context, runtime) {
  if (
    context.runProcess("docker", ["compose", "version"], {
      cwd: runtime.projectRoot,
      env: context.env,
      quiet: true,
    }) === 0
  ) {
    return ["docker", "compose"];
  }
  if (
    context.runProcess("docker-compose", ["version"], {
      cwd: runtime.projectRoot,
      env: context.env,
      quiet: true,
    }) === 0
  ) {
    return ["docker-compose"];
  }
  throw new CliError("Docker Compose wurde nicht gefunden. Installiere Docker Desktop.");
}

function composePrefix(runtime, context, validate = true) {
  if (!existsSync(runtime.envFile)) {
    throw new CliError("Aeris ist noch nicht eingerichtet. Führe `aeris init` aus.");
  }
  if (validate) {
    const errors = validateSecrets(runtime, context);
    if (errors.length) throw new CliError(`Ungültige Konfiguration: ${errors.join("; ")}`);
  }
  const executable = composeExecutable(context, runtime);
  return [
    executable[0],
    [
      ...executable.slice(1),
      "--project-name",
      "aegis",
      "--project-directory",
      path.dirname(runtime.composeFile),
      "--env-file",
      runtime.envFile,
      "-f",
      runtime.composeFile,
    ],
  ];
}

function runCompose(runtime, context, args, validate = true) {
  const [command, prefix] = composePrefix(runtime, context, validate);
  return context.runProcess(command, [...prefix, ...args], {
    cwd: runtime.projectRoot,
    env: context.env,
    quiet: false,
  });
}

function up(runtime, context, build) {
  const args = ["up", "-d"];
  if (build) args.push("--build");
  if (context.platform === "darwin") args.push(...MAC_CORE_SERVICES);
  return runCompose(runtime, context, args);
}

async function waitForDashboard(url, waitSeconds, context) {
  const deadline = Date.now() + waitSeconds * 1000;
  while (Date.now() < deadline) {
    const remaining = deadline - Date.now();
    if (await context.checkHealth(url, Math.min(2000, remaining))) return true;
    if (Date.now() >= deadline) return false;
    await context.sleep(Math.min(1000, deadline - Date.now()));
  }
  return false;
}

async function dashboardCommand(options, context) {
  const { runtime, created } = createRuntime(options, context, !options.noStart);
  if (created) {
    context.stdout(`Sichere Konfiguration erstellt: ${runtime.envFile}`);
    context.stdout("Dashboard-Zugang anzeigen: aeris credentials");
  }
  const url = dashboardUrl(runtime, context);
  context.stdout(`Dashboard: ${url}`);
  let healthy = await context.checkHealth(url, 2000);
  if (!healthy && options.noStart) {
    context.stderr(`Dashboard ist nicht erreichbar: ${url}`);
    return 1;
  }
  if (!healthy) {
    context.stdout("Dashboard läuft noch nicht; Aeris startet die Dienste …");
    if (context.platform === "darwin") {
      context.stdout("Hinweis: Der Linux-Host-Agent wird unter macOS nicht gestartet.");
    }
    const result = up(runtime, context, true);
    if (result !== 0) {
      context.stderr("Compose-Start fehlgeschlagen. Prüfe `aeris doctor`.");
      return result > 0 ? result : 1;
    }
    context.stdout(`Warte bis zu ${options.waitSeconds}s auf das Dashboard …`);
    healthy = await waitForDashboard(url, options.waitSeconds, context);
    if (!healthy) {
      context.stderr("Dashboard wurde nicht rechtzeitig gesund. Prüfe `aeris logs app migrate`.");
      return 1;
    }
  }
  if (!options.noBrowser && !context.openBrowser(url)) {
    context.stdout("Browser konnte nicht automatisch geöffnet werden; nutze die angezeigte URL.");
  }
  return 0;
}

function positiveInteger(raw, name) {
  const value = Number(raw);
  if (!Number.isInteger(value) || value <= 0) throw new CliError(`${name} muss größer als 0 sein.`);
  return value;
}

function extractGlobalOptions(argv) {
  const options = {};
  const remaining = [];
  for (let index = 0; index < argv.length; index += 1) {
    const argument = argv[index];
    const equals = argument.match(/^--(project-dir|env-file)=(.*)$/);
    if (equals) {
      options[equals[1] === "project-dir" ? "projectDir" : "envFile"] = equals[2];
      continue;
    }
    if (["--project-dir", "--env-file"].includes(argument)) {
      const value = argv[index + 1];
      if (!value || value.startsWith("-")) throw new CliError(`${argument} benötigt einen Pfad.`);
      options[argument === "--project-dir" ? "projectDir" : "envFile"] = value;
      index += 1;
      continue;
    }
    remaining.push(argument);
  }
  return { options, remaining };
}

export function parseArguments(argv) {
  const { options, remaining } = extractGlobalOptions(argv);
  if (remaining.includes("--version") || remaining.includes("-V")) return { ...options, command: "version" };
  const commands = new Set([
    "dashboard",
    "up",
    "down",
    "status",
    "logs",
    "doctor",
    "maintenance",
    "init",
    "credentials",
    "help",
  ]);
  let command = "dashboard";
  if (remaining.length && !remaining[0].startsWith("-")) {
    if (!commands.has(remaining[0])) throw new CliError(`Unbekannter Befehl: ${remaining[0]}`);
    command = remaining.shift();
  }
  if (remaining.includes("--help") || remaining.includes("-h")) return { ...options, command: "help" };
  options.command = command;
  if (command === "dashboard") {
    options.noStart = false;
    options.noBrowser = false;
    options.waitSeconds = DEFAULT_WAIT_SECONDS;
    for (let index = 0; index < remaining.length; index += 1) {
      const argument = remaining[index];
      if (argument === "--no-start") options.noStart = true;
      else if (argument === "--no-browser") options.noBrowser = true;
      else if (argument === "--wait-seconds") {
        options.waitSeconds = positiveInteger(remaining[index + 1], "--wait-seconds");
        index += 1;
      } else throw new CliError(`Unbekannte Option: ${argument}`);
    }
  } else if (command === "up") {
    options.build = true;
    for (const argument of remaining) {
      if (argument === "--no-build") options.build = false;
      else throw new CliError(`Unbekannte Option: ${argument}`);
    }
  } else if (command === "logs") {
    options.follow = false;
    options.tail = undefined;
    options.services = [];
    for (let index = 0; index < remaining.length; index += 1) {
      const argument = remaining[index];
      if (["-f", "--follow"].includes(argument)) options.follow = true;
      else if (argument === "--tail") {
        options.tail = positiveInteger(remaining[index + 1], "--tail");
        index += 1;
      } else {
        if (!SERVICE_PATTERN.test(argument)) throw new CliError("Ungültiger Compose-Servicename.");
        options.services.push(argument);
      }
    }
  } else if (command === "maintenance") {
    options.once = false;
    for (const argument of remaining) {
      if (argument === "--once") options.once = true;
      else throw new CliError(`Unbekannte Option: ${argument}`);
    }
  } else if (remaining.length) {
    throw new CliError(`Unerwartetes Argument: ${remaining[0]}`);
  }
  return options;
}

function helpText(version) {
  return `Aeris ${version} – Aegis sicher starten und bedienen

Verwendung:
  aeris                              Dashboard starten und im Browser öffnen
  aeris dashboard [Optionen]         Dashboard starten/öffnen
  aeris up [--no-build]              Dienste starten
  aeris down                         Dienste stoppen; Volumes behalten
  aeris status                       Compose-Status anzeigen
  aeris logs [services] [-f]         Logs anzeigen
  aeris doctor                       Installation und Konfiguration prüfen
  aeris maintenance [--once]         Retention-Worker ausführen
  aeris init                         sichere lokale Konfiguration anlegen
  aeris credentials                  Dashboard-Zugang anzeigen

Dashboard-Optionen:
  --no-start                         laufende Instanz nur prüfen
  --no-browser                       Browser nicht öffnen
  --wait-seconds N                   maximale Startwartezeit

Globale Optionen:
  --env-file PATH                    alternative .env-Datei
  --project-dir PATH                 alternatives Aeris-Paket
  --version                          Version anzeigen
  --help                             Hilfe anzeigen`;
}

async function doctorCommand(options, context) {
  const { runtime } = createRuntime(options, context, false);
  let failed = false;
  context.stdout(`[OK] Paket: ${runtime.projectRoot}`);
  const envExists = existsSync(runtime.envFile);
  context.stdout(`[${envExists ? "OK" : "FEHLER"}] Konfiguration: ${runtime.envFile}`);
  failed ||= !envExists;
  if (envExists) {
    const stats = lstatSync(runtime.envFile);
    const secure =
      stats.isFile() &&
      !stats.isSymbolicLink() &&
      (context.platform === "win32" || (stats.mode & 0o077) === 0);
    context.stdout(`[${secure ? "OK" : "FEHLER"}] Konfigurationsdatei ist privat`);
    failed ||= !secure;
  }
  const secretErrors = envExists ? validateSecrets(runtime, context) : ["nicht prüfbar"];
  context.stdout(`[${secretErrors.length ? "FEHLER" : "OK"}] Pflicht-Secrets${secretErrors.length ? `: ${secretErrors.join("; ")}` : ""}`);
  failed ||= secretErrors.length > 0;
  let executable;
  try {
    executable = composeExecutable(context, runtime);
    context.stdout(`[OK] Docker Compose: ${executable.join(" ")}`);
  } catch (error) {
    context.stdout(`[FEHLER] Docker Compose: ${error.message}`);
    failed = true;
  }
  if (executable) {
    const daemon = context.runProcess("docker", ["info"], {
      cwd: runtime.projectRoot,
      env: context.env,
      quiet: true,
    }) === 0;
    context.stdout(`[${daemon ? "OK" : "FEHLER"}] Docker-Daemon`);
    failed ||= !daemon;
  }
  if (executable && envExists && !secretErrors.length) {
    const valid = runCompose(runtime, context, ["config", "--quiet"]) === 0;
    context.stdout(`[${valid ? "OK" : "FEHLER"}] Compose-Konfiguration`);
    failed ||= !valid;
  }
  if (context.platform === "darwin") {
    context.stdout("[HINWEIS] Der Linux-Host-Agent ist unter macOS deaktiviert.");
  }
  try {
    const url = dashboardUrl(runtime, context);
    const healthy = await context.checkHealth(url, 2000);
    context.stdout(`[${healthy ? "OK" : "HINWEIS"}] Dashboard ${healthy ? "erreichbar" : "nicht erreichbar"}: ${url}`);
  } catch (error) {
    context.stdout(`[FEHLER] Dashboard-Adresse: ${error.message}`);
    failed = true;
  }
  return failed ? 1 : 0;
}

export async function run(argv = process.argv.slice(2), overrides = {}) {
  const context = createContext(overrides);
  try {
    const options = parseArguments([...argv]);
    const version = packageVersion(context.packageRoot);
    if (options.command === "version") {
      context.stdout(`aeris ${version}`);
      return 0;
    }
    if (options.command === "help") {
      context.stdout(helpText(version));
      return 0;
    }
    if (options.command === "dashboard") return await dashboardCommand(options, context);
    if (options.command === "init") {
      const { runtime, created } = createRuntime(options, context, true);
      context.stdout(`${created ? "Konfiguration erstellt" : "Konfiguration vorhanden"}: ${runtime.envFile}`);
      context.stdout("Dashboard-Zugang anzeigen: aeris credentials");
      return 0;
    }
    if (options.command === "credentials") {
      const { runtime } = createRuntime(options, context, false);
      if (!existsSync(runtime.envFile)) throw new CliError("Führe zuerst `aeris init` aus.");
      const username = setting(runtime, context, "AEGIS_API_USERNAME", "aegis");
      const password = setting(runtime, context, "AEGIS_API_PASSWORD", "");
      if (!password) throw new CliError("AEGIS_API_PASSWORD fehlt.");
      context.stdout(`Benutzername: ${username}`);
      context.stdout(`Passwort: ${password}`);
      return 0;
    }
    if (options.command === "doctor") return await doctorCommand(options, context);

    const initialize = ["up", "maintenance"].includes(options.command);
    const { runtime, created } = createRuntime(options, context, initialize);
    if (created) context.stdout(`Sichere Konfiguration erstellt: ${runtime.envFile}`);
    if (options.command === "up") return up(runtime, context, options.build);
    if (options.command === "down") return runCompose(runtime, context, ["down"]);
    if (options.command === "status") return runCompose(runtime, context, ["ps"]);
    if (options.command === "logs") {
      const args = ["logs"];
      if (options.follow) args.push("--follow");
      if (options.tail !== undefined) args.push("--tail", String(options.tail));
      args.push(...options.services);
      return runCompose(runtime, context, args);
    }
    if (options.command === "maintenance") {
      return options.once
        ? runCompose(runtime, context, [
            "run",
            "--rm",
            "maintenance",
            "python",
            "-m",
            "core.maintenance",
            "--once",
          ])
        : runCompose(runtime, context, ["up", "-d", "maintenance"]);
    }
    throw new CliError(`Unbekannter Befehl: ${options.command}`);
  } catch (error) {
    if (error instanceof CliError) {
      context.stderr(`aeris: ${error.message}`);
      return 2;
    }
    context.stderr("aeris: unerwarteter interner Fehler");
    return 2;
  }
}

let invokedPath = "";
try {
  invokedPath = process.argv[1] ? pathToFileURL(realpathSync(process.argv[1])).href : "";
} catch {
  // Importierte Module haben nicht zwingend einen auflösbaren argv-Einstiegspunkt.
}
if (import.meta.url === invokedPath) {
  process.exitCode = await run();
}
