"""Safe command-line frontend for the local Aegis Docker Compose deployment."""

from __future__ import annotations

import argparse
import contextlib
import ipaddress
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import tomllib
import urllib.parse
import urllib.request
import webbrowser
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from aeris import __version__

_COMPOSE_RELATIVE_PATH = Path("deploy/docker-compose.yml")
_REQUIRED_SECRETS = ("POSTGRES_PASSWORD", "REDIS_PASSWORD", "AEGIS_API_PASSWORD")
_DEFAULT_DASHBOARD_WAIT_SECONDS = 120
_SERVICE_NAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_UNQUOTED_COMMENT_PATTERN = re.compile(r"\s+#")
_ENV_EXPRESSION_PATTERN = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*)(?:(:-|-|:\?|\?|:\+|\+)(.*))?$",
    re.DOTALL,
)
_PROJECT_NAME = "aegis"
_PROJECT_ENTRY_POINT = "aeris.cli:main"


class CliError(RuntimeError):
    """An expected, user-actionable CLI failure."""


@dataclass(frozen=True)
class Runtime:
    project_dir: Path
    env_file: Path
    compose_file: Path
    env_values: dict[str, str]


@dataclass
class _HealthProbe:
    done: threading.Event
    result: bool = False


_HEALTH_PROBES: dict[str, _HealthProbe] = {}
_HEALTH_PROBES_LOCK = threading.Lock()


def _config_file() -> Path:
    config_home = os.environ.get("XDG_CONFIG_HOME")
    base = Path(config_home).expanduser() if config_home else Path.home() / ".config"
    return base / "aeris" / "config.toml"


def _is_project_dir(path: Path) -> bool:
    pyproject = path / "pyproject.toml"
    if not pyproject.is_file() or not (path / _COMPOSE_RELATIVE_PATH).is_file():
        return False
    try:
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return False
    project = data.get("project")
    if not isinstance(project, dict) or project.get("name") != _PROJECT_NAME:
        return False
    scripts = project.get("scripts")
    return isinstance(scripts, dict) and scripts.get("aeris") == _PROJECT_ENTRY_POINT


def _read_configured_project() -> Path | None:
    path = _config_file()
    if not path.is_file():
        return None
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return None
    configured = data.get("project_dir")
    if not isinstance(configured, str) or not configured.strip():
        return None
    return Path(configured).expanduser()


def _resolve_path(path: Path, *, label: str) -> Path:
    try:
        return path.expanduser().resolve()
    except (OSError, RuntimeError) as exc:
        raise CliError(f"{label} kann nicht aufgelöst werden: {exc}") from exc


def _candidate_project_dirs() -> list[Path]:
    candidates: list[Path] = []
    configured = _read_configured_project()
    if configured is not None:
        candidates.append(configured)

    # Editable tool installations keep this package inside the repository.
    with contextlib.suppress(OSError, RuntimeError):
        candidates.append(Path(__file__).resolve().parents[1])

    unique: list[Path] = []
    seen: set[Path] = set()
    for candidate in candidates:
        try:
            resolved = candidate.expanduser().resolve()
        except (OSError, RuntimeError):
            continue
        if resolved not in seen:
            unique.append(resolved)
            seen.add(resolved)
    return unique


def _resolve_project_dir(explicit: Path | None) -> Path:
    if explicit is not None:
        candidate = _resolve_path(explicit, label="Projektpfad")
        if not _is_project_dir(candidate):
            raise CliError(f"Kein Aeris-Projekt unter {candidate} gefunden.")
        return candidate

    from_environment = os.environ.get("AERIS_PROJECT_DIR")
    if from_environment:
        candidate = _resolve_path(Path(from_environment), label="AERIS_PROJECT_DIR")
        if not _is_project_dir(candidate):
            raise CliError(f"AERIS_PROJECT_DIR zeigt auf kein Aeris-Projekt: {candidate}.")
        return candidate

    for candidate in _candidate_project_dirs():
        if _is_project_dir(candidate):
            return candidate
    raise CliError(
        "Aeris-Projekt nicht gefunden. Nutze `aeris configure /pfad/zum/repository` "
        "oder --project-dir."
    )


