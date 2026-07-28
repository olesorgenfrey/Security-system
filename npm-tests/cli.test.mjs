import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  symlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import test from "node:test";

import {
  browserInvocation,
  isAegisHealthPayload,
  parseEnvFile,
  run,
} from "../bin/aeris.mjs";

function createProject(root) {
  const project = path.join(root, "package");
  for (const directory of ["deploy", "config"]) {
    mkdirSync(path.join(project, directory), { recursive: true });
  }
  writeFileSync(path.join(project, "Dockerfile"), "FROM scratch\n");
  writeFileSync(path.join(project, "package.json"), '{"version":"0.1.0"}\n');
  writeFileSync(path.join(project, "pyproject.toml"), '[project]\nname = "aegis"\n');
  writeFileSync(path.join(project, "deploy", "docker-compose.yml"), "services: {}\n");
  writeFileSync(path.join(project, "config", "scope.yaml"), "allowlist: {}\n");
  writeFileSync(
    path.join(project, ".env.example"),
    [
      "POSTGRES_PASSWORD=",
      "REDIS_PASSWORD=",
      "AEGIS_API_PASSWORD=",
      "AEGIS_API_USERNAME=aegis",
      "AEGIS_BIND_ADDRESS=127.0.0.1",
      "AEGIS_HTTP_PORT=8123",
      "AERIS_CONFIG_DIR=../config",
      "HOST_LOG_DIR=/var/log",
      "HOST_AGENT_HOSTNAME=test-host",
      "HOST_AGENT_LOG_PATHS=/host/var/log/auth.log",
      "",
    ].join("\n"),
  );
  return project;
}

