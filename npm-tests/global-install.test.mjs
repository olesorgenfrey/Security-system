import assert from "node:assert/strict";
import {
  chmodSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const NPM = process.platform === "win32" ? "npm.cmd" : "npm";

function execute(command, args, options = {}) {
  return spawnSync(command, args, {
    cwd: options.cwd,
    env: options.env,
    encoding: "utf8",
    shell: false,
  });
}

test("packed CLI installs globally and runs outside the checkout without uv", (t) => {
  const root = mkdtempSync(path.join(tmpdir(), "aeris global install-"));
  t.after(() => rmSync(root, { recursive: true, force: true }));
  const prefix = path.join(root, "prefix");
  const elsewhere = path.join(root, "elsewhere");
  const home = path.join(root, "home");
  const xdg = path.join(root, "xdg");
  mkdirSync(elsewhere);
  mkdirSync(home);

  const packed = execute(
    NPM,
    ["pack", "--json", "--ignore-scripts", "--pack-destination", root],
    { cwd: PROJECT_ROOT },
  );
  assert.equal(packed.status, 0, packed.stderr || packed.stdout);
  const archive = path.join(root, JSON.parse(packed.stdout)[0].filename);

  const installed = execute(
    NPM,
    [
      "install",
      "--global",
      "--prefix",
      prefix,
      "--ignore-scripts",
      "--no-audit",
      "--no-fund",
      archive,
    ],
    { cwd: elsewhere },
  );
  assert.equal(installed.status, 0, installed.stderr || installed.stdout);

  const executable =
    process.platform === "win32" ? path.join(prefix, "aeris.cmd") : path.join(prefix, "bin", "aeris");
  assert.ok(existsSync(executable));
  const env = { ...process.env, HOME: home, XDG_CONFIG_HOME: xdg };
  delete env.AERIS_HOME;
  delete env.AERIS_PROJECT_DIR;
  delete env.AERIS_ENV_FILE;

  const version = execute(executable, ["--version"], { cwd: elsewhere, env });
  assert.equal(version.status, 0, version.stderr || version.stdout);
  assert.match(version.stdout, /^aeris 0\.1\.0\s*$/);

  const initialized = execute(executable, ["init"], { cwd: elsewhere, env });
  assert.equal(initialized.status, 0, initialized.stderr || initialized.stdout);
  const envFile = path.join(xdg, "aeris", ".env");
  const contents = readFileSync(envFile, "utf8");
  const secrets = ["POSTGRES_PASSWORD", "REDIS_PASSWORD", "AEGIS_API_PASSWORD"].map(
    (name) => contents.match(new RegExp(`^${name}=([a-f0-9]{64})$`, "m"))?.[1],
  );
  assert.ok(secrets.every(Boolean));
  assert.equal(new Set(secrets).size, 3);
  assert.ok(secrets.every((secret) => !initialized.stdout.includes(secret)));
  if (process.platform !== "win32") assert.equal(statSync(envFile).mode & 0o777, 0o600);

  const installedRoot =
    process.platform === "win32"
      ? path.join(prefix, "node_modules", "aeris-security-cli")
      : path.join(prefix, "lib", "node_modules", "aeris-security-cli");
  assert.ok(existsSync(path.join(installedRoot, "deploy", "docker-compose.yml")));
  assert.ok(existsSync(path.join(installedRoot, "dashboard", "templates", "index.html")));

  if (process.platform !== "win32") {
    const fakeBin = path.join(root, "fake bin");
    const dockerLog = path.join(root, "docker-argv.jsonl");
    mkdirSync(fakeBin);
    const fakeDocker = path.join(fakeBin, "docker");
    writeFileSync(
      fakeDocker,
      [
        "#!/usr/bin/env node",
        'const fs = require("node:fs");',
        'fs.appendFileSync(process.env.AERIS_TEST_DOCKER_LOG, JSON.stringify(process.argv.slice(2)) + "\\n");',
        "",
      ].join("\n"),
      { mode: 0o755 },
    );
    chmodSync(fakeDocker, 0o755);
    const composeEnv = {
      ...env,
      PATH: `${fakeBin}${path.delimiter}${env.PATH}`,
      AERIS_TEST_DOCKER_LOG: dockerLog,
      COMPOSE_PROJECT_NAME: "must-not-win",
    };
    const status = execute(executable, ["status"], { cwd: elsewhere, env: composeEnv });
    assert.equal(status.status, 0, status.stderr || status.stdout);
    const calls = readFileSync(dockerLog, "utf8")
      .trim()
      .split("\n")
      .map((line) => JSON.parse(line));
    assert.deepEqual(calls[0], ["compose", "version"]);
    assert.deepEqual(calls[1], [
      "compose",
      "--project-name",
      "aegis",
      "--project-directory",
      path.join(installedRoot, "deploy"),
      "--env-file",
      envFile,
      "-f",
      path.join(installedRoot, "deploy", "docker-compose.yml"),
      "ps",
    ]);
  }
});