def _closing_quote(value: str, quote: str) -> int | None:
    for index in range(1, len(value)):
        if value[index] != quote:
            continue
        backslashes = 0
        cursor = index - 1
        while cursor >= 0 and value[cursor] == "\\":
            backslashes += 1
            cursor -= 1
        if backslashes % 2 == 0:
            return index
    return None


def _decode_quoted_env(value: str, quote: str) -> str:
    if quote == "'":
        return value.replace("\\'", "'")
    escapes = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "\\": "\\"}
    decoded: list[str] = []
    index = 0
    while index < len(value):
        character = value[index]
        if character == "\\" and index + 1 < len(value):
            escaped = value[index + 1]
            replacement = escapes.get(escaped)
            if replacement is not None:
                decoded.append(replacement)
                index += 2
                continue
        decoded.append(character)
        index += 1
    return "".join(decoded)


def _environment_value(values: dict[str, str], name: str) -> tuple[bool, str]:
    if name in os.environ:
        return True, os.environ[name]
    if name in values:
        return True, values[name]
    return False, ""


def _matching_brace(value: str, opening: int) -> int | None:
    depth = 1
    index = opening + 1
    while index < len(value):
        if value.startswith("${", index):
            depth += 1
            index += 2
            continue
        if value[index] == "}":
            depth -= 1
            if depth == 0:
                return index
        index += 1
    return None


def _expand_env_expression(
    expression: str,
    values: dict[str, str],
    *,
    path: Path,
    line_number: int,
    depth: int,
) -> str:
    match = _ENV_EXPRESSION_PATTERN.fullmatch(expression)
    if match is None:
        raise CliError(f"Ungültige Variablenexpansion in {path}, Zeile {line_number}.")
    name, operator, word = match.groups()
    is_set, current = _environment_value(values, name)
    is_nonempty = is_set and bool(current)
    if operator is None:
        return current
    replacement = word or ""
    if operator == ":-":
        return (
            current
            if is_nonempty
            else _expand_env_value(
                replacement, values, path=path, line_number=line_number, depth=depth + 1
            )
        )
    if operator == "-":
        return (
            current
            if is_set
            else _expand_env_value(
                replacement, values, path=path, line_number=line_number, depth=depth + 1
            )
        )
    if operator in {":?", "?"}:
        valid = is_nonempty if operator == ":?" else is_set
        if not valid:
            raise CliError(f"Variable {name} fehlt in {path}, Zeile {line_number}.")
        return current
    if operator == ":+":
        return (
            _expand_env_value(
                replacement, values, path=path, line_number=line_number, depth=depth + 1
            )
            if is_nonempty
            else ""
        )
    return (
        _expand_env_value(replacement, values, path=path, line_number=line_number, depth=depth + 1)
        if is_set
        else ""
    )


def _expand_env_value(
    value: str,
    values: dict[str, str],
    *,
    path: Path,
    line_number: int,
    depth: int = 0,
) -> str:
    if depth > 20:
        raise CliError(f"Zu tiefe Variablenexpansion in {path}, Zeile {line_number}.")
    expanded: list[str] = []
    index = 0
    while index < len(value):
        if value[index] != "$":
            expanded.append(value[index])
            index += 1
            continue
        if index + 1 >= len(value):
            expanded.append("$")
            break
        if value[index + 1] == "$":
            expanded.append("$")
            index += 2
            continue
        if value[index + 1] == "{":
            closing = _matching_brace(value, index + 1)
            if closing is None:
                raise CliError(f"Offene Variablenexpansion in {path}, Zeile {line_number}.")
            expanded.append(
                _expand_env_expression(
                    value[index + 2 : closing],
                    values,
                    path=path,
                    line_number=line_number,
                    depth=depth,
                )
            )
            index = closing + 1
            continue
        name = re.match(r"[A-Za-z_][A-Za-z0-9_]*", value[index + 1 :])
        if name is None:
            expanded.append("$")
            index += 1
            continue
        expanded.append(_environment_value(values, name.group(0))[1])
        index += len(name.group(0)) + 1
    return "".join(expanded)


