from __future__ import annotations

import os
import threading
import time
from collections.abc import Sequence
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from aeris import cli


@pytest.fixture
def cli_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    (project / "deploy").mkdir(parents=True)
    (project / "deploy/docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (project / "pyproject.toml").write_text(
        "[project]\nname='aegis'\n[project.scripts]\naeris='aeris.cli:main'\n",
        encoding="utf-8",
    )
    logs = project / "host-logs"
    logs.mkdir()
    (logs / "auth.log").write_text("", encoding="utf-8")
    (project / ".env").write_text(
        "\n".join(
            (
                "POSTGRES_PASSWORD=postgres-test-secret",
                "REDIS_PASSWORD=redis-test-secret",
                "AEGIS_API_PASSWORD=dashboard-test-secret",
                f"HOST_LOG_DIR={logs}",
                "HOST_AGENT_LOG_PATHS=/host/var/log/auth.log",
                "AEGIS_HTTP_PORT=8123",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    return project


@pytest.fixture(autouse=True)
def isolated_cli_environment(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "config"))
    monkeypatch.delenv("AERIS_PROJECT_DIR", raising=False)
    monkeypatch.delenv("AERIS_DASHBOARD_URL", raising=False)
    for name in cli._REQUIRED_SECRETS:
        monkeypatch.delenv(name, raising=False)


def test_bare_aeris_opens_healthy_dashboard(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    opened: list[str] = []
    starts: list[tuple[bool, bool, tuple[str, ...]]] = []

    def open_browser(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.chdir(cli_project)
    monkeypatch.setattr(cli, "__file__", str(cli_project / "aeris/cli.py"))
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_open_browser", open_browser)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)

    def start(
        _runtime: cli.Runtime,
        *,
        build: bool,
        auth_disabled: bool = False,
        services: Sequence[str] = (),
    ) -> int:
        starts.append((build, auth_disabled, tuple(services)))
        return 0

    monkeypatch.setattr(cli, "_up", start)

    assert cli.run([]) == 0
    assert opened == ["http://127.0.0.1:8123/"]
    assert starts == [(False, False, ("app",))]


def test_bare_aeris_starts_waits_and_opens_dashboard(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    health_results = iter((False, True))
    starts: list[bool] = []
    opened: list[str] = []

    def start(_runtime: cli.Runtime, *, build: bool, auth_disabled: bool = False) -> int:
        starts.append(build)
        assert auth_disabled is False
        return 0

    def open_browser(url: str) -> bool:
        opened.append(url)
        return True

    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url, **_kwargs: next(health_results))
    monkeypatch.setattr(cli, "_up", start)
    monkeypatch.setattr(cli, "_open_browser", open_browser)

    assert cli.run(["--project-dir", str(cli_project)]) == 0
    assert starts == [True]
    assert opened == ["http://127.0.0.1:8123/"]


def test_dashboard_no_start_never_touches_compose(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: False)
    monkeypatch.setattr(
        cli, "_up", lambda *_args, **_kwargs: pytest.fail("--no-start touched Compose")
    )
    monkeypatch.setattr(
        cli, "_open_browser", lambda _url: pytest.fail("unhealthy dashboard opened browser")
    )

    result = cli.run(["--project-dir", str(cli_project), "dashboard", "--no-start", "--no-browser"])

    assert result == 1


def test_dashboard_no_browser_never_opens_browser(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_up", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)
    monkeypatch.setattr(
        cli, "_open_browser", lambda _url: pytest.fail("--no-browser opened a browser")
    )

    assert cli.run(["--project-dir", str(cli_project), "dashboard", "--no-browser"]) == 0


def test_dashboard_no_auth_is_transient_and_reconciles_healthy_app(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    starts: list[tuple[bool, bool, tuple[str, ...]]] = []

    def start(
        _runtime: cli.Runtime,
        *,
        build: bool,
        auth_disabled: bool = False,
        services: Sequence[str] = (),
    ) -> int:
        starts.append((build, auth_disabled, tuple(services)))
        return 0

    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)
    monkeypatch.setattr(cli, "_up", start)

    assert (
        cli.run(["--project-dir", str(cli_project), "dashboard", "--no-auth", "--no-browser"]) == 0
    )
    assert starts == [(True, True, ("app",))]
    assert "WARNUNG" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("name", "value"),
    [
        ("AEGIS_BIND_ADDRESS", "0.0.0.0"),
        ("AEGIS_BIND_ADDRESS", "192.0.2.10"),
        ("AERIS_DASHBOARD_URL", "https://aegis.example.test/"),
    ],
)
def test_dashboard_no_auth_rejects_nonlocal_exposure_before_compose(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    value: str,
) -> None:
    monkeypatch.setenv(name, value)
    monkeypatch.setattr(
        cli, "_up", lambda *_args, **_kwargs: pytest.fail("unsafe test mode touched Compose")
    )

    assert (
        cli.run(["--project-dir", str(cli_project), "dashboard", "--no-auth", "--no-browser"]) == 2
    )


def test_dashboard_no_auth_cannot_be_combined_with_no_start(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_up", lambda *_args, **_kwargs: pytest.fail("invalid options touched Compose")
    )

    assert (
        cli.run(
            [
                "--project-dir",
                str(cli_project),
                "dashboard",
                "--no-auth",
                "--no-start",
            ]
        )
        == 2
    )


@pytest.mark.parametrize(
    ("arguments", "expected_suffix"),
    [
        (["up"], ["up", "-d", "--build"]),
        (["up", "--no-build"], ["up", "-d"]),
        (["down"], ["down"]),
        (["status"], ["ps"]),
        (
            ["logs", "app", "worker", "--follow", "--tail", "25"],
            ["logs", "--follow", "--tail", "25", "app", "worker"],
        ),
        (["maintenance"], ["up", "-d", "maintenance"]),
        (
            ["maintenance", "--once"],
            ["run", "--rm", "maintenance", "python", "-m", "core.maintenance", "--once"],
        ),
    ],
)
def test_compose_commands_use_expected_safe_argv(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected_suffix: list[str],
) -> None:
    calls: list[list[str]] = []

    def run_process(argv: Sequence[str], **_kwargs: Any) -> int:
        calls.append(list(argv))
        return 0

    monkeypatch.setattr(cli, "_compose_executable", lambda _root: ("docker", "compose"))
    monkeypatch.setattr(cli, "_run_process", run_process)

    assert cli.run(["--project-dir", str(cli_project), *arguments]) == 0
    assert calls[-1][-len(expected_suffix) :] == expected_suffix
    assert "--volumes" not in calls[-1]
    assert "-v" not in calls[-1]
    project_name_index = calls[-1].index("--project-name")
    assert calls[-1][project_name_index + 1] == "aegis"


def test_health_identity_rejects_an_unrelated_http_service() -> None:
    assert cli._is_aegis_health_payload({"status": "ok", "service": "aegis"})
    assert not cli._is_aegis_health_payload({"status": "ok"})
    assert not cli._is_aegis_health_payload({"status": "ok", "service": "another-app"})


def test_subprocesses_use_argument_lists_and_never_a_shell(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def fake_run(argv: Sequence[str], **kwargs: Any) -> SimpleNamespace:
        calls.append((list(argv), kwargs))
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr("aeris.cli.shutil.which", lambda _name: "/usr/bin/tool")
    monkeypatch.setattr("aeris.cli.subprocess.run", fake_run)

    assert cli.run(["--project-dir", str(cli_project), "status"]) == 0
    assert calls
    assert all(call[1]["shell"] is False for call in calls)
    assert all(isinstance(call[0], list) for call in calls)


def test_doctor_does_not_print_secret_values(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "same-secret-value"
    env_file = cli_project / ".env"
    env_file.write_text(
        f"POSTGRES_PASSWORD={secret}\nREDIS_PASSWORD={secret}\nAEGIS_API_PASSWORD={secret}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(cli, "_compose_executable", lambda _root: ("docker", "compose"))
    monkeypatch.setattr(cli, "_run_process", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: False)

    assert cli.run(["--project-dir", str(cli_project), "doctor"]) == 1
    captured = capsys.readouterr()
    output = captured.out + captured.err
    assert secret not in output
    assert "unterschiedlich" in output


def test_configure_persists_project_for_invocations_from_any_directory(
    cli_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    assert cli.run(["configure", str(cli_project)]) == 0
    config = Path(os.environ["XDG_CONFIG_HOME"]) / "aeris/config.toml"
    assert config.is_file()
    assert config.stat().st_mode & 0o777 == 0o600

    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_open_browser", lambda _url: True)
    monkeypatch.setattr(cli, "_up", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)

    assert cli.run(["dashboard", "--no-browser"]) == 0


def test_invalid_aeris_project_environment_fails_closed(
    cli_project: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    invalid = tmp_path / "not-a-project"
    invalid.mkdir()
    monkeypatch.chdir(cli_project)
    monkeypatch.setenv("AERIS_PROJECT_DIR", str(invalid))

    assert cli.run(["status"]) == 2


def test_test_command_runs_every_check_without_external_execution(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def run_process(argv: Sequence[str], **_kwargs: Any) -> int:
        calls.append(tuple(argv))
        return 0

    monkeypatch.setattr(cli, "_command_available", lambda _command: True)
    monkeypatch.setattr(cli, "_run_process", run_process)

    assert cli.run(["--project-dir", str(cli_project), "test"]) == 0
    assert ("uv", "run", "ruff", "check", ".") in calls
    assert ("uv", "run", "ruff", "format", "--check", ".") in calls
    assert ("uv", "run", "mypy", ".") in calls
    assert ("uv", "run", "pytest", "-q") in calls
    assert ("node", "--check", "dashboard/static/dashboard.js") in calls


def test_dashboard_url_is_printed_before_compose_failure(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: False)
    monkeypatch.setattr(cli, "_up", lambda *_args, **_kwargs: 17)

    assert cli.run(["--project-dir", str(cli_project), "dashboard", "--no-browser"]) == 17
    assert "Dashboard: http://127.0.0.1:8123/" in capsys.readouterr().out


def test_custom_dashboard_path_uses_root_health_endpoint(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    dashboard_url = "https://aegis.example.test/console/"
    monkeypatch.setenv("AERIS_DASHBOARD_URL", dashboard_url)
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_up", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)

    assert (
        cli.run(
            [
                "dashboard",
                "--project-dir",
                str(cli_project),
                "--no-browser",
            ]
        )
        == 0
    )
    assert cli._health_url(dashboard_url) == "https://aegis.example.test/health"
    assert f"Dashboard: {dashboard_url}" in capsys.readouterr().out


@pytest.mark.parametrize(
    "url",
    [
        "https://aegis.example.test/console/?token=do-not-print",
        "https://user:password@aegis.example.test/",
        "http://[broken",
        "http://aegis.example.test:99999/",
    ],
)
def test_invalid_dashboard_urls_fail_without_echoing_values(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    url: str,
) -> None:
    monkeypatch.setenv("AERIS_DASHBOARD_URL", url)

    assert cli.run(["--project-dir", str(cli_project), "dashboard", "--no-start"]) == 2
    captured = capsys.readouterr()
    assert url not in captured.out + captured.err
    assert "do-not-print" not in captured.out + captured.err


def test_browser_errors_are_reported_without_failing_dashboard(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: True)
    monkeypatch.setattr(cli, "_up", lambda *_args, **_kwargs: 0)
    monkeypatch.setattr(cli, "_wait_for_dashboard", lambda *_args: True)

    def fail_browser(*_args: Any, **_kwargs: Any) -> bool:
        raise OSError("no browser")

    monkeypatch.setattr("aeris.cli.webbrowser.open", fail_browser)

    assert cli.run(["--project-dir", str(cli_project), "dashboard"]) == 0
    assert "Browser konnte nicht automatisch geöffnet werden" in capsys.readouterr().out


def test_health_probe_has_a_hard_outer_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()
    calls: list[None] = []

    def blocked_urlopen(*_args: Any, **_kwargs: Any) -> Any:
        calls.append(None)
        release.wait(1)
        raise OSError("blocked resolver")

    monkeypatch.setattr("aeris.cli.urllib.request.urlopen", blocked_urlopen)
    started = time.monotonic()
    try:
        assert cli._dashboard_healthy("http://timeout.example.test/", timeout=0.01) is False
        assert time.monotonic() - started < 0.2
        assert cli._dashboard_healthy("http://timeout.example.test/", timeout=0.01) is False
        assert len(calls) == 2
    finally:
        release.set()


def test_logs_rejects_option_injection_as_service_name(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli, "_run_process", lambda *_args, **_kwargs: pytest.fail("process was started")
    )

    assert cli.run(["--project-dir", str(cli_project), "logs", "--", "--volumes"]) == 2


def test_doctor_checks_daemon_with_legacy_compose(
    cli_project: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    calls: list[tuple[str, ...]] = []

    monkeypatch.setattr(cli, "_compose_executable", lambda _root: ("docker-compose",))
    monkeypatch.setattr(cli, "_command_available", lambda command: command != "docker")
    monkeypatch.setattr(cli, "_dashboard_healthy", lambda _url: False)

    def run_process(argv: Sequence[str], **_kwargs: Any) -> int:
        command = tuple(argv)
        calls.append(command)
        return 1 if command[-2:] == ("ps", "-q") else 0

    monkeypatch.setattr(cli, "_run_process", run_process)

    assert cli.run(["--project-dir", str(cli_project), "doctor"]) == 1
    assert any(command[-2:] == ("ps", "-q") for command in calls)
    assert "[FEHLER] Docker-Daemon" in capsys.readouterr().out


def test_relative_host_log_dir_is_resolved_like_compose(cli_project: Path) -> None:
    env_file = cli_project / ".env"
    contents = env_file.read_text(encoding="utf-8")
    contents = contents.replace(
        f"HOST_LOG_DIR={cli_project / 'host-logs'}", "HOST_LOG_DIR=../host-logs"
    )
    env_file.write_text(contents, encoding="utf-8")
    args = cli._parser().parse_args(["--project-dir", str(cli_project), "doctor"])
    runtime = cli._runtime(args)

    assert cli._host_log_sources(runtime) == [cli_project / "host-logs/auth.log"]


def test_host_log_sources_reject_mount_traversal(cli_project: Path) -> None:
    env_file = cli_project / ".env"
    contents = env_file.read_text(encoding="utf-8")
    contents = contents.replace(
        "HOST_AGENT_LOG_PATHS=/host/var/log/auth.log",
        "HOST_AGENT_LOG_PATHS=/host/var/log/../../etc/shadow,/host/var/log/auth.log",
    )
    env_file.write_text(contents, encoding="utf-8")
    args = cli._parser().parse_args(["--project-dir", str(cli_project), "doctor"])
    runtime = cli._runtime(args)

    assert cli._host_log_sources(runtime) == [cli_project / "host-logs/auth.log"]


def test_test_command_maps_negative_returncode_to_failure(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls = 0

    def run_process(_argv: Sequence[str], **_kwargs: Any) -> int:
        nonlocal calls
        calls += 1
        return -9 if calls == 1 else 0

    monkeypatch.setattr(cli, "_command_available", lambda _command: True)
    monkeypatch.setattr(cli, "_run_process", run_process)

    assert cli.run(["--project-dir", str(cli_project), "test"]) == 1


def test_dotenv_comments_and_interpolation_match_runtime_values(cli_project: Path) -> None:
    env_file = cli_project / ".env"
    env_file.write_text(
        "BASE=alpha\n"
        "POSTGRES_PASSWORD=postgres-${BASE} # inline comment\n"
        "REDIS_PASSWORD='redis-${BASE}'\n"
        'AEGIS_API_PASSWORD="dashboard-${BASE}-secret"\n',
        encoding="utf-8",
    )
    args = cli._parser().parse_args(["--project-dir", str(cli_project), "doctor"])
    runtime = cli._runtime(args)

    assert runtime.env_values["POSTGRES_PASSWORD"] == "postgres-alpha"
    assert runtime.env_values["REDIS_PASSWORD"] == "redis-${BASE}"
    assert runtime.env_values["AEGIS_API_PASSWORD"] == "dashboard-alpha-secret"


def test_dotenv_last_assignment_controls_quote_and_expansion(cli_project: Path) -> None:
    env_file = cli_project / ".env"
    env_file.write_text(
        "BASE=alpha\n"
        "POSTGRES_PASSWORD='literal-${BASE}'\n"
        "POSTGRES_PASSWORD=postgres-${BASE}\n"
        "REDIS_PASSWORD=${MISSING:-redis-default}\n"
        "AEGIS_API_PASSWORD=dashboard-$BASE-secret\n",
        encoding="utf-8",
    )
    args = cli._parser().parse_args(["--project-dir", str(cli_project), "doctor"])
    runtime = cli._runtime(args)

    assert runtime.env_values["POSTGRES_PASSWORD"] == "postgres-alpha"
    assert runtime.env_values["REDIS_PASSWORD"] == "redis-default"
    assert runtime.env_values["AEGIS_API_PASSWORD"] == "dashboard-alpha-secret"


def test_explicit_project_does_not_resolve_other_candidates(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        cli,
        "_candidate_project_dirs",
        lambda: pytest.fail("unrelated candidates were resolved"),
    )

    assert cli._resolve_project_dir(cli_project) == cli_project.resolve()


def test_configure_reports_unwritable_config_home(
    cli_project: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    blocked = tmp_path / "not-a-directory"
    blocked.write_text("blocked", encoding="utf-8")
    monkeypatch.setenv("XDG_CONFIG_HOME", str(blocked))

    assert cli.run(["configure", str(cli_project)]) == 2
    assert "konnte nicht geschrieben werden" in capsys.readouterr().err


def test_unrelated_compose_project_is_not_auto_detected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    unrelated = tmp_path / "unrelated"
    (unrelated / "deploy").mkdir(parents=True)
    (unrelated / "deploy/docker-compose.yml").write_text("services: {}\n", encoding="utf-8")
    (unrelated / "pyproject.toml").write_text(
        "[project]\nname='aegis'\n[project.scripts]\naeris='aeris.cli:main'\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(unrelated)
    monkeypatch.setattr(cli, "_read_configured_project", lambda: None)
    monkeypatch.setattr(cli, "__file__", str(tmp_path / "installed/aeris/cli.py"))

    assert cli.run(["dashboard", "--no-start"]) == 2


def test_runtime_options_work_between_log_services(
    cli_project: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[tuple[str, ...]] = []

    def run_process(argv: Sequence[str], **_kwargs: Any) -> int:
        calls.append(tuple(argv))
        return 0

    monkeypatch.setattr(cli, "_compose_executable", lambda _root: ("docker", "compose"))
    monkeypatch.setattr(cli, "_run_process", run_process)

    assert (
        cli.run(
            [
                "logs",
                "app",
                "--project-dir",
                str(cli_project),
                "worker",
            ]
        )
        == 0
    )
    assert calls[-1][-3:] == ("logs", "app", "worker")