function harness(t, overrides = {}) {
  const root = mkdtempSync(path.join(tmpdir(), "aeris-npm-test-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const project = createProject(root);
  const elsewhere = path.join(root, "elsewhere");
  const home = path.join(root, "home");
  mkdirSync(elsewhere);
  mkdirSync(home);
  const stdout = [];
  const stderr = [];
  const processCalls = [];
  const browserCalls = [];
  const context = {
    cwd: elsewhere,
    env: {},
    homeDir: home,
    packageRoot: project,
    platform: overrides.platform ?? "linux",
    hostName: "unit-test-host",
    stdout: (message) => stdout.push(message),
    stderr: (message) => stderr.push(message),
    runProcess: (command, args, options) => {
      processCalls.push({ command, args: [...args], options });
      return overrides.processResult?.(command, args) ?? 0;
    },
    checkHealth: overrides.checkHealth ?? (async () => true),
    openBrowser: (url) => {
      browserCalls.push(url);
      return overrides.browserResult ?? true;
    },
    sleep: async () => {},
  };
  return { root, project, home, stdout, stderr, processCalls, browserCalls, context };
}

function defaultEnvFile(state) {
  return path.join(state.home, ".config", "aeris", ".env");
}

test("bare aeris creates secure config and opens a healthy dashboard", async (t) => {
  const state = harness(t);

  assert.equal(await run([], state.context), 0);
  assert.deepEqual(state.browserCalls, ["http://127.0.0.1:8123/"]);
  assert.equal(state.processCalls.length, 0);

  const envFile = defaultEnvFile(state);
  const values = parseEnvFile(envFile);
  const secrets = [
    values.POSTGRES_PASSWORD,
    values.REDIS_PASSWORD,
    values.AEGIS_API_PASSWORD,
  ];
  assert.equal(new Set(secrets).size, 3);
  assert.ok(secrets.every((secret) => /^[a-f0-9]{64}$/.test(secret)));
  assert.equal(statSync(envFile).mode & 0o777, 0o600);
  assert.ok(readFileSync(path.join(state.home, ".config", "aeris", "config", "scope.yaml"), "utf8"));
  const routineOutput = [...state.stdout, ...state.stderr].join("\n");
  assert.ok(secrets.every((secret) => !routineOutput.includes(secret)));
});

test("unhealthy macOS dashboard starts only core services then opens", async (t) => {
  const health = [false, true];
  const state = harness(t, {
    platform: "darwin",
    checkHealth: async () => health.shift() ?? true,
  });

  assert.equal(await run([], state.context), 0);
  const compose = state.processCalls.find(
    (call) => call.command === "docker" && call.args.includes("up"),
  );
  assert.ok(compose);
  assert.deepEqual(compose.args.slice(-4), [
    "app",
    "worker",
    "notification_worker",
    "maintenance",
  ]);
  assert.ok(compose.args.includes("--build"));
  assert.ok(!compose.args.includes("host_agent"));
  assert.deepEqual(state.browserCalls, ["http://127.0.0.1:8123/"]);
  assert.ok(state.stdout.some((line) => line.includes("Linux-Host-Agent")));
});

test("--no-start never creates config, starts Docker, or opens a browser", async (t) => {
  const state = harness(t, { checkHealth: async () => false });

  assert.equal(await run(["dashboard", "--no-start", "--no-browser"], state.context), 1);
  assert.equal(state.processCalls.length, 0);
  assert.equal(state.browserCalls.length, 0);
  assert.equal(statSync(state.home).isDirectory(), true);
  assert.throws(() => statSync(defaultEnvFile(state)));
});

test("an unrelated lookalike checkout in cwd is never trusted implicitly", async (t) => {
  const state = harness(t);
  mkdirSync(path.join(state.context.cwd, "deploy"), { recursive: true });
  writeFileSync(path.join(state.context.cwd, "Dockerfile"), "FROM malicious\n");
  writeFileSync(path.join(state.context.cwd, "pyproject.toml"), '[project]\nname = "aegis"\n');
  writeFileSync(path.join(state.context.cwd, "deploy", "docker-compose.yml"), "services: {}\n");

  assert.equal(await run(["init"], state.context), 0);
  assert.ok(existsSync(defaultEnvFile(state)));
  assert.equal(existsSync(path.join(state.context.cwd, ".env")), false);
});

test("compose commands use safe argv and down preserves volumes", async (t) => {
  const state = harness(t);
  assert.equal(await run(["init"], state.context), 0);

  const cases = [
    [["up", "--no-build"], ["up", "-d"]],
    [["down"], ["down"]],
    [["status"], ["ps"]],
    [["logs", "app", "worker", "-f", "--tail", "25"], ["logs", "--follow", "--tail", "25", "app", "worker"]],
    [["maintenance", "--once"], ["run", "--rm", "maintenance", "python", "-m", "core.maintenance", "--once"]],
  ];

  for (const [argv, suffix] of cases) {
    state.processCalls.length = 0;
    assert.equal(await run(argv, state.context), 0);
    const actual = state.processCalls.at(-1);
    assert.deepEqual(actual.args.slice(-suffix.length), suffix);
    const projectNameIndex = actual.args.indexOf("--project-name");
    assert.equal(actual.args[projectNameIndex + 1], "aegis");
    assert.equal(actual.options.shell, undefined);
    assert.ok(!actual.args.includes("--volumes"));
    assert.ok(!actual.args.includes("-v"));
  }
});

test("invalid log service is rejected before process execution", async (t) => {
  const state = harness(t);
  assert.equal(await run(["logs", "--volumes"], state.context), 2);
  assert.equal(state.processCalls.length, 0);
});

test("existing env is not overwritten and credentials reveal only dashboard secret", async (t) => {
  const state = harness(t);
  const envFile = defaultEnvFile(state);
  mkdirSync(path.dirname(envFile), { recursive: true });
  const existing = [
    "POSTGRES_PASSWORD=postgres-existing",
    "REDIS_PASSWORD=redis-existing",
    "AEGIS_API_PASSWORD=dashboard-existing-secret",
    "AEGIS_API_USERNAME=operator",
    "AEGIS_HTTP_PORT=8123",
    "",
  ].join("\n");
  writeFileSync(envFile, existing, { mode: 0o644 });

  assert.equal(await run(["init"], state.context), 0);
  assert.equal(readFileSync(envFile, "utf8"), existing);
  assert.equal(statSync(envFile).mode & 0o777, 0o600);
  assert.equal(
    readFileSync(path.join(state.home, ".config", "aeris", "config", "scope.yaml"), "utf8"),
    "allowlist: {}\n",
  );
  state.stdout.length = 0;
  assert.equal(await run(["credentials"], state.context), 0);
  const output = state.stdout.join("\n");
  assert.match(output, /Benutzername: operator/);
  assert.match(output, /Passwort: dashboard-existing-secret/);
  assert.ok(!output.includes("postgres-existing"));
  assert.ok(!output.includes("redis-existing"));
});

test("doctor reports an existing world-readable env without leaking it", async (t) => {
  const state = harness(t);
  const envFile = defaultEnvFile(state);
  mkdirSync(path.dirname(envFile), { recursive: true });
  const secret = "dashboard-doctor-secret";
  writeFileSync(
    envFile,
    [
      "POSTGRES_PASSWORD=postgres-doctor-secret",
      "REDIS_PASSWORD=redis-doctor-secret",
      `AEGIS_API_PASSWORD=${secret}`,
      "",
    ].join("\n"),
    { mode: 0o644 },
  );

  assert.equal(await run(["doctor"], state.context), 1);
  const output = [...state.stdout, ...state.stderr].join("\n");
  assert.match(output, /FEHLER.*privat/);
  assert.ok(!output.includes(secret));
});

test("init never changes the permissions of an explicit project directory", async (t) => {
  const state = harness(t);
  const envFile = path.join(state.project, ".env");
  writeFileSync(
    envFile,
    [
      "POSTGRES_PASSWORD=postgres-external-secret",
      "REDIS_PASSWORD=redis-external-secret",
      "AEGIS_API_PASSWORD=dashboard-external-secret",
      "",
    ].join("\n"),
    { mode: 0o644 },
  );
  chmodSync(state.project, 0o755);

  assert.equal(await run(["init", "--project-dir", state.project], state.context), 0);
  assert.equal(statSync(state.project).mode & 0o777, 0o755);
  assert.equal(statSync(envFile).mode & 0o777, 0o600);
});

test("custom URL secrets and malformed URLs are never echoed", async (t) => {
  const state = harness(t);
  state.context.env.AERIS_DASHBOARD_URL = "https://example.test/console/?token=do-not-print";

  assert.equal(await run(["dashboard", "--no-start"], state.context), 2);
  const output = [...state.stdout, ...state.stderr].join("\n");
  assert.ok(!output.includes("do-not-print"));
  assert.ok(!output.includes(state.context.env.AERIS_DASHBOARD_URL));
});

test("global options work between log services", async (t) => {
  const state = harness(t);
  assert.equal(await run(["init"], state.context), 0);
  state.processCalls.length = 0;

  assert.equal(
    await run(
      ["logs", "app", "--env-file", defaultEnvFile(state), "worker"],
      state.context,
    ),
    0,
  );
  assert.deepEqual(state.processCalls.at(-1).args.slice(-3), ["logs", "app", "worker"]);
});

test("Windows browser launch keeps metacharacters inside one explorer argument", () => {
  const url = "https://example.test/a&whoami|calc%PATH%/";
  assert.deepEqual(browserInvocation(url, "win32"), ["explorer.exe", [url]]);
});

test("health identity rejects an unrelated HTTP service", () => {
  assert.equal(isAegisHealthPayload({ status: "ok", service: "aegis" }), true);
  assert.equal(isAegisHealthPayload({ status: "ok" }), false);
  assert.equal(isAegisHealthPayload({ status: "ok", service: "another-app" }), false);
});

test("init rejects a symlinked env file without changing its target", async (t) => {
  const state = harness(t);
  const target = path.join(state.root, "outside.env");
  const envFile = defaultEnvFile(state);
  const contents = "AEGIS_API_PASSWORD=do-not-touch\n";
  writeFileSync(target, contents, { mode: 0o644 });
  mkdirSync(path.dirname(envFile), { recursive: true });
  symlinkSync(target, envFile);

  assert.equal(await run(["init"], state.context), 2);
  assert.equal(readFileSync(target, "utf8"), contents);
  assert.match(state.stderr.join("\n"), /reguläre Datei/);
  state.stderr.length = 0;
  assert.equal(await run(["credentials"], state.context), 2);
  assert.match(state.stderr.join("\n"), /reguläre Datei/);
});