def _parse_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise CliError(f"Konfiguration {path} kann nicht gelesen werden: {exc}") from exc

    values: dict[str, str] = {}
    index = 0
    while index < len(lines):
        assignment_line = index + 1
        assignment = lines[index].strip()
        if not assignment or assignment.startswith("#"):
            index += 1
            continue
        if assignment.startswith("export "):
            assignment = assignment[7:].lstrip()
        key, separator, raw_value = assignment.partition("=")
        key = key.strip()
        if not _ENV_KEY_PATTERN.fullmatch(key):
            raise CliError(f"Ungültiger Variablenname in {path}, Zeile {assignment_line}.")
        raw_value = raw_value.lstrip() if separator else ""

        if raw_value.startswith(("'", '"')):
            quote = raw_value[0]
            closing = _closing_quote(raw_value, quote)
            while closing is None and index + 1 < len(lines):
                index += 1
                raw_value += "\n" + lines[index]
                closing = _closing_quote(raw_value, quote)
            if closing is None:
                raise CliError(f"Offenes Anführungszeichen in {path}, Zeile {assignment_line}.")
            trailing = raw_value[closing + 1 :].strip()
            if trailing and not trailing.startswith("#"):
                raise CliError(f"Ungültiger Wert in {path}, Zeile {assignment_line}.")
            value = _decode_quoted_env(raw_value[1:closing], quote)
            if quote == '"':
                value = _expand_env_value(value, values, path=path, line_number=assignment_line)
        else:
            comment = _UNQUOTED_COMMENT_PATTERN.search(raw_value)
            if comment is not None:
                raw_value = raw_value[: comment.start()]
            value = _expand_env_value(
                raw_value.rstrip(), values, path=path, line_number=assignment_line
            )
        values[key] = value
        index += 1
    return values


def _runtime(args: argparse.Namespace) -> Runtime:
    project_dir = _resolve_project_dir(args.project_dir)
    env_file = args.env_file or Path(".env")
    if not env_file.is_absolute():
        env_file = project_dir / env_file
    env_file = _resolve_path(env_file, label="Umgebungsdatei")
    return Runtime(
        project_dir=project_dir,
        env_file=env_file,
        compose_file=_resolve_path(project_dir / _COMPOSE_RELATIVE_PATH, label="Compose-Datei"),
        env_values=_parse_env_file(env_file),
    )


def _setting(runtime: Runtime, name: str, default: str | None = None) -> str | None:
    return os.environ.get(name, runtime.env_values.get(name, default))


def _dashboard_url(runtime: Runtime) -> str:
    configured = _setting(runtime, "AERIS_DASHBOARD_URL")
    if configured:
        url = configured.strip()
    else:
        raw_port = _setting(runtime, "AEGIS_HTTP_PORT", "8000") or "8000"
        try:
            port = int(raw_port)
        except ValueError as exc:
            raise CliError("AEGIS_HTTP_PORT muss eine Zahl sein.") from exc
        if not 1 <= port <= 65_535:
            raise CliError("AEGIS_HTTP_PORT muss zwischen 1 und 65535 liegen.")

        host = (_setting(runtime, "AEGIS_BIND_ADDRESS", "127.0.0.1") or "127.0.0.1").strip()
        if host in {"0.0.0.0", "::", "[::]"}:
            host = "127.0.0.1"
        if (
            not host
            or any(character.isspace() for character in host)
            or any(character in host for character in "/@?#")
        ):
            raise CliError("AEGIS_BIND_ADDRESS enthält keine gültige Host-Adresse.")
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        url = f"http://{host}:{port}/"

    try:
        parsed = urllib.parse.urlsplit(url)
        parsed_port = parsed.port
    except ValueError as exc:
        raise CliError("AERIS_DASHBOARD_URL ist keine gültige HTTP(S)-Adresse.") from exc
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or not parsed.hostname:
        raise CliError("AERIS_DASHBOARD_URL muss eine vollständige HTTP(S)-Adresse sein.")
    if parsed.username or parsed.password:
        raise CliError("Zugangsdaten gehören nicht in AERIS_DASHBOARD_URL.")
    if parsed.query or parsed.fragment:
        raise CliError("AERIS_DASHBOARD_URL darf weder Query noch Fragment enthalten.")
    if parsed_port is not None and not 1 <= parsed_port <= 65_535:
        raise CliError("Der Port in AERIS_DASHBOARD_URL muss zwischen 1 und 65535 liegen.")
    if any(character.isspace() for character in parsed.hostname):
        raise CliError("AERIS_DASHBOARD_URL enthält keinen gültigen Hostnamen.")
    path = parsed.path.rstrip("/") + "/"
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


