import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";
import { fileURLToPath } from "node:url";

const PROJECT_ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

test("npm tarball contains the runtime but no caches, tests, or secrets", () => {
  const npm = process.platform === "win32" ? "npm.cmd" : "npm";
  const result = spawnSync(npm, ["pack", "--dry-run", "--json", "--ignore-scripts"], {
    cwd: PROJECT_ROOT,
    encoding: "utf8",
    shell: false,
  });
  assert.equal(result.status, 0, result.stderr || result.stdout);

  const [metadata] = JSON.parse(result.stdout);
  const entries = new Map(metadata.files.map((entry) => [entry.path, entry]));
  const required = [
    ".dockerignore",
    ".env.example",
    "Dockerfile",
    "README.md",
    "aeris/cli.py",
    "alembic/versions/0004_align_schema_constraints.py",
    "api/main.py",
    "bin/aeris.mjs",
    "config/scope.yaml",
    "core/ingestion/consumer.py",
    "dashboard/static/dashboard.js",
    "dashboard/templates/alerts.html",
    "dashboard/templates/index.html",
    "deploy/docker-compose.yml",
    "package.json",
    "pyproject.toml",
    "rules/new_admin_account.yml",
    "uv.lock",
  ];
  for (const file of required) assert.ok(entries.has(file), `${file} fehlt im npm-Paket`);
  assert.equal(entries.get("bin/aeris.mjs").mode & 0o777, 0o755);

  const forbidden = /(^|\/)(__pycache__|tests?|npm-tests)(\/|$)|\.py[co]$|(^|\/)\.env$|\.(pem|key)$/;
  const leaked = [...entries.keys()].filter((file) => forbidden.test(file));
  assert.deepEqual(leaked, []);

  const packageJson = JSON.parse(readFileSync(path.join(PROJECT_ROOT, "package.json"), "utf8"));
  const pyproject = readFileSync(path.join(PROJECT_ROOT, "pyproject.toml"), "utf8");
  const pythonVersion = pyproject.match(/^version\s*=\s*"([^"]+)"$/m)?.[1];
  assert.equal(packageJson.version, pythonVersion);
  for (const lifecycle of ["preinstall", "install", "postinstall", "prepare"]) {
    assert.equal(packageJson.scripts?.[lifecycle], undefined);
  }
});