def _is_literal_loopback_address(value: str | None) -> bool:
    if value is None:
        return False
    candidate = value.strip().removeprefix("[").removesuffix("]")
    try:
        return ipaddress.ip_address(candidate).is_loopback
    except ValueError:
        return False


def _validate_local_test_mode(runtime: Runtime, dashboard_url: str) -> None:
    bind_address = _setting(runtime, "AEGIS_BIND_ADDRESS", "127.0.0.1")
    if not _is_literal_loopback_address(bind_address):
        raise CliError(
            "--no-auth ist nur mit einer wörtlichen Loopback-Adresse in AEGIS_BIND_ADDRESS erlaubt."
        )
    dashboard_host = urllib.parse.urlsplit(dashboard_url).hostname
    if not _is_literal_loopback_address(dashboard_host):
        raise CliError("--no-auth darf nur mit einer lokalen Dashboard-URL verwendet werden.")


def _health_url(dashboard_url: str) -> str:
    parsed = urllib.parse.urlsplit(dashboard_url)
    return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, "/health", "", ""))


def _is_aegis_health_payload(payload: object) -> bool:
    return (
        isinstance(payload, dict)
        and payload.get("status") == "ok"
        and payload.get("service") == "aegis"
    )


def _probe_dashboard(dashboard_url: str, timeout: float, probe: _HealthProbe) -> None:
    request = urllib.request.Request(
        _health_url(dashboard_url), headers={"Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read(4097)
            payload = json.loads(body) if len(body) <= 4096 else None
            probe.result = int(response.status) == 200 and _is_aegis_health_payload(payload)
    except Exception:
        probe.result = False
    finally:
        probe.done.set()
        with _HEALTH_PROBES_LOCK:
            if _HEALTH_PROBES.get(dashboard_url) is probe:
                del _HEALTH_PROBES[dashboard_url]


def _dashboard_healthy(dashboard_url: str, timeout: float = 2.0) -> bool:
    if timeout <= 0:
        return False
    with _HEALTH_PROBES_LOCK:
        probe = _HEALTH_PROBES.get(dashboard_url)
        if probe is None:
            probe = _HealthProbe(done=threading.Event())
            _HEALTH_PROBES[dashboard_url] = probe
            try:
                threading.Thread(
                    target=_probe_dashboard,
                    args=(dashboard_url, timeout, probe),
                    name="aeris-health-probe",
                    daemon=True,
                ).start()
            except RuntimeError:
                del _HEALTH_PROBES[dashboard_url]
                return False
    if not probe.done.wait(timeout):
        with _HEALTH_PROBES_LOCK:
            if _HEALTH_PROBES.get(dashboard_url) is probe:
                del _HEALTH_PROBES[dashboard_url]
        return False
    return probe.result


def _open_browser(url: str) -> bool:
    try:
        return bool(webbrowser.open(url, new=2))
    except Exception:
        return False


def _run_process(
    argv: Sequence[str],
    *,
    cwd: Path,
    quiet: bool = False,
    environment_overrides: Mapping[str, str] | None = None,
) -> int:
    try:
        completed = subprocess.run(
            list(argv),
            cwd=cwd,
            check=False,
            shell=False,
            env=(
                None if environment_overrides is None else {**os.environ, **environment_overrides}
            ),
            stdout=subprocess.DEVNULL if quiet else None,
            stderr=subprocess.DEVNULL if quiet else None,
        )
    except OSError as exc:
        raise CliError(f"Befehl {argv[0]!r} konnte nicht gestartet werden: {exc}") from exc
    return completed.returncode


def _command_available(command: str) -> bool:
    return shutil.which(command) is not None


def _compose_executable(project_dir: Path) -> tuple[str, ...]:
    if (
        _command_available("docker")
        and _run_process(("docker", "compose", "version"), cwd=project_dir, quiet=True) == 0
    ):
        return ("docker", "compose")
    if (
        _command_available("docker-compose")
        and _run_process(("docker-compose", "version"), cwd=project_dir, quiet=True) == 0
    ):
        return ("docker-compose",)
    raise CliError("Docker Compose wurde nicht gefunden. Installiere Docker Compose v2.")


def _secret_errors(runtime: Runtime) -> list[str]:
    values = [_setting(runtime, name) or "" for name in _REQUIRED_SECRETS]
    errors = [
        f"{name} fehlt oder ist leer"
        for name, value in zip(_REQUIRED_SECRETS, values, strict=True)
        if not value
    ]
    if values[2] and len(values[2]) < 16:
        errors.append("AEGIS_API_PASSWORD muss mindestens 16 Zeichen lang sein")
    for name, value in zip(_REQUIRED_SECRETS[:2], values[:2], strict=True):
        if value and re.fullmatch(r"[A-Za-z0-9._~-]+", value) is None:
            errors.append(f"{name} muss URL-sicher sein (empfohlen: openssl rand -hex 32)")
    nonempty = [value for value in values if value]
    if len(nonempty) != len(set(nonempty)):
        errors.append("POSTGRES-, REDIS- und API-Passwort müssen unterschiedlich sein")
    return errors


def _compose_prefix(runtime: Runtime, *, validate: bool = True) -> list[str]:
    if not runtime.env_file.is_file():
        raise CliError(
            f"{runtime.env_file} fehlt. Kopiere zuerst .env.example nach .env und setze Secrets."
        )
    if validate:
        errors = _secret_errors(runtime)
        if errors:
            raise CliError("Ungültige .env-Konfiguration: " + "; ".join(errors))
    return [
        *_compose_executable(runtime.project_dir),
        "--project-name",
        _PROJECT_NAME,
        "--env-file",
        str(runtime.env_file),
        "-f",
        str(runtime.compose_file),
    ]


def _compose(
    runtime: Runtime,
    arguments: Sequence[str],
    *,
    environment_overrides: Mapping[str, str] | None = None,
) -> int:
    return _run_process(
        [*_compose_prefix(runtime), *arguments],
        cwd=runtime.project_dir,
        environment_overrides=environment_overrides,
    )


def _up(
    runtime: Runtime,
    *,
    build: bool,
    auth_disabled: bool = False,
    services: Sequence[str] = (),
) -> int:
    arguments = ["up", "-d"]
    if build:
        arguments.append("--build")
    arguments.extend(services)
    return _compose(
        runtime,
        arguments,
        environment_overrides={"AEGIS_API_AUTH_DISABLED": "true" if auth_disabled else "false"},
    )


def _wait_for_dashboard(url: str, wait_seconds: int) -> bool:
    deadline = time.monotonic() + wait_seconds
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        if _dashboard_healthy(url, timeout=min(2.0, remaining)):
            return True
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return False
        time.sleep(min(1.0, remaining))


def _dashboard_command(runtime: Runtime, args: argparse.Namespace) -> int:
    if args.no_auth and args.no_start:
        raise CliError("--no-auth kann nicht mit --no-start kombiniert werden.")
    url = _dashboard_url(runtime)
    if args.no_auth:
        _validate_local_test_mode(runtime, url)
    print(f"Dashboard: {url}")
    healthy = _dashboard_healthy(url)
    if not healthy and args.no_start:
        print(f"Dashboard ist nicht erreichbar: {url}", file=sys.stderr)
        return 1

    if args.no_auth:
        print(
            "WARNUNG: Die Dashboard-Anmeldung ist nur für diesen lokalen Testmodus ausgeschaltet."
        )
        print("Ein normaler Aufruf von `aeris` oder `aeris up` schaltet sie wieder ein.")
    if not healthy:
        print("Dashboard läuft noch nicht; Aeris startet die Dienste …")
        result = _up(runtime, build=True, auth_disabled=args.no_auth)
        if result != 0:
            print(
                "Compose-Start fehlgeschlagen. Prüfe `aeris doctor` und die Logs.", file=sys.stderr
            )
            return result
        print(f"Warte bis zu {args.wait_seconds}s auf das Dashboard …")
        if not _wait_for_dashboard(url, args.wait_seconds):
            print(
                "Dashboard wurde nicht rechtzeitig gesund. "
                f"Prüfe `aeris logs app migrate`. URL: {url}",
                file=sys.stderr,
            )
            return 1
    elif not args.no_start:
        # Reconcile even a healthy app so a normal invocation always exits test mode.
        result = _up(
            runtime,
            build=args.no_auth,
            auth_disabled=args.no_auth,
            services=("app",),
        )
        if result != 0:
            print(
                "Anmeldemodus konnte nicht gesetzt werden. Prüfe `aeris doctor`.",
                file=sys.stderr,
            )
            return result
        if not _wait_for_dashboard(url, args.wait_seconds):
            print(
                "Dashboard wurde nach dem Moduswechsel nicht rechtzeitig gesund.",
                file=sys.stderr,
            )
            return 1

    if not args.no_browser and not _open_browser(url):
        print("Browser konnte nicht automatisch geöffnet werden; nutze die angezeigte URL.")
    return 0


def _print_check(ok: bool, label: str, detail: str = "") -> None:
    suffix = f": {detail}" if detail else ""
    print(f"[{'OK' if ok else 'FEHLER'}] {label}{suffix}")


def _host_log_sources(runtime: Runtime) -> list[Path]:
    host_dir = Path(_setting(runtime, "HOST_LOG_DIR", "/var/log") or "/var/log").expanduser()
    if not host_dir.is_absolute():
        host_dir = runtime.compose_file.parent / host_dir
    host_dir = _resolve_path(host_dir, label="HOST_LOG_DIR")
    configured = _setting(runtime, "HOST_AGENT_LOG_PATHS", "/host/var/log/auth.log") or ""
    sources: list[Path] = []
    prefix = "/host/var/log/"
    for item in configured.split(","):
        target = item.strip()
        if target.startswith(prefix):
            source = _resolve_path(
                host_dir / target.removeprefix(prefix), label="HOST_AGENT_LOG_PATHS"
            )
            try:
                source.relative_to(host_dir)
            except ValueError:
                continue
            sources.append(source)
    return sources


def _doctor(runtime: Runtime) -> int:
    failed = False
    _print_check(True, "Projekt", str(runtime.project_dir))

    env_exists = runtime.env_file.is_file()
    _print_check(env_exists, "Umgebungsdatei", str(runtime.env_file))
    failed |= not env_exists

    secret_errors = _secret_errors(runtime) if env_exists else ["nicht prüfbar"]
    _print_check(not secret_errors, "Pflicht-Secrets", "; ".join(secret_errors))
    failed |= bool(secret_errors)

    compose: tuple[str, ...] | None = None
    try:
        compose = _compose_executable(runtime.project_dir)
    except CliError as exc:
        _print_check(False, "Docker Compose", str(exc))
        failed = True
    else:
        _print_check(True, "Docker Compose", " ".join(compose))

    docker_ready = False
    if compose and _command_available("docker"):
        docker_ready = _run_process(("docker", "info"), cwd=runtime.project_dir, quiet=True) == 0
        _print_check(docker_ready, "Docker-Daemon")
        failed |= not docker_ready
    elif compose and env_exists and not secret_errors:
        prefix = [
            *compose,
            "--env-file",
            str(runtime.env_file),
            "-f",
            str(runtime.compose_file),
        ]
        docker_ready = _run_process([*prefix, "ps", "-q"], cwd=runtime.project_dir, quiet=True) == 0
        _print_check(docker_ready, "Docker-Daemon")
        failed |= not docker_ready

    if compose and env_exists and not secret_errors:
        prefix = [
            *compose,
            "--env-file",
            str(runtime.env_file),
            "-f",
            str(runtime.compose_file),
        ]
        config_valid = (
            _run_process([*prefix, "config", "--quiet"], cwd=runtime.project_dir, quiet=True) == 0
        )
        _print_check(config_valid, "Compose-Konfiguration")
        failed |= not config_valid

    sources = _host_log_sources(runtime)
    logs_ok = bool(sources) and all(source.is_file() for source in sources)
    detail = ", ".join(str(source) for source in sources) or "kein gültiger Host-Pfad"
    _print_check(logs_ok, "Host-Authentifizierungslog", detail)
    failed |= not logs_ok

    try:
        url = _dashboard_url(runtime)
        dashboard_ok = _dashboard_healthy(url)
    except CliError as exc:
        _print_check(False, "Dashboard-Adresse", str(exc))
        failed = True
    else:
        if dashboard_ok:
            _print_check(True, "Dashboard erreichbar", url)
        else:
            print(f"[HINWEIS] Dashboard ist derzeit nicht erreichbar: {url}")

    return 1 if failed else 0


def _test_command(runtime: Runtime) -> int:
    commands = [
        ("uv", "run", "ruff", "check", "."),
        ("uv", "run", "ruff", "format", "--check", "."),
        ("uv", "run", "mypy", "."),
        ("uv", "run", "pytest", "-q"),
        ("node", "--check", "dashboard/static/dashboard.js"),
    ]
    result = 0
    for command in commands:
        print("+ " + " ".join(command))
        if not _command_available(command[0]):
            print(f"Befehl {command[0]!r} fehlt.", file=sys.stderr)
            result = 1
            continue
        returncode = _run_process(command, cwd=runtime.project_dir)
        if returncode != 0:
            result = max(result, returncode if returncode > 0 else 1)
    return result


def _configure_project(path: Path | None, *, show: bool) -> int:
    if show:
        configured = _read_configured_project()
        if configured is None:
            print("Kein globales Aeris-Projekt konfiguriert.")
            return 1
        print(_resolve_path(configured, label="Gespeicherter Projektpfad"))
        return 0
    if path is None:
        raise CliError("configure benötigt einen Projektpfad oder --show.")
    project = _resolve_path(path, label="Projektpfad")
    if not _is_project_dir(project):
        raise CliError(f"{project} ist kein Aeris-Projekt.")

    config = _config_file()
    temporary_path: Path | None = None
    try:
        config.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with contextlib.suppress(OSError):
            config.parent.chmod(0o700)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=config.parent,
            prefix=".config.toml.",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            os.chmod(temporary.name, 0o600)
            temporary.write(f"project_dir = {json.dumps(str(project))}\n")
            temporary.flush()
            os.fsync(temporary.fileno())
        temporary_path.replace(config)
        temporary_path = None
        config.chmod(0o600)
    except OSError as exc:
        raise CliError(f"Konfiguration {config} konnte nicht geschrieben werden: {exc}") from exc
    finally:
        if temporary_path is not None:
            with contextlib.suppress(FileNotFoundError):
                temporary_path.unlink()
    print(f"Globales Aeris-Projekt gespeichert: {project}")
    return 0


def _positive_seconds(value: str) -> int:
    try:
        seconds = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("muss eine ganze Zahl sein") from exc
    if seconds <= 0:
        raise argparse.ArgumentTypeError("muss größer als 0 sein")
    return seconds


def _service_name(value: str) -> str:
    if not _SERVICE_NAME_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "darf nur Buchstaben, Ziffern, Punkt, Unterstrich und Bindestrich enthalten"
        )
    return value


def _normalize_runtime_options(argv: Sequence[str]) -> list[str]:
    global_options: list[str] = []
    remaining: list[str] = []
    arguments = list(argv)
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith(("--project-dir=", "--env-file=")):
            global_options.append(argument)
            index += 1
            continue
        if argument in {"--project-dir", "--env-file"} and index + 1 < len(arguments):
            value = arguments[index + 1]
            if not value.startswith("-"):
                global_options.extend((argument, value))
                index += 2
                continue
        remaining.append(argument)
        index += 1
    return [*global_options, *remaining]


def _add_runtime_options(parser: argparse.ArgumentParser, *, suppress_defaults: bool) -> None:
    default: Path | str | None = argparse.SUPPRESS if suppress_defaults else None
    parser.add_argument(
        "--project-dir",
        type=Path,
        default=default,
        help="Pfad zum Aeris-Repository",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=default,
        help="Compose-Umgebungsdatei (relativ zum Repository)",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aeris",
        description="Aegis sicher starten, prüfen und bedienen.",
    )
    parser.add_argument("--version", action="version", version=f"aeris {__version__}")
    _add_runtime_options(parser, suppress_defaults=False)
    subparsers = parser.add_subparsers(dest="command")

    dashboard = subparsers.add_parser("dashboard", help="Dashboard starten und öffnen")
    _add_runtime_options(dashboard, suppress_defaults=True)
    dashboard.add_argument("--no-start", action="store_true", help="Dienste nicht starten")
    dashboard.add_argument("--no-browser", action="store_true", help="Browser nicht öffnen")
    dashboard.add_argument(
        "--no-auth",
        action="store_true",
        help="Anmeldung nur für einen lokalen Test ausschalten",
    )
    dashboard.add_argument(
        "--wait-seconds",
        type=_positive_seconds,
        default=_DEFAULT_DASHBOARD_WAIT_SECONDS,
        metavar="N",
        help="maximale Wartezeit nach dem Start",
    )

    up = subparsers.add_parser("up", help="Dienste bauen und starten")
    _add_runtime_options(up, suppress_defaults=True)
    up.add_argument("--no-build", action="store_true", help="vorhandene Images verwenden")
    down = subparsers.add_parser("down", help="Dienste stoppen; Volumes bleiben erhalten")
    _add_runtime_options(down, suppress_defaults=True)
    status = subparsers.add_parser("status", help="Compose-Servicezustand anzeigen")
    _add_runtime_options(status, suppress_defaults=True)

    logs = subparsers.add_parser("logs", help="Compose-Logs anzeigen")
    _add_runtime_options(logs, suppress_defaults=True)
    logs.add_argument("services", nargs="*", type=_service_name, help="optionale Servicenamen")
    logs.add_argument("-f", "--follow", action="store_true", help="Logausgabe verfolgen")
    logs.add_argument("--tail", type=_positive_seconds, metavar="N", help="letzte N Zeilen")

    doctor = subparsers.add_parser("doctor", help="Voraussetzungen und Konfiguration prüfen")
    _add_runtime_options(doctor, suppress_defaults=True)
    test = subparsers.add_parser("test", help="lokale Qualitätsprüfungen ausführen")
    _add_runtime_options(test, suppress_defaults=True)

    maintenance = subparsers.add_parser("maintenance", help="Event-Retention ausführen")
    _add_runtime_options(maintenance, suppress_defaults=True)
    maintenance.add_argument("--once", action="store_true", help="genau einen Lauf ausführen")

    configure = subparsers.add_parser("configure", help="Projektpfad für globale Aufrufe speichern")
    configure.add_argument("path", nargs="?", type=Path, help="Pfad zum Aeris-Repository")
    configure.add_argument("--show", action="store_true", help="gespeicherten Pfad anzeigen")
    parser.set_defaults(
        command="dashboard",
        no_start=False,
        no_browser=False,
        no_auth=False,
        wait_seconds=_DEFAULT_DASHBOARD_WAIT_SECONDS,
    )
    return parser


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "configure":
        return _configure_project(args.path, show=args.show)

    runtime = _runtime(args)
    if args.command == "dashboard":
        return _dashboard_command(runtime, args)
    if args.command == "up":
        return _up(runtime, build=not args.no_build)
    if args.command == "down":
        return _compose(runtime, ("down",))
    if args.command == "status":
        return _compose(runtime, ("ps",))
    if args.command == "logs":
        arguments = ["logs"]
        if args.follow:
            arguments.append("--follow")
        if args.tail is not None:
            arguments.extend(("--tail", str(args.tail)))
        arguments.extend(args.services)
        return _compose(runtime, arguments)
    if args.command == "doctor":
        return _doctor(runtime)
    if args.command == "test":
        return _test_command(runtime)
    if args.command == "maintenance":
        if args.once:
            return _compose(
                runtime,
                ("run", "--rm", "maintenance", "python", "-m", "core.maintenance", "--once"),
            )
        return _compose(runtime, ("up", "-d", "maintenance"))
    raise CliError(f"Unbekannter Befehl: {args.command}")


def run(argv: Sequence[str] | None = None) -> int:
    """Parse and execute one CLI invocation, returning its process status."""
    try:
        try:
            arguments = sys.argv[1:] if argv is None else argv
            args = _parser().parse_args(_normalize_runtime_options(arguments))
        except SystemExit as exc:
            return exc.code if isinstance(exc.code, int) else 1
        return _dispatch(args)
    except CliError as exc:
        print(f"aeris: {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\naeris: abgebrochen", file=sys.stderr)
        return 130


def main() -> None:
    raise SystemExit(run())
